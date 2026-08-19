import os
import re
import warnings
import numpy as np

warnings.filterwarnings("ignore")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Safe single-threaded BLAS to avoid Windows OpenBLAS thread allocation exhaustion
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import threading

try:
    import torch
    # Use balanced threads for fast CPU tensor encoding
    torch.set_num_threads(min(4, os.cpu_count() or 2))
except Exception:
    pass

class EmbeddingGenerator:
    """
    High-speed embedding generator wrapping free, open-source SentenceTransformer ('all-MiniLM-L6-v2').
    Includes fallback feature-hashing vector encoder if PyTorch page file memory is constrained.
    Thread-safe singleton prevents race conditions during startup or concurrent requests.
    """

    _model = None
    _use_fallback = False
    _lock = threading.Lock()

    @classmethod
    def get_model(cls):
        if cls._use_fallback:
            return None

        if cls._model is None:
            with cls._lock:
                if cls._model is None and not cls._use_fallback:
                    try:
                        from sentence_transformers import SentenceTransformer
                        cls._model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
                    except Exception as e:
                        # Fallback to feature hashing encoder on memory-constrained Windows page file limit
                        cls._use_fallback = True
                        return None
        return cls._model

    @classmethod
    def _fallback_embed(cls, text: str) -> np.ndarray:
        """Lightweight 384-dimensional term-frequency feature hashing vector encoder."""
        vec = np.zeros(384, dtype=np.float32)
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            return vec

        for word in words:
            idx = abs(hash(word)) % 384
            vec[idx] += 1.0

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    @classmethod
    def embed_texts(cls, texts: list) -> np.ndarray:
        """
        Generates normalized numpy float32 embeddings for a list of strings in fast batches.
        Output shape: (N, 384)
        """
        if not texts:
            return np.empty((0, 384), dtype=np.float32)

        model = cls.get_model()
        if model is not None:
            try:
                embeddings = model.encode(
                    texts,
                    batch_size=128,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False
                )
                return embeddings.astype(np.float32)
            except Exception:
                cls._use_fallback = True

        # Fallback encoding
        matrix = np.array([cls._fallback_embed(t) for t in texts], dtype=np.float32)
        return matrix

    @classmethod
    def embed_query(cls, query: str) -> np.ndarray:
        """
        Generates normalized embedding for a single query string.
        Output shape: (1, 384)
        """
        if not query:
            return np.zeros((1, 384), dtype=np.float32)

        model = cls.get_model()
        if model is not None:
            try:
                emb = model.encode([query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
                return emb.astype(np.float32)
            except Exception:
                cls._use_fallback = True

        vec = cls._fallback_embed(query).reshape(1, 384)
        return vec
