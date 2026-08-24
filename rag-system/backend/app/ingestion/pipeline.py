"""
pipeline.py

Thin orchestration layer: load -> chunk -> embed -> upsert. Deliberately
contains almost no logic of its own -- each stage is a separately
testable module (loaders/chunking/embeddings/vectorstore), and this file
just wires them together and enforces the one cross-cutting rule that
matters most: FAIL LOUDLY on zero chunks or zero vectors.

That "fail loudly" rule is why `status` is written as "failed" with a
concrete `error_message` instead of silently leaving a 0-chunk "ghost"
document row that looks uploaded but is unqueryable -- a document a
user can see in their sidebar but that never surfaces in an answer is a
worse experience than an upload that visibly errors.
"""

from dataclasses import dataclass

from app.ingestion import loaders, chunking, embeddings, vectorstore
from app.retrieval.bm25_cache import invalidate_user_cache


class IngestionError(Exception):
    pass


@dataclass
class IngestionResult:
    chunk_count: int


_LOADERS = {
    "pdf": loaders.load_pdf,
    "csv": loaders.load_csv,
    "docx": loaders.load_docx,
}


def ingest_file(
    *,
    db,  # RLS-scoped Supabase client (see app/db.py) -- used to mirror chunk text for BM25
    user_id: str,
    document_id: str,
    source_name: str,
    source_type: str,
    file_bytes: bytes | None = None,
    youtube_url: str | None = None,
    describe_image_fn=None,  # injected vision-model fallback, see below
) -> IngestionResult:
    """
    describe_image_fn: optional callable(bytes) -> str, used only when
    source_type == "image" and OCR extracts nothing. Injected rather than
    imported directly so this module doesn't hard-depend on the LLM
    client (keeps ingestion testable without a live Groq key).
    """
    try:
        if source_type == "youtube":
            if not youtube_url:
                raise loaders.LoaderError("Missing YouTube URL.")
            text = loaders.load_youtube(youtube_url)
        elif source_type == "image":
            if file_bytes is None:
                raise loaders.LoaderError("Missing image file.")
            text = loaders.load_image(file_bytes)
            if not text.strip() and describe_image_fn is not None:
                text = describe_image_fn(file_bytes)
        elif source_type in _LOADERS:
            if file_bytes is None:
                raise loaders.LoaderError(f"Missing file bytes for {source_type}.")
            text = _LOADERS[source_type](file_bytes)
        else:
            raise loaders.LoaderError(f"Unsupported source_type: {source_type}")
    except loaders.LoaderError as exc:
        raise IngestionError(str(exc)) from exc

    if not text or not text.strip():
        raise IngestionError(
            "No extractable content found in this file (even after OCR fallback where applicable)."
        )

    chunks = chunking.chunk_text(text)
    if not chunks:
        raise IngestionError("Content was extracted but produced zero chunks after splitting.")

    vectors = embeddings.embed_texts([c.text for c in chunks])
    if not vectors or len(vectors) != len(chunks):
        raise IngestionError("Embedding step produced zero (or mismatched) vectors.")

    upserted = vectorstore.upsert_chunks(
        user_id=user_id,
        document_id=document_id,
        chunks=[c.text for c in chunks],
        embeddings=vectors,
        source_name=source_name,
    )
    if upserted == 0:
        raise IngestionError("Vector store reported zero vectors upserted.")

    # Mirror chunk text into Postgres (document_chunks) so the BM25 side
    # of hybrid retrieval has something to index -- Pinecone alone
    # doesn't offer a cheap "list all vectors for this user" call.
    db.table("document_chunks").insert(
        [
            {
                "chunk_id": f"{document_id}::{c.index}",
                "document_id": document_id,
                "user_id": user_id,
                "source_name": source_name,
                "chunk_index": c.index,
                "text": c.text,
            }
            for c in chunks
        ]
    ).execute()

    # This user's document set just changed -- their cached BM25 corpus
    # is now stale and must not be served again until rebuilt.
    invalidate_user_cache(user_id)

    return IngestionResult(chunk_count=upserted)
