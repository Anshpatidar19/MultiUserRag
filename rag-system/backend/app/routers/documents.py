"""
routers/documents.py

Upload endpoints per format, plus list/delete. Route handlers stay thin
on purpose: they create the `documents` row, delegate the actual
load->chunk->embed->upsert work to ingestion/pipeline.py, and translate
`IngestionError` into a "failed" status with a clear error_message
instead of a generic 500 -- this is the API-level half of the
"fail loudly, no silent zero-chunk ghosts" requirement.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth import CurrentUser, get_current_user
from app.ingestion.pipeline import ingest_file, IngestionError
from app.ingestion.vectorstore import delete_document as delete_vectors
from app.llm.client import describe_image_with_vision
from app.models import DocumentOut, YoutubeIngestRequest
from app.retrieval.bm25_cache import invalidate_user_cache

router = APIRouter(prefix="/documents", tags=["documents"])

_EXT_TO_TYPE = {"pdf": "pdf", "csv": "csv", "docx": "docx", "png": "image", "jpg": "image", "jpeg": "image"}


def _source_type_from_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _EXT_TO_TYPE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported file type: .{ext}")
    return _EXT_TO_TYPE[ext]


async def _run_ingestion(
    user: CurrentUser,
    *,
    source_name: str,
    source_type: str,
    file_bytes: bytes | None = None,
    youtube_url: str | None = None,
):
    document_id = str(uuid.uuid4())

    # Insert as "processing" first so the frontend can show it immediately.
    user.db.table("documents").insert(
        {
            "id": document_id,
            "user_id": user.id,
            "source_name": source_name,
            "source_type": source_type,
            "chunk_count": 0,
            "status": "processing",
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


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, user: CurrentUser = Depends(get_current_user)):
    user.db.table("documents").delete().eq("id", document_id).eq("user_id", user.id).execute()
    delete_vectors(user_id=user.id, document_id=document_id)
    user.db.table("document_chunks").delete().eq("document_id", document_id).eq("user_id", user.id).execute()
    invalidate_user_cache(user.id)  # this user's corpus just changed -- don't serve stale BM25
    return None
