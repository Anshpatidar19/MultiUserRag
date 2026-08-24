"""
embeddings.py

Wraps a local sentence-transformers model (default: all-MiniLM-L6-v2) so
embedding is free and doesn't depend on an external API's uptime/rate
limits -- a deliberate cost + reliability choice over e.g. OpenAI
embeddings, per spec. The model is loaded once per process (module-level
singleton) since loading it is the expensive part, not inference.
"""

from functools import lru_cache
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import get_settings


@lru_cache
def _get_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(settings.embedding_model_name)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed; returns plain python lists (JSON/Pinecone-friendly)."""
    if not texts:
        return []
    model = _get_model()
    vectors: np.ndarray = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]
