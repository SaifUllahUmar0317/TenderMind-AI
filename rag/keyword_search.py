import re
import math
from collections import Counter

class BM25Search:
    """
    Lightweight BM25 keyword search engine for document chunks.
    Provides term-frequency & inverse-document-frequency relevance scoring.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.chunks = []
        self.doc_tokens = []
        self.doc_lens = []
        self.avg_dl = 0.0
        self.doc_freqs = Counter()
        self.N = 0

    @staticmethod
    def _tokenize(text: str) -> list:
        """Tokenizes and normalizes text into lowercase words."""
        return re.findall(r'\b\w+\b', text.lower())

    def index_chunks(self, chunks: list):
        """
        Indexes a list of chunk dicts for BM25 keyword retrieval.
        """
        self.chunks = chunks
        self.N = len(chunks)
        if self.N == 0:
            return

        self.doc_tokens = []
        self.doc_lens = []
        self.doc_freqs = Counter()

        total_len = 0
        for chunk in chunks:
            text = chunk.get("text", "")
            tokens = self._tokenize(text)
            self.doc_tokens.append(tokens)
            l = len(tokens)
            self.doc_lens.append(l)
            total_len += l

            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.doc_freqs[token] += 1

        self.avg_dl = total_len / self.N if self.N > 0 else 1.0

    def search(self, query: str, top_k: int = 5) -> list:
        """
        Performs BM25 keyword search for query against indexed chunks.
        Returns list of dicts: {"chunk": chunk_dict, "score": float_bm25_score}
        """
        if self.N == 0 or not query.strip():
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = [0.0] * self.N

        for q_token in query_tokens:
            df = self.doc_freqs.get(q_token, 0)
            if df == 0:
                continue

            # Calculate BM25 IDF
            idf = math.log((self.N - df + 0.5) / (df + 0.5) + 1.0)

            for i, tokens in enumerate(self.doc_tokens):
                tf = tokens.count(q_token)
                if tf == 0:
                    continue

                dl = self.doc_lens[i]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (dl / self.avg_dl))

                scores[i] += idf * (numerator / denominator)

        # Normalize BM25 scores between 0.0 and 1.0
        max_score = max(scores) if scores else 1.0
        if max_score > 0:
            norm_scores = [s / max_score for s in scores]
        else:
            norm_scores = scores

        ranked_indices = sorted(range(self.N), key=lambda i: norm_scores[i], reverse=True)[:top_k]

        results = []
        for idx in ranked_indices:
            if norm_scores[idx] > 0.0:
                results.append({
                    "chunk": self.chunks[idx],
                    "score": round(norm_scores[idx], 4)
                })

        return results
