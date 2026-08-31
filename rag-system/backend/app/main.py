"""
main.py

App entrypoint. Only responsibilities here: create the FastAPI app,
attach CORS, and mount routers. Auth enforcement happens per-route via
the `get_current_user` dependency (see auth.py) rather than global
middleware, so it's explicit in each router's function signature which
endpoints require auth (all of them, in this app).
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import setup_logging
from app.config import get_settings
from app.routers import documents, sessions, chat

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


@app.on_event("startup")
async def on_startup():
    logger.info("RAG API starting up — CORS origins: %s", settings.cors_origins)


@app.get("/health")
async def health():
    return {"status": "ok"}