import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.config import get_settings
from app.ingestion import embeddings, vectorstore
from app.retrieval.bm25_cache import get_or_build
from app.retrieval.tokenizer import tokenize as _tokenize

logger = logging.getLogger(__name__)
settings = get_settings()

RRF_K = 60

# Both branches of hybrid search are network I/O (a Pinecone query, and
# either a Supabase fetch to rebuild the BM25 cache or a cache hit that
# returns instantly) and don't depend on each other's results, so
# running them back-to-back was pure added latency for no reason. A
# small dedicated pool runs them concurrently -- retrieval wall time
# becomes roughly max(dense, bm25) instead of dense + bm25.
_retrieval_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hybrid-retrieval")


@dataclass
class RetrievedChunk:
    document_id: str
    source_name: str
    text: str
    rrf_score: float
    dense_score: float | None
    bm25_score: float | None
    rerank_score: float | None = None


def _fetch_user_corpus(db, user_id: str) -> list[dict]:
    resp = (
        db.table("document_chunks")
        .select("chunk_id, document_id, source_name, text")
        .eq("user_id", user_id)
        .execute()
    )
    return [
        {"id": r["chunk_id"], "document_id": r["document_id"], "source_name": r["source_name"], "text": r["text"]}
        for r in resp.data
    ]


def hybrid_search(db, user_id: str, query_text: str) -> list[RetrievedChunk]:
    pool = settings.retrieval_candidate_pool
    rerank_pool = settings.retrieval_rerank_pool

    # embed_query() is a local, in-process model call (fast, no network),
    # so it stays on the calling thread; the two genuinely slow, mutually
    # independent I/O calls below run concurrently instead of sequentially.
    query_emb = embeddings.embed_query(query_text)

    dense_future = _retrieval_executor.submit(
        vectorstore.query, user_id=user_id, query_embedding=query_emb, top_k=pool
    )
    bm25_future = _retrieval_executor.submit(get_or_build, user_id, lambda: _fetch_user_corpus(db, user_id))

    dense_hits = dense_future.result()
    cache_entry = bm25_future.result()

    dense_rank = {hit["id"]: rank for rank, hit in enumerate(dense_hits)}
    dense_score_by_id = {hit["id"]: hit["score"] for hit in dense_hits}
    chunk_meta_by_id = {
        hit["id"]: {"document_id": hit["document_id"], "source_name": hit["source_name"], "text": hit["text"]}
        for hit in dense_hits
    }

    bm25_rank: dict[str, int] = {}
    bm25_score_by_id: dict[str, float] = {}
    if cache_entry.bm25 is not None and cache_entry.chunk_ids:
        scores = cache_entry.bm25.get_scores(_tokenize(query_text))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:pool]
        for rank, idx in enumerate(ranked):
            cid = cache_entry.chunk_ids[idx]
            bm25_rank[cid] = rank
            bm25_score_by_id[cid] = float(scores[idx])
            chunk_meta_by_id.setdefault(
                cid,
                {
                    "document_id": cache_entry.document_ids[idx],
                    "source_name": cache_entry.source_names[idx],
                    "text": cache_entry.chunk_texts[idx],
                },
            )

    all_ids = set(dense_rank) | set(bm25_rank)
    fused: list[RetrievedChunk] = []
    for cid in all_ids:
        score = 0.0
        if cid in dense_rank:
            score += 1.0 / (RRF_K + dense_rank[cid] + 1)
        if cid in bm25_rank:
            score += 1.0 / (RRF_K + bm25_rank[cid] + 1)
        meta = chunk_meta_by_id[cid]
        fused.append(
            RetrievedChunk(
                document_id=meta["document_id"],
                source_name=meta["source_name"],
                text=meta["text"],
                rrf_score=score,
                dense_score=dense_score_by_id.get(cid),
                bm25_score=bm25_score_by_id.get(cid),
            )
        )

    fused.sort(key=lambda c: c.rrf_score, reverse=True)
    result = fused[:rerank_pool]

    logger.info(
        "HYBRID SEARCH | query=%r | user_corpus_chunks=%d | dense_hits=%d | bm25_hits=%d | "
        "fused_unique=%d | returned=%d (rerank_pool cap=%d)",
        query_text,
        len(cache_entry.chunk_ids) if cache_entry.chunk_ids else 0,
        len(dense_hits),
        len(bm25_rank),
        len(fused),
        len(result),
        rerank_pool,
    )
    for i, c in enumerate(result[:5]):
        logger.debug(
            "  fused #%d | rrf=%.4f dense=%s bm25=%s | source=%r | %.60r",
            i + 1, c.rrf_score,
            f"{c.dense_score:.4f}" if c.dense_score is not None else "—",
            f"{c.bm25_score:.4f}" if c.bm25_score is not None else "—",
            c.source_name, c.text,
        )

    return result