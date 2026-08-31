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

Async ingestion: chunk/embed/upsert (loaders.py + embeddings.py) makes
several outbound network calls (OCR, embeddings, vision fallback) and
can easily take from several seconds up to a minute or more for a large
PDF. That work used to run inline before the request returned, which
meant (a) the browser's upload spinner sat there for the full duration
with nothing in the Knowledge Base / Upload lists to show for it, and
(b) it blocked FastAPI's event loop for every other user's request in
the meantime, since `ingest_file` is a plain synchronous function.
Both endpoints below now do only the fast part inline -- store the raw
file, insert the "processing" row -- and return immediately so the
document shows up in the UI right away. The actual pipeline run is
handed to `BackgroundTasks`, which (for a sync callable) Starlette runs
in a worker thread rather than on the event loop, so it no longer stalls
other requests either. The frontend polls GET /documents while anything
is "processing" (see DocumentsContext.jsx) to pick up "ready"/"failed"
once the background task finishes.
"""

import functools
import logging
import mimetypes
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.ingestion.pipeline import ingest_file, IngestionError
from app.ingestion.vectorstore import delete_document as delete_vectors
from app.llm.client import describe_image_with_vision
from app.models import DocumentOut, DocumentUrlOut, YoutubeIngestRequest
from app.retrieval.bm25_cache import invalidate_user_cache

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
logger = logging.getLogger(__name__)

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


def _create_processing_row(
    user: CurrentUser,
    *,
    source_name: str,
    source_type: str,
    file_bytes: bytes | None = None,
) -> tuple[str, str | None]:
    """
    The fast, synchronous half of ingestion: store the raw file (if any)
    and insert the `documents` row with status "processing". Runs inline
    on the request so the row -- and therefore the document -- exists
    the instant the endpoint returns, before any chunking/embedding has
    happened.
    """
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
            logger.error("Failed to store raw file for %r: %s", source_name, exc)
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

    logger.info(
        "Document row created | user=%s doc=%s source=%r type=%s status=processing",
        user.id, document_id, source_name, source_type,
    )

    return document_id, storage_path


def _process_ingestion(
    user: CurrentUser,
    *,
    document_id: str,
    source_name: str,
    source_type: str,
    file_bytes: bytes | None = None,
    youtube_url: str | None = None,
    image_mime_type: str | None = None,
):
    """
    The slow half: load -> chunk -> embed -> upsert, then flip the row to
    "ready"/"failed". Runs as a BackgroundTask (i.e. in a worker thread,
    after the response for the upload request has already been sent) so
    it neither blocks the client nor the event loop for other users.

    `image_mime_type` is bound onto the vision fallback here (instead of
    inside pipeline.py, which has no knowledge of the original filename)
    so Gemini always receives the image's real content type rather than
    the previous hardcoded "image/jpeg" default -- that mismatch could
    degrade or break vision descriptions for anything uploaded as PNG.

    PDFs get their own vision callback too now (mime type "image/png",
    since scanned PDF pages are always rendered to PNG in loaders.py
    before being handed to the vision model) -- this is what fixes
    marksheets/tables scanned into a PDF, not just ones uploaded as a
    standalone photo. See ingestion/pipeline.py's module docstring for
    the full rationale.
    """
    describe_fn = None
    if source_type == "image":
        describe_fn = functools.partial(describe_image_with_vision, mime_type=image_mime_type)
    elif source_type == "pdf":
        describe_fn = functools.partial(describe_image_with_vision, mime_type="image/png")

    try:
        result = ingest_file(
            db=user.db,
            user_id=user.id,
            document_id=document_id,
            source_name=source_name,
            source_type=source_type,
            file_bytes=file_bytes,
            youtube_url=youtube_url,
            describe_image_fn=describe_fn,
        )
    except IngestionError as exc:
        logger.error("Document %s (%r) FAILED: %s", document_id, source_name, exc)
        user.db.table("documents").update(
            {"status": "failed", "error_message": str(exc)}
        ).eq("id", document_id).execute()
        return
    except Exception as exc:  # noqa: BLE001 - never leave a row stuck "processing" forever
        logger.exception("Document %s (%r) FAILED unexpectedly", document_id, source_name)
        user.db.table("documents").update(
            {"status": "failed", "error_message": f"Unexpected error: {exc}"}
        ).eq("id", document_id).execute()
        return

    logger.info(
        "Document %s (%r) READY — %d chunks stored.",
        document_id, source_name, result.chunk_count,
    )
    user.db.table("documents").update(
        {"status": "ready", "chunk_count": result.chunk_count}
    ).eq("id", document_id).execute()


@router.get("", response_model=list[DocumentOut])
async def list_documents(user: CurrentUser = Depends(get_current_user)):
    resp = user.db.table("documents").select("*").order("uploaded_at", desc=True).execute()
    return resp.data


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    source_type = _source_type_from_filename(file.filename)
    file_bytes = await file.read()
    logger.info(
        "Upload received | user=%s filename=%r type=%s size=%d bytes",
        user.id, file.filename, source_type, len(file_bytes),
    )
    document_id, _storage_path = _create_processing_row(
        user, source_name=file.filename, source_type=source_type, file_bytes=file_bytes
    )
    background_tasks.add_task(
        _process_ingestion,
        user,
        document_id=document_id,
        source_name=file.filename,
        source_type=source_type,
        file_bytes=file_bytes,
        image_mime_type=_content_type_from_filename(file.filename) if source_type == "image" else None,
    )
    row = user.db.table("documents").select("*").eq("id", document_id).single().execute()
    return row.data


@router.post("/youtube", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_youtube(
    body: YoutubeIngestRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    logger.info("YouTube ingest requested | user=%s url=%r", user.id, body.url)
    document_id, _storage_path = _create_processing_row(
        user, source_name=body.url, source_type="youtube"
    )
    background_tasks.add_task(
        _process_ingestion,
        user,
        document_id=document_id,
        source_name=body.url,
        source_type="youtube",
        youtube_url=body.url,
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
        logger.error("Failed to sign URL for doc %s: %s", document_id, exc)
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
            logger.warning("Failed to remove orphaned storage object %r for doc %s", storage_path, document_id)

    invalidate_user_cache(user.id)  # this user's corpus just changed -- don't serve stale BM25
    logger.info("Document %s deleted | user=%s", document_id, user.id)
    return None   