"""
routers/sessions.py

CRUD for chat sessions. Every query below relies on RLS (see
supabase/schema.sql) to scope rows to the caller -- we still add
`.eq("user_id", user.id)` explicitly on writes as defense-in-depth, but
reads deliberately trust RLS alone so that "even a direct DB query can
only return the requesting user's rows" is actually exercised here, not
just true in theory.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import CurrentUser, get_current_user
from app.models import ChatSessionOut, ChatSessionCreate, ChatSessionRename

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[ChatSessionOut])
async def list_sessions(user: CurrentUser = Depends(get_current_user)):
    resp = user.db.table("chat_sessions").select("*").order("last_active_at", desc=True).execute()
    return resp.data


@router.post("", response_model=ChatSessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(body: ChatSessionCreate, user: CurrentUser = Depends(get_current_user)):
    resp = (
        user.db.table("chat_sessions")
        .insert({"user_id": user.id, "title": body.title})
        .execute()
    )
    return resp.data[0]


@router.patch("/{session_id}", response_model=ChatSessionOut)
async def rename_session(session_id: str, body: ChatSessionRename, user: CurrentUser = Depends(get_current_user)):
    resp = (
        user.db.table("chat_sessions")
        .update({"title": body.title})
        .eq("id", session_id)
        .eq("user_id", user.id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return resp.data[0]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user: CurrentUser = Depends(get_current_user)):
    user.db.table("chat_sessions").delete().eq("id", session_id).eq("user_id", user.id).execute()
    return None


@router.get("/{session_id}/messages")
async def get_messages(session_id: str, user: CurrentUser = Depends(get_current_user)):
    resp = (
        user.db.table("chat_messages")
        .select("*")
        .eq("session_id", session_id)
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
    )
    return resp.data
