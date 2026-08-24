# Multi-Tenant Agentic RAG System

A full-stack, multi-tenant RAG chat app. FastAPI + Supabase (auth/DB/RLS)
+ Pinecone (per-user namespaces) + local embeddings + Groq generation +
hybrid retrieval (dense + BM25, RRF-fused) + custom confidence scoring +
Langfuse observability + a React frontend styled after the VigilEye AI
reference UI (indigo accent, card-based layout).

## Why some things need you to fill in credentials

This was built as a code scaffold in a sandboxed environment with no
access to Supabase/Pinecone/Groq/Langfuse or the public internet beyond
a package-registry allowlist, so nothing here is deployed or live-tested
against real services. Every module is fully implemented and documented
(see the docstring at the top of each file for the reasoning behind its
design), but you'll need to supply real API keys and run it yourself.

## Architecture

```
backend/
  app/
    main.py              # FastAPI app + router mounting
    config.py             # env-driven settings (Settings/get_settings)
    auth.py                # Supabase JWT -> CurrentUser + RLS-scoped db client
    db.py                    # user-scoped vs service-role Supabase clients
    models.py                 # pydantic I/O schemas
    ingestion/
      loaders.py                # pdf / image(OCR) / csv / docx / youtube
      chunking.py                 # recursive paragraph->sentence->word splitter
      embeddings.py                 # local sentence-transformers (all-MiniLM-L6-v2)
      vectorstore.py                  # Pinecone, hard-scoped to namespace=user_id
      pipeline.py                       # load -> chunk -> embed -> upsert, fail loudly
    retrieval/
      bm25_cache.py           # per-user TTL cache, invalidated on upload/delete
      hybrid.py                  # dense + BM25 fused via Reciprocal Rank Fusion
      rerank.py                     # optional cross-encoder rerank pass
    llm/
      client.py                 # Groq streaming generation; agentic vs gated mode
      confidence.py                # custom (non-LLM-reported) confidence score
    observability/
      tracing.py                 # Langfuse spans/trace/score per query
    routers/
      documents.py, sessions.py, chat.py
  supabase/schema.sql       # tables + RLS policies (the hard isolation boundary)
  requirements.txt
  .env.example

frontend/                (React + Vite)
  src/
    pages/            Login, Signup, Chat, Documents, Settings
    components/       Sidebar, ConfidenceBadge, Icons, ProtectedRoute
    hooks/useVoice.js     Web Speech API (STT input / TTS playback)
    api/              supabase client + fetch wrapper + SSE chat streaming
    utils/exportPdf.js   text-based PDF export of a conversation
    styles/theme.css      indigo/purple, card-based theme matching the reference app
```

## Design decisions worth knowing about (also documented inline)

- **Multi-tenancy is enforced twice, independently**: Postgres Row Level
  Security (`supabase/schema.sql`) at the DB layer, and Pinecone
  namespaces (`vectorstore.py`) + a per-user-keyed BM25 cache
  (`bm25_cache.py`) at the retrieval layer. Neither depends on the other
  being correct.
- **Agentic vs. gated generation** (`llm/client.py`): defaults to
  *agentic* — always answer, but clearly flag general-knowledge answers
  as "not based on your documents" when KB confidence is low. A hard
  gate is available via `GENERATION_MODE=gated` in `.env`. The tradeoff
  is explained in that file's docstring.
- **Confidence score is custom, not the LLM's self-report** — blended
  from retrieval similarity, cross-document source agreement, and
  answer/context lexical grounding (`llm/confidence.py`), and pushed to
  Langfuse as a queryable score, not just displayed in the UI.
- **Fail loudly on ingestion** (`ingestion/pipeline.py`): zero chunks or
  zero vectors is a hard error surfaced to the frontend as `status:
  "failed"` with a message — never a silent "ghost" document.
- **Web page scraping is intentionally absent** — only PDF/image/CSV/
  DOCX/YouTube-transcript ingestion exist, per spec.

## Getting it running

### 1. Supabase
- Create a project, then run `backend/supabase/schema.sql` in the SQL editor.
- Enable email/password auth (Authentication -> Providers).
- Copy your project URL, anon key, and service role key.

### 2. Pinecone
- Create an account/API key. The index is auto-created on first use
  (see `vectorstore.py`) with the configured dimension (384, matching
  all-MiniLM-L6-v2).

### 3. Groq
- Create an API key at console.groq.com.

### 4. Langfuse (optional)
- Create a project for tracing; tracing no-ops safely if you leave the
  keys blank.

### 5. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values
# System deps for OCR: `apt install tesseract-ocr poppler-utils` (Linux)
uvicorn app.main:app --reload --port 8000
```

### 6. Frontend
```bash
cd frontend
npm install
cp .env.example .env   # fill in Supabase URL + anon key
npm run dev
```

Visit http://localhost:5173 — sign up, upload a document, and chat.
