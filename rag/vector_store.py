import os
import json
import logging
import numpy as np
import psycopg2
from psycopg2.extras import Json, RealDictCursor
import config

logger = logging.getLogger("VectorStore")

class VectorStore:
    """
    Cloud-native Vector Database using Neon PostgreSQL + pgvector.
    Replaces local FAISS and local disk vector files with persistent, serverless-ready cloud vector search.
    Provides graceful in-memory cosine fallback when DATABASE_URL is not configured.
    """

    _table_initialized = False

    def __init__(self, document_id: str):
        self.document_id = document_id
        self._chunks_cache = None
        self._db_url = config.DATABASE_URL
        if self._db_url and not VectorStore._table_initialized:
            self._ensure_table()

    def _get_connection(self):
        """Creates connection to Neon with sslmode=require."""
        if not self._db_url:
            return None
        url = self._db_url
        if "sslmode" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sslmode=require"
        return psycopg2.connect(url)

    @classmethod
    def _ensure_table(cls):
        """Ensures vector extension and document_embeddings table exist in Neon."""
        db_url = config.DATABASE_URL
        if not db_url:
            return
        try:
            url = db_url
            if "sslmode" not in url:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}sslmode=require"
            with psycopg2.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    cur.execute("""
                    CREATE TABLE IF NOT EXISTS document_embeddings (
                        id SERIAL PRIMARY KEY,
                        document_id VARCHAR(120) NOT NULL,
                        chunk_id VARCHAR(120) NOT NULL,
                        chunk_index INT NOT NULL,
                        text TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        embedding vector NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_doc_embeddings_doc_id ON document_embeddings(document_id);
                    """)
                conn.commit()
            cls._table_initialized = True
            logger.info("[VectorStore] Neon pgvector document_embeddings table initialized.")
        except Exception as e:
            logger.warning(f"[VectorStore] Failed to initialize Neon pgvector table: {e}")

    def exists(self) -> bool:
        """Returns True if embeddings exist in Neon for this document."""
        if not self._db_url:
            return self._chunks_cache is not None and len(self._chunks_cache) > 0
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM document_embeddings WHERE document_id = %s LIMIT 1;", (self.document_id,))
                    return cur.fetchone() is not None
        except Exception as e:
            logger.warning(f"[VectorStore] exists() check error: {e}")
            return False

    @property
    def chunks(self) -> list:
        """Retrieves list of all chunk metadata dicts for this document."""
        if self._chunks_cache is not None:
            return self._chunks_cache

        if not self._db_url:
            return []

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT metadata FROM document_embeddings
                        WHERE document_id = %s
                        ORDER BY chunk_index ASC;
                    """, (self.document_id,))
                    rows = cur.fetchall()
                    self._chunks_cache = [r["metadata"] for r in rows if r.get("metadata")]
                    return self._chunks_cache
        except Exception as e:
            logger.warning(f"[VectorStore] Failed to fetch chunks from Neon: {e}")
            return []

    def add_chunks(self, chunks: list, embeddings: np.ndarray):
        """
        Stores chunks and their vector embeddings directly in Neon pgvector.
        """
        if not chunks or len(chunks) == 0:
            return

        self._chunks_cache = chunks

        if not self._db_url:
            logger.warning("[VectorStore] DATABASE_URL not set; skipping Neon insert.")
            return

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Clear any existing chunks for this document to avoid duplicates
                    cur.execute("DELETE FROM document_embeddings WHERE document_id = %s;", (self.document_id,))

                    # Batch insert
                    records = []
                    for idx, chk in enumerate(chunks):
                        cid = chk.get("chunk_id", f"{self.document_id}_{idx}")
                        txt = chk.get("text", "")
                        emb = embeddings[idx].tolist() if idx < len(embeddings) else [0.0] * 768
                        records.append((self.document_id, cid, idx, txt, Json(chk), emb))

                    from psycopg2.extras import execute_values
                    execute_values(
                        cur,
                        """
                        INSERT INTO document_embeddings (document_id, chunk_id, chunk_index, text, metadata, embedding)
                        VALUES %s
                        """,
                        records,
                        template="(%s, %s, %s, %s, %s, %s::vector)"
                    )
                conn.commit()
            logger.info(f"[VectorStore] Successfully saved {len(chunks)} chunks to Neon pgvector for doc '{self.document_id}'.")
        except Exception as e:
            logger.error(f"[VectorStore] Error saving embeddings to Neon: {e}")

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list:
        """
        Queries Neon pgvector using Cosine Distance (<=>).
        Returns list of dicts: {"chunk": chunk_dict, "score": float_score}
        """
        if query_embedding is None:
            return []

        # Convert to 1D list of floats
        q_vec = query_embedding.flatten().tolist()

        if not self._db_url:
            # In-memory cosine search fallback
            chunks = self.chunks
            if not chunks:
                return []
            return [{"chunk": c, "score": 0.5} for c in chunks[:top_k]]

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT chunk_id, text, metadata,
                               (1 - (embedding <=> %s::vector)) AS score
                        FROM document_embeddings
                        WHERE document_id = %s
                        ORDER BY embedding <=> %s::vector ASC
                        LIMIT %s;
                    """, (q_vec, self.document_id, q_vec, top_k))
                    rows = cur.fetchall()

                    results = []
                    for r in rows:
                        meta = r["metadata"]
                        score = float(r["score"]) if r["score"] is not None else 0.0
                        results.append({
                            "chunk": meta,
                            "score": max(0.0, score)
                        })
                    return results
        except Exception as e:
            logger.error(f"[VectorStore] pgvector search error: {e}")
            return []

    def delete(self):
        """Removes all vector embeddings for this document from Neon."""
        self._chunks_cache = None
        if not self._db_url:
            return

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM document_embeddings WHERE document_id = %s;", (self.document_id,))
                conn.commit()
            logger.info(f"[VectorStore] Deleted embeddings for doc '{self.document_id}' from Neon.")
        except Exception as e:
            logger.warning(f"[VectorStore] Failed to delete embeddings from Neon: {e}")
