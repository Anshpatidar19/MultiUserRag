"""
models.py

Pydantic schemas for API I/O. Kept separate from any ORM/DB row shape on
purpose: the DB schema (see supabase/schema.sql) is the source of truth
for storage, while these models are the contract with the frontend and
can diverge slightly (e.g. hiding internal fields, renaming for the UI).
"""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class ChatSessionOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    last_active_at: datetime


class ChatSessionCreate(BaseModel):
    title: str = "New chat"


class ChatSessionRename(BaseModel):
    title: str


class Citation(BaseModel):
    source_name: str
    relevance_score: float
    preview: str
    document_id: str


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = []
    confidence_score: float | None = None
    confidence_label: str | None = None
    grounded: bool | None = None  # False => answered from general knowledge
    created_at: datetime


class ChatRequest(BaseModel):
    session_id: str
    message: str
    language: str | None = None  # e.g. "en", "hi"; None => auto-detect


class DocumentOut(BaseModel):
    id: str
    source_name: str
    source_type: Literal["pdf", "image", "csv", "youtube", "docx"]
    uploaded_at: datetime
    chunk_count: int
    status: Literal["processing", "ready", "failed"]
    error_message: str | None = None
    storage_path: str | None = None  # null for source types with no raw file (youtube)


class DocumentUrlOut(BaseModel):
    url: str
    expires_in: int


class YoutubeIngestRequest(BaseModel):
    url: str