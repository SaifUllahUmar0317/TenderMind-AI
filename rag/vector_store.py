import os
import json
import faiss
import numpy as np
from config import TEMP_FOLDER

VECTOR_STORE_DIR = os.path.join(TEMP_FOLDER, "vector_stores")
os.makedirs(VECTOR_STORE_DIR, exist_ok=True)

class VectorStore:
    """
    FAISS-based local vector database for storing and querying document embeddings.
    Isolates vector indices per document ID.
    """

    def __init__(self, document_id: str):
        self.document_id = document_id
        self.dimension = 384  # SentenceTransformer all-MiniLM-L6-v2 dimension
        self.index_path = os.path.join(VECTOR_STORE_DIR, f"{document_id}.faiss")
        self.meta_path = os.path.join(VECTOR_STORE_DIR, f"{document_id}_meta.json")

        self.index = None
        self.chunks = []
        self._load_or_create()

    def _load_or_create(self):
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            try:
                self.index = faiss.read_index(self.index_path)
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    self.chunks = json.load(f)
            except Exception:
                self.index = faiss.IndexFlatIP(self.dimension)
                self.chunks = []
        else:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.chunks = []

    def add_chunks(self, chunks: list, embeddings: np.ndarray):
        """
        Adds text chunks and corresponding embeddings to FAISS index.
        """
        if len(chunks) == 0 or embeddings.shape[0] == 0:
            return

        # Ensure float32 matrix
        embeddings = embeddings.astype(np.float32)

        # Add to FAISS index
        self.index.add(embeddings)
        self.chunks.extend(chunks)

        # Persist index and metadata
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, indent=2, ensure_ascii=False)

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list:
        """
        Queries FAISS index using vector similarity.
        Returns list of dicts: {"chunk": chunk_dict, "score": float_score}
        """
        if self.index is None or self.index.ntotal == 0 or len(self.chunks) == 0:
            return []

        top_k = min(top_k, self.index.ntotal)
        query_embedding = query_embedding.astype(np.float32)

        distances, indices = self.index.search(query_embedding, top_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(self.chunks) and idx >= 0:
                results.append({
                    "chunk": self.chunks[idx],
                    "score": float(dist)
                })

        return results

    def delete(self):
        """Removes persisted FAISS vector index files."""
        if os.path.exists(self.index_path):
            try:
                os.remove(self.index_path)
            except Exception:
                pass
        if os.path.exists(self.meta_path):
            try:
                os.remove(self.meta_path)
            except Exception:
                pass
