"""
routers/documents.py

Upload endpoints per format, plus list/delete. Route handlers stay thin
on purpose: they create the `documents` row, delegate the actual
load->chunk->embed->upsert work to ingestion/pipeline.py, and translate
`IngestionError` into a "failed" status with a clear error_message
instead of a generic 500 -- this is the API-level half of the
"fail loudly, no silent zero-chunk ghosts" requirement.

Raw file storage: alongside the chunk/embed pipeline, the original
uploaded bytes are stored in the "documents" Supabase Storage bucket
under `{user_id}/{document_id}-{filename}`, using the caller's own
RLS-scoped client -- so the same "can't touch another user's data"
guarantee that covers the Postgres tables also covers the raw files
(see supabase/schema.sql for the bucket's RLS policies). The bucket is
private; the only way to read a file back out is the signed URL minted
by GET /documents/{id}/url, which is short-lived and still goes through
`get_current_user` + a user_id-owner check first.
"""

import mimetypes
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.ingestion.pipeline import ingest_file, IngestionError
from app.ingestion.vectorstore import delete_document as delete_vectors
from app.llm.client import describe_image_with_vision
from app.models import DocumentOut, DocumentUrlOut, YoutubeIngestRequest
from app.retrieval.bm25_cache import invalidate_user_cache

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()

_EXT_TO_TYPE = {"pdf": "pdf", "csv": "csv", "docx": "docx", "png": "image", "jpg": "image", "jpeg": "image"}

# Explicit map first (mimetypes' guess is unreliable/OS-dependent for a
# couple of these, e.g. .docx on some platforms), falling back to
# mimetypes.guess_type, then to a generic binary type as a last resort.
_EXT_TO_MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# How long a signed download/view URL stays valid.
_SIGNED_URL_TTL_SECONDS = 300


def _source_type_from_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _EXT_TO_TYPE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported file type: .{ext}")
    return _EXT_TO_TYPE[ext]


def _content_type_from_filename(filename: str) -> str:
    """
    The MIME type stored on the Storage object. This is what makes a
    signed URL open a PDF/image inline in the browser tab instead of
    forcing a download -- browsers decide "render vs. download" based
    on the Content-Type the server sends, not the file extension in the
    URL. Storing everything as application/octet-stream (the previous
    behavior) meant every file downloaded regardless of type.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _EXT_TO_MIME:
        return _EXT_TO_MIME[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _storage_path(user_id: str, document_id: str, filename: str) -> str:
    # user_id as the first path segment is what the bucket's RLS
    # policies check against auth.uid() -- keep this prefix in sync
    # with supabase/schema.sql if you ever change the layout.
    return f"{user_id}/{document_id}-{filename}"


async def _run_ingestion(
    user: CurrentUser,
    *,
    source_name: str,
    source_type: str,
    file_bytes: bytes | None = None,
    youtube_url: str | None = None,
):
    document_id = str(uuid.uuid4())
    storage_path = None

    # Upload the raw file to Storage first (if we have raw bytes at
    # all -- youtube ingestion has none). If this fails, we bail out
    # before creating the row rather than leaving an orphaned document
    # with no backing file.
    if file_bytes is not None:
        storage_path = _storage_path(user.id, document_id, source_name)
        try:
            user.db.storage.from_(settings.supabase_storage_bucket).upload(
                storage_path,
                file_bytes,
                {"content-type": _content_type_from_filename(source_name), "upsert": "true"},
            )
        except Exception as exc:  # noqa: BLE001 - surface as a clean error, not a 500
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Failed to store uploaded file: {exc}"
            ) from exc

    # Insert as "processing" first so the frontend can show it immediately.
    user.db.table("documents").insert(
        {
            "id": document_id,
            "user_id": user.id,
            "source_name": source_name,
            "source_type": source_type,
            "chunk_count": 0,
            "status": "processing",
            "storage_path": storage_path,
        }
    ).execute()

    try:
        result = ingest_file(
            db=user.db,
            user_id=user.id,
            document_id=document_id,
            source_name=source_name,
            source_type=source_type,
            file_bytes=file_bytes,
            youtube_url=youtube_url,
            describe_image_fn=describe_image_with_vision,
        )
    except IngestionError as exc:
        user.db.table("documents").update(
            {"status": "failed", "error_message": str(exc)}
        ).eq("id", document_id).execute()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    user.db.table("documents").update(
        {"status": "ready", "chunk_count": result.chunk_count}
    ).eq("id", document_id).execute()

    return document_id, result.chunk_count


@router.get("", response_model=list[DocumentOut])
async def list_documents(user: CurrentUser = Depends(get_current_user)):
    resp = user.db.table("documents").select("*").order("uploaded_at", desc=True).execute()
    return resp.data


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    source_type = _source_type_from_filename(file.filename)
    file_bytes = await file.read()
    document_id, chunk_count = await _run_ingestion(
        user, source_name=file.filename, source_type=source_type, file_bytes=file_bytes
    )
    row = user.db.table("documents").select("*").eq("id", document_id).single().execute()
    return row.data


@router.post("/youtube", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_youtube(body: YoutubeIngestRequest, user: CurrentUser = Depends(get_current_user)):
    document_id, chunk_count = await _run_ingestion(
        user, source_name=body.url, source_type="youtube", youtube_url=body.url
    )
    row = user.db.table("documents").select("*").eq("id", document_id).single().execute()
    return row.data


@router.get("/{document_id}/url", response_model=DocumentUrlOut)
async def get_document_url(document_id: str, user: CurrentUser = Depends(get_current_user)):
    """
    Mint a short-lived signed URL to view/download the original file.
    Looks up storage_path scoped to this user first (so a document_id
    that isn't theirs -- or has no stored file, e.g. a youtube source --
    404s instead of leaking a path), then asks Storage to sign it.
    """
    row = (
        user.db.table("documents")
        .select("storage_path")
        .eq("id", document_id)
        .eq("user_id", user.id)
        .single()
        .execute()
    )
    storage_path = row.data.get("storage_path") if row.data else None
    if not storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No stored file for this document")

    try:
        signed = user.db.storage.from_(settings.supabase_storage_bucket).create_signed_url(
            storage_path, _SIGNED_URL_TTL_SECONDS
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to sign URL: {exc}") from exc

    url = signed.get("signedURL") or signed.get("signed_url")
    if not url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Storage did not return a signed URL")

    return DocumentUrlOut(url=url, expires_in=_SIGNED_URL_TTL_SECONDS)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, user: CurrentUser = Depends(get_current_user)):
    row = (
        user.db.table("documents")
        .select("storage_path")
        .eq("id", document_id)
        .eq("user_id", user.id)
        .single()
        .execute()
    )
    storage_path = row.data.get("storage_path") if row.data else None

    user.db.table("documents").delete().eq("id", document_id).eq("user_id", user.id).execute()
    delete_vectors(user_id=user.id, document_id=document_id)
    user.db.table("document_chunks").delete().eq("document_id", document_id).eq("user_id", user.id).execute()

    if storage_path:
        try:
            user.db.storage.from_(settings.supabase_storage_bucket).remove([storage_path])
        except Exception:  # noqa: BLE001
            # Row/vectors are already gone -- don't fail the delete over
            # an orphaned storage object; it's harmless and can be swept
            # up later if needed.
            pass

    invalidate_user_cache(user.id)  # this user's corpus just changed -- don't serve stale BM25
    return None