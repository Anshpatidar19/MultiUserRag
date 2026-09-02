"""
bm25_cache.py

An in-memory BM25 corpus, keyed and partitioned by user_id, with a TTL
so it can't drift stale forever even if we somehow miss an invalidation.
Two safety properties matter here:

1. Partitioning: the cache dict is keyed by user_id, so
   `_CACHE[user_a_id]` and `_CACHE[user_b_id]` are just different dict
   entries -- there's no path where building one user's BM25 index could
   read another user's chunks, mirroring the Pinecone namespace
   isolation in vectorstore.py.
2. Immediate invalidation: `invalidate_user_cache` is called by the
   ingestion pipeline on every successful upload and by the delete route
   on every delete, so a user never sees stale keyword results after
   changing their own document set -- we don't rely on the TTL alone for
   that case, only as a backstop.

This is process-local memory, which is fine for a single backend
instance; a multi-instance deployment would swap this for Redis with the
same per-user-key contract.
"""

import time
from dataclasses import dataclass
from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.retrieval.tokenizer import tokenize as _tokenize

settings = get_settings()


@dataclass
class _CacheEntry:
    bm25: BM25Okapi
    chunk_ids: list[str]
    chunk_texts: list[str]
    document_ids: list[str]
    source_names: list[str]
    built_at: float


_CACHE: dict[str, _CacheEntry] = {}

# _tokenize is imported (not redefined) from retrieval/tokenizer.py, the
# single shared tokenizer used by BM25 indexing/querying here AND by the
# lexical-grounding overlap check in llm/confidence.py. It does regex
# word-extraction (not .split(), which left punctuation glued onto tokens
# like "SUBJECTS/PAPERS") followed by Porter stemming, so morphological
# variants of the same word -- "accounts" / "accounting" / "account",
# "exam" / "exams" -- collapse onto one token instead of being treated as
# unrelated strings. See tokenizer.py for the full rationale.


def get_or_build(user_id: str, corpus_fetcher) -> _CacheEntry:
    """
    corpus_fetcher: callable() -> list[dict] with keys
    {id, document_id, source_name, text}, fetched from Pinecone metadata
    for this user's namespace. Only called on a cache miss/expiry.
    """
    entry = _CACHE.get(user_id)
    if entry is not None and (time.time() - entry.built_at) < settings.bm25_cache_ttl_seconds:
        return entry

    rows = corpus_fetcher()
    tokenized = [_tokenize(r["text"]) for r in rows]
    bm25 = BM25Okapi(tokenized) if tokenized else None

    entry = _CacheEntry(
        bm25=bm25,
        chunk_ids=[r["id"] for r in rows],
        chunk_texts=[r["text"] for r in rows],
        document_ids=[r["document_id"] for r in rows],
        source_names=[r["source_name"] for r in rows],
        built_at=time.time(),
    )
    _CACHE[user_id] = entry
    return entry


def invalidate_user_cache(user_id: str) -> None:
    _CACHE.pop(user_id, None)