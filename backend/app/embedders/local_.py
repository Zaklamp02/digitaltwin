"""Local sentence-transformers embedder (offline-capable fallback)."""

from __future__ import annotations


class LocalEmbedder:
    name = "local"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        # Imported lazily so the openai path doesn't require sentence-transformers.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]
