
from functools import lru_cache
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import get_settings


@lru_cache
def _get_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(settings.embedding_model_name)


def warmup() -> None:
    """Force the embedding model to load now, not on the first query."""
    _get_model()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed; returns plain python lists (JSON/Pinecone-friendly)."""
    if not texts:
        return []
    model = _get_model()
    vectors: np.ndarray = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]