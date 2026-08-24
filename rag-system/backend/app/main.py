"""
main.py

App entrypoint. Only responsibilities here: create the FastAPI app,
attach CORS, and mount routers. Auth enforcement happens per-route via
the `get_current_user` dependency (see auth.py) rather than global
middleware, so it's explicit in each router's function signature which
endpoints require auth (all of them, in this app).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import documents, sessions, chat

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


@app.get("/health")
async def health():
    return {"status": "ok"}
