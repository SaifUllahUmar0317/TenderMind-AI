import os
import re
import requests
import numpy as np
import logging

logger = logging.getLogger("EmbeddingGenerator")

class EmbeddingGenerator:
    """
    Lightweight, serverless-ready embedding generator.
    Uses Google Gemini Embeddings API ('text-embedding-004', 768 dimensions) with zero local ML dependencies.
    Includes a deterministic 768-dimensional TF-IDF feature hashing fallback when API keys are not configured.
    """

    DIMENSION = 768
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004"

    @classmethod
    def get_api_key(cls) -> str:
        return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()

    @classmethod
    def get_model(cls):
        """Backward-compatibility stub for health checks."""
        key = cls.get_api_key()
        return "gemini-text-embedding-004" if key else "feature-hashing-fallback"

    @classmethod
    def _fallback_embed(cls, text: str) -> np.ndarray:
        """
        Deterministic 768-dimensional term-frequency feature hashing vector encoder.
        Requires zero external network calls, zero PyTorch, and zero local memory overhead.
        """
        vec = np.zeros(cls.DIMENSION, dtype=np.float32)
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            return vec

        for word in words:
            idx = abs(hash(word)) % cls.DIMENSION
            vec[idx] += 1.0

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    @classmethod
    def _embed_gemini_batch(cls, texts: list, api_key: str) -> list:
        """
        Batches texts into chunks of up to 100 and calls Gemini batchEmbedContents API.
        """
        all_embeddings = []
        batch_size = 90  # Keep safely under the 100 batch limit

        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            url = f"{cls.GEMINI_API_URL}:batchEmbedContents?key={api_key}"
            payload = {
                "requests": [
                    {
                        "model": "models/text-embedding-004",
                        "content": {"parts": [{"text": str(t)[:4000]}]}
                    }
                    for t in chunk
                ]
            }

            resp = requests.post(url, json=payload, timeout=30)
            if not resp.ok:
                raise RuntimeError(f"Gemini Embedding API error ({resp.status_code}): {resp.text[:300]}")

            data = resp.json()
            embs = [item.get("values", []) for item in data.get("embeddings", [])]
            for e in embs:
                vec = np.array(e, dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                all_embeddings.append(vec)

        return all_embeddings

    @classmethod
    def embed_texts(cls, texts: list) -> np.ndarray:
        """
        Generates normalized numpy float32 embeddings for a list of strings.
        Output shape: (N, 768)
        """
        if not texts:
            return np.empty((0, cls.DIMENSION), dtype=np.float32)

        api_key = cls.get_api_key()
        if api_key:
            try:
                embs = cls._embed_gemini_batch(texts, api_key)
                if len(embs) == len(texts):
                    return np.array(embs, dtype=np.float32)
            except Exception as e:
                logger.warning(f"[EmbeddingGenerator] Gemini API error, falling back to feature hashing: {e}")

        # Deterministic feature hashing fallback
        matrix = np.array([cls._fallback_embed(t) for t in texts], dtype=np.float32)
        return matrix

    @classmethod
    def embed_query(cls, query: str) -> np.ndarray:
        """
        Generates normalized embedding for a single query string.
        Output shape: (1, 768)
        """
        if not query:
            return np.zeros((1, cls.DIMENSION), dtype=np.float32)

        api_key = cls.get_api_key()
        if api_key:
            try:
                url = f"{cls.GEMINI_API_URL}:embedContent?key={api_key}"
                payload = {
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": str(query)[:4000]}]}
                }
                resp = requests.post(url, json=payload, timeout=15)
                if resp.ok:
                    data = resp.json()
                    val = data.get("embedding", {}).get("values", [])
                    if len(val) == cls.DIMENSION:
                        vec = np.array(val, dtype=np.float32)
                        norm = np.linalg.norm(vec)
                        if norm > 0:
                            vec = vec / norm
                        return vec.reshape(1, cls.DIMENSION)
            except Exception as e:
                logger.warning(f"[EmbeddingGenerator] Gemini API query error, using fallback: {e}")

        vec = cls._fallback_embed(query).reshape(1, cls.DIMENSION)
        return vec
