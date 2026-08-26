"""
hybrid.py

Combines dense (vector) and sparse (BM25 keyword) retrieval via
Reciprocal Rank Fusion (RRF) rather than a weighted score blend, because
RRF only needs each method's *rank* ordering, not comparable score
scales -- cosine similarity and BM25 scores aren't on the same scale, so
fusing raw scores would silently let one method dominate.

Everything here is user-scoped: the dense side hits Pinecone with
namespace=user_id (see vectorstore.py), and the sparse side builds its
BM25 index only from this user's chunk rows (see bm25_cache.py + the
`document_chunks` Supabase table, which is a lightweight metadata mirror
of what's in the vector store, kept in Postgres because Pinecone doesn't
offer a simple "list all vectors" call).
"""

from dataclasses import dataclass

from app.config import get_settings
from app.ingestion import embeddings, vectorstore
from app.retrieval.bm25_cache import get_or_build, _tokenize

settings = get_settings()

RRF_K = 60  # standard RRF smoothing constant


@dataclass
class RetrievedChunk:
    document_id: str
    source_name: str
    text: str
    rrf_score: float
    dense_score: float | None
    bm25_score: float | None
    # Set by retrieval/rerank.py after the cross-encoder pass. None until
    # then (or permanently, if the reranker model failed to load -- see
    # rerank.py). Deliberately distinct from rrf_score: RRF only encodes
    # *rank order* within this query's pool, not a real relevance
    # magnitude, so a low rrf_score does NOT reliably mean "not relevant"
    # -- it can just mean "a much bigger document in the corpus produced
    # more candidates." The cross-encoder score is an actual (query, chunk)
    # relevance judgment and is what chat.py filters noise on.
    rerank_score: float | None = None


def _fetch_user_corpus(db, user_id: str) -> list[dict]:
    """Reads the lightweight chunk-text mirror table, RLS-scoped to this user."""
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
    # NOTE: intentionally NOT retrieval_top_k here. We return the wider
    # rerank pool so the cross-encoder in retrieval/rerank.py has real
    # candidates to reorder. Truncating to top_k at this point would mean
    # a chunk that only won on BM25 (and got diluted by RRF fusion against
    # many mediocre dense matches) gets discarded before the reranker -- the
    # one component that could correctly promote it -- ever sees it. The
    # final top_k cut happens in routers/chat.py, AFTER rerank().
    rerank_pool = settings.retrieval_rerank_pool

    # --- Dense: Pinecone, hard-scoped to this user's namespace ---
    query_emb = embeddings.embed_query(query_text)
    dense_hits = vectorstore.query(user_id=user_id, query_embedding=query_emb, top_k=pool)
    dense_rank = {hit["id"]: rank for rank, hit in enumerate(dense_hits)}
    dense_score_by_id = {hit["id"]: hit["score"] for hit in dense_hits}
    chunk_meta_by_id = {
        hit["id"]: {"document_id": hit["document_id"], "source_name": hit["source_name"], "text": hit["text"]}
        for hit in dense_hits
    }

    # --- Sparse: per-user cached BM25 ---
    cache_entry = get_or_build(user_id, lambda: _fetch_user_corpus(db, user_id))
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

    # --- Fuse via RRF ---
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
    return fused[:rerank_pool]