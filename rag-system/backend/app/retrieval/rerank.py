"""
rerank.py

Optional cross-encoder rerank pass over the RRF-fused candidates. RRF
gives a good cheap ordering from two independent signals, but a
cross-encoder that jointly scores (query, chunk) pairs is more accurate
at final ranking -- it's just too slow to run over the full candidate
pool (~25), so we only run it on the already-narrowed set. If the
cross-encoder model isn't available (e.g. not downloaded in this
environment), we fail soft and keep RRF order rather than erroring the
whole request -- reranking is a quality improvement, not a correctness
requirement.
"""

from functools import lru_cache

from app.retrieval.hybrid import RetrievedChunk


@lru_cache
def _get_reranker():
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        return None


def rerank(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    model = _get_reranker()
    if model is None or not chunks:
        return chunks

    pairs = [(query, c.text) for c in chunks]
    scores = model.predict(pairs)
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    return [chunks[i] for i in order]
