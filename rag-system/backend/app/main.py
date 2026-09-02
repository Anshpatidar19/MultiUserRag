"""
main.py

App entrypoint. Only responsibilities here: create the FastAPI app,
attach CORS, and mount routers. Auth enforcement happens per-route via
the `get_current_user` dependency (see auth.py) rather than global
middleware, so it's explicit in each route's function signature which
endpoints require auth (all of them). Admin routes additionally depend
on `get_current_admin` (see admin.py), a stricter check layered on top.
"""

import asyncio
import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import setup_logging
from app.config import get_settings
from app.ingestion import embeddings
from app.retrieval import rerank
from app.routers import documents, sessions, chat, admin

setup_logging()  # must run before any other app module's logger is used
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="Multi-Tenant Agentic RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.on_event("startup")
async def on_startup():
    logger.info("RAG API starting up — CORS origins: %s", settings.cors_origins)

    t0 = time.perf_counter()
    await asyncio.gather(
        asyncio.to_thread(embeddings.warmup),
        asyncio.to_thread(rerank.warmup),
    )
    logger.info("Model warmup complete in %.2fs — ready to serve.", time.perf_counter() - t0)


@app.get("/health")
async def health():
    return {"status": "ok"}