"""
rerank.py

Optional cross-encoder rerank pass over the RRF-fused candidates. RRF
gives a good cheap ordering from two independent signals, but a
cross-encoder that jointly scores (query, chunk) pairs is more accurate
at final ranking -- it's just too slow to run over the full candidate
pool (~25), so we only run it on the already-narrowed rerank_pool (see
hybrid.py). If the cross-encoder model isn't available (e.g. not
downloaded / no network access to huggingface.co in this environment),
we fail soft and keep RRF order rather than erroring the whole request
-- reranking is a quality improvement, not a correctness requirement.

IMPORTANT: "fail soft" here is silent by design at the request level,
but it is NOT harmless -- RRF's rank-based fusion has no real relevance
magnitude, only within-query rank order. A tiny 1-chunk document can
easily be outranked by a large document's incidental keyword overlap
(e.g. an 828-chunk book matching a query on a single shared common
word), and the cross-encoder is the ONLY component in this pipeline
that can actually tell "genuinely relevant" apart from "coincidentally
ranked." If you see low-relevance/noise citations dominating answers,
check that this model is actually loading (log a warning on the except
branch below, or check startup logs) rather than assuming reranking is
running.
"""

import logging
from functools import lru_cache

from app.retrieval.hybrid import RetrievedChunk

logger = logging.getLogger(__name__)


@lru_cache
def _get_reranker():
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        logger.warning(
            "Cross-encoder reranker failed to load -- falling back to RRF-only "
            "ordering. Retrieval quality on noisy/imbalanced corpora will be "
            "degraded (no relevance-score filtering will be applied).",
            exc_info=True,
        )
        return None


def rerank(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    model = _get_reranker()
    if model is None or not chunks:
        logger.info("RERANK skipped (model unavailable or 0 candidate chunks) | candidates=%d", len(chunks))
        return chunks

    pairs = [(query, c.text) for c in chunks]
    scores = model.predict(pairs)
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    result = [
        RetrievedChunk(
            document_id=chunks[i].document_id,
            source_name=chunks[i].source_name,
            text=chunks[i].text,
            rrf_score=chunks[i].rrf_score,
            dense_score=chunks[i].dense_score,
            bm25_score=chunks[i].bm25_score,
            rerank_score=float(scores[i]),
        )
        for i in order
    ]
    logger.info(
        "RERANK | candidates=%d | top_score=%.4f | bottom_score=%.4f",
        len(result), float(scores[order[0]]), float(scores[order[-1]]),
    )
    return result