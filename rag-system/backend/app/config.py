"""
config.py

Centralized settings loaded from environment variables. Every external
service (Supabase, Pinecone, Gemini, Langfuse) needs credentials, and we
want a single, obvious place to see what's required rather than env
lookups scattered across modules. Pydantic's BaseSettings also gives us
fail-fast behavior: the app refuses to boot with a clear error if a
required key is missing, instead of failing mysteriously mid-request.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Supabase (auth + Postgres + RLS) ---
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str  # server-side only, bypasses RLS when needed
    supabase_storage_bucket: str = "documents"  # holds raw uploaded files, per-user folders

    # --- Vector store ---
    pinecone_api_key: str
    pinecone_index_name: str = "rag-multitenant"
    pinecone_environment: str = "us-east-1"

    # --- LLM (Gemini, via the google-genai SDK) ---
    # One model handles both chat generation and image description --
    # Gemini's models are natively multimodal, unlike the old Groq setup
    # which needed a separate vision-only model. Gemini model names move
    # fast; check https://ai.google.dev/gemini-api/docs/models for the
    # current recommended flash-tier model if this one starts erroring
    # or gets deprecated.
    gemini_api_key: str
    gemini_model: str = "gemini-3.6-flash"

    # --- Embeddings (local, no external API) ---
    embedding_model_name: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # --- Retrieval ---
    retrieval_candidate_pool: int = 25
    # How many RRF-fused candidates survive to be handed to the cross-encoder
    # reranker. This MUST be larger than retrieval_top_k -- the whole point of
    # reranking is to let the cross-encoder promote a chunk that RRF's cheap
    # rank-fusion under-ranked (e.g. it only won on the sparse/BM25 side and
    # got diluted by RRF_K smoothing). If we truncated to retrieval_top_k
    # before reranking, the reranker would only ever get to reorder an
    # already-too-narrow set and could never rescue a chunk RRF dropped.
    retrieval_rerank_pool: int = 15
    retrieval_top_k: int = 3
    # Minimum cross-encoder relevance score a chunk must clear to survive
    # into the final answer context. ms-marco-MiniLM-L-6-v2 outputs a
    # relevance logit, not a 0..1 probability -- scores well above 0
    # indicate a genuine match, scores near/below 0 indicate the pair is
    # essentially unrelated. This is what stops an unrelated document
    # (e.g. a large book that happens to share one keyword with the
    # query) from filling the top-k purely because RRF's rank-based
    # fusion has no way to express "not actually relevant," only
    # "ranked lower." Only applied when rerank_score is populated (i.e.
    # the cross-encoder actually loaded) -- see retrieval/rerank.py.
    retrieval_min_rerank_score: float = -2.0
    bm25_cache_ttl_seconds: int = 600  # 10 min; invalidated early on upload/delete

    # --- Confidence gating ---
    # AGENTIC: always answer; low confidence gets a "not grounded in your
    # documents" note but the LLM's general knowledge still responds.
    # GATED: below confidence_threshold, refuse to generate and ask the
    # user to rephrase / upload more relevant docs.
    # See llm/confidence.py and llm/client.py docstrings for the full
    # rationale behind defaulting to AGENTIC.
    generation_mode: str = "agentic"  # "agentic" | "gated"
    confidence_gate_threshold: float = 0.35

    # --- Observability ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://jp.cloud.langfuse.com"

    # --- Misc ---
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Cached so we parse the environment once per process, not per request."""
    return Settings()