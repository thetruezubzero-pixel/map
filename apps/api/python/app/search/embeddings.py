from __future__ import annotations

import numpy as np

_MODEL = None
EMBEDDING_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2


def get_model():
    """Lazily loads the embedding model -- sentence-transformers/torch are
    heavy, so nothing imports them until an embedding is actually needed."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _MODEL


def embed(text: str) -> np.ndarray:
    model = get_model()
    return np.asarray(model.encode(text), dtype=np.float32)


def embed_batch(texts: list[str]) -> np.ndarray:
    model = get_model()
    return np.asarray(model.encode(texts), dtype=np.float32)
