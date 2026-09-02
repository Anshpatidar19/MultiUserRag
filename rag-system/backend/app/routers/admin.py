"""
routers/admin.py

Admin-only endpoints: cross-user visibility and moderation actions that
a normal per-user RLS-scoped client (see auth.py) can never provide,
since RLS deliberately blocks exactly this. Every route here depends on
`get_current_admin` (see admin.py) instead of `get_current_user`, and
uses the SERVICE-ROLE client (bypasses RLS) rather than `user.db` --
this is the one place in the app allowed to, and it's gated behind the
admin_users table check.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status

from app.admin import get_current_admin
from app.auth import CurrentUser
from app.config import get_settings
from app.db import get_service_client
from app.ingestion.vectorstore import delete_document as delete_vectors, _get_index
from app.retrieval.bm25_cache import invalidate_user_cache

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.get("/me")
async def admin_me(admin: CurrentUser = Depends(get_current_admin)):
    """Cheap check the frontend uses to decide whether to show the Admin nav link/page at all."""
    return {"is_admin": True, "user_id": admin.id, "email": admin.email}


def _list_all_auth_users() -> list:
    """
    Paginates through Supabase Auth's admin user list (service-role
    only -- NOT available via the RLS-scoped per-user client). Page
    size capped at 200; fine for small/medium tenant counts. A large
    deployment should move this to server-side search/pagination
    instead of pulling the full list per request.
    """
    db = get_service_client()
    users, page = [], 1
    while True:
        resp = db.auth.admin.list_users(page=page, per_page=200)
        batch = resp if isinstance(resp, list) else getattr(resp, "users", [])
        if not batch:
            break
        users.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return users


@router.get("/stats")
async def get_stats(admin: CurrentUser = Depends(get_current_admin)):
    db = get_service_client()
    t0 = time.perf_counter()

    users = _list_all_auth_users()
    documents = (db.table("documents").select("id, status, source_type, chunk_count, user_id").execute().data or [])

    by_status = {"processing": 0, "ready": 0, "failed": 0}
    by_type: dict[str, int] = {}
    total_chunks = 0
    for d in documents:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
        by_type[d["source_type"]] = by_type.get(d["source_type"], 0) + 1
        total_chunks += d.get("chunk_count") or 0

    sessions_count = db.table("chat_sessions").select("id", count="exact").execute().count or 0
    messages_count = db.table("chat_messages").select("id", count="exact").execute().count or 0

    logger.info(
        "ADMIN STATS computed in %.2fs | users=%d documents=%d",
        time.perf_counter() - t0, len(users), len(documents),
    )

    return {
        "total_users": len(users),
        "total_documents": len(documents),
        "total_chunks": total_chunks,
        "documents_by_status": by_status,
        "documents_by_type": by_type,
        "total_sessions": sessions_count,
        "total_messages": messages_count,
    }


@router.get("/users")
async def list_users(admin: CurrentUser = Depends(get_current_admin)):
    db = get_service_client()
    users = _list_all_auth_users()

    doc_counts: dict[str, dict] = {}
    for d in (db.table("documents").select("user_id, status").execute().data or []):
        entry = doc_counts.setdefault(d["user_id"], {"total": 0, "ready": 0, "failed": 0, "processing": 0})
        entry["total"] += 1
        entry[d["status"]] += 1

    return [
        {
            "id": u.id,
            "email": u.email,
            "created_at": u.created_at,
            "last_sign_in_at": getattr(u, "last_sign_in_at", None),
            "documents": doc_counts.get(u.id, {"total": 0, "ready": 0, "failed": 0, "processing": 0}),
        }
        for u in users
    ]


@router.get("/documents")
async def list_all_documents(admin: CurrentUser = Depends(get_current_admin)):
    db = get_service_client()
    documents = db.table("documents").select("*").order("uploaded_at", desc=True).limit(500).execute().data or []
    email_by_id = {u.id: u.email for u in _list_all_auth_users()}
    for d in documents:
        d["owner_email"] = email_by_id.get(d["user_id"], "(unknown)")
    return documents


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_document(document_id: str, admin: CurrentUser = Depends(get_current_admin)):
    db = get_service_client()
    row = db.table("documents").select("user_id, storage_path").eq("id", document_id).single().execute()
    if not row.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    owner_id = row.data["user_id"]
    storage_path = row.data.get("storage_path")

    db.table("documents").delete().eq("id", document_id).execute()
    db.table("document_chunks").delete().eq("document_id", document_id).execute()
    delete_vectors(user_id=owner_id, document_id=document_id)

    if storage_path:
        try:
            db.storage.from_(settings.supabase_storage_bucket).remove([storage_path])
        except Exception:  # noqa: BLE001
            logger.warning("Admin delete: failed to remove storage object %r for doc %s", storage_path, document_id)

    invalidate_user_cache(owner_id)  # that user's corpus just changed -- don't serve them a stale BM25 index
    logger.info("ADMIN DELETE | admin=%s deleted doc=%s (owner=%s)", admin.id, document_id, owner_id)
    return None


@router.get("/health")
async def admin_health(admin: CurrentUser = Depends(get_current_admin)):
    """
    Quick reachability check for each external dependency, surfaced in
    the admin panel so an outage (e.g. the Pinecone ConnectTimeoutError
    seen earlier) is visible at a glance instead of only showing up
    later as a pile of failed document uploads.
    """
    result: dict = {}

    t0 = time.perf_counter()
    try:
        _get_index()
        result["pinecone"] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        result["pinecone"] = {"ok": False, "error": str(exc)}

    t0 = time.perf_counter()
    try:
        get_service_client().table("documents").select("id").limit(1).execute()
        result["supabase"] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        result["supabase"] = {"ok": False, "error": str(exc)}

    result["gemini"] = {
        "ok": bool(settings.gemini_api_key),
        "note": "key configured" if settings.gemini_api_key else "no key set",
    }

    return result