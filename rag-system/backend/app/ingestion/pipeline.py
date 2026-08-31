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

import logging
import time
from dataclasses import dataclass

from app.ingestion import loaders, chunking, embeddings, vectorstore
from app.retrieval.bm25_cache import invalidate_user_cache

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


# OCR on a real photo (as opposed to a scanned text document) very often
# returns a *few* stray characters -- a watermark, a timestamp, noise
# misread from a texture -- without returning nothing at all. The old
# gate ("if not text.strip()") treated any non-empty OCR result as "this
# image has usable text," which skipped the vision description entirely
# and left the image indexed under a near-useless scrap. This threshold
# means "OCR found less than a real sentence's worth of content," which
# is a much better proxy for "this image actually needs a vision
# description" than mere non-emptiness.
_MIN_OCR_CHARS_BEFORE_SKIPPING_VISION = 40


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
    db,
    user_id: str,
    document_id: str,
    source_name: str,
    source_type: str,
    file_bytes: bytes | None = None,
    youtube_url: str | None = None,
    describe_image_fn=None,
) -> IngestionResult:
    t0 = time.perf_counter()
    logger.info(
        "INGEST START | user=%s doc=%s source=%r type=%s",
        user_id, document_id, source_name, source_type,
    )

    try:
        if source_type == "youtube":
            if not youtube_url:
                raise loaders.LoaderError("Missing YouTube URL.")
            text = loaders.load_youtube(youtube_url)
        elif source_type == "image":
            if file_bytes is None:
                raise loaders.LoaderError("Missing image file.")
            ocr_text = loaders.load_image(file_bytes)
            if len(ocr_text.strip()) < _MIN_OCR_CHARS_BEFORE_SKIPPING_VISION and describe_image_fn is not None:
                logger.info(
                    "OCR found only %d char(s) for %r (below %d-char threshold) — "
                    "running vision model to get a real description.",
                    len(ocr_text.strip()), source_name, _MIN_OCR_CHARS_BEFORE_SKIPPING_VISION,
                )
                vision_text = describe_image_fn(file_bytes, ocr_text=ocr_text)
                # Keep whatever OCR found (it may still be a real, short
                # label/caption) alongside the richer vision description,
                # rather than throwing it away.
                text = f"{ocr_text}\n\n{vision_text}".strip() if ocr_text.strip() else vision_text
            else:
                text = ocr_text
        elif source_type in _LOADERS:
            if file_bytes is None:
                raise loaders.LoaderError(f"Missing file bytes for {source_type}.")
            text = _LOADERS[source_type](file_bytes)
        else:
            raise loaders.LoaderError(f"Unsupported source_type: {source_type}")
    except loaders.LoaderError as exc:
        logger.error("INGEST FAILED (load stage) | doc=%s | %s", document_id, exc)
        raise IngestionError(str(exc)) from exc

    if not text or not text.strip():
        logger.error("INGEST FAILED (no extractable text) | doc=%s", document_id)
        raise IngestionError(
            "No extractable content found in this file (even after OCR fallback where applicable)."
        )
    logger.info("Loaded text | doc=%s | %d chars extracted", document_id, len(text))

    chunks = chunking.chunk_text(text)
    if not chunks:
        logger.error("INGEST FAILED (zero chunks after splitting) | doc=%s", document_id)
        raise IngestionError("Content was extracted but produced zero chunks after splitting.")
    logger.info("Chunked | doc=%s | %d chunks created", document_id, len(chunks))

    vectors = embeddings.embed_texts([c.text for c in chunks])
    if not vectors or len(vectors) != len(chunks):
        logger.error(
            "INGEST FAILED (embedding mismatch) | doc=%s | chunks=%d vectors=%d",
            document_id, len(chunks), len(vectors) if vectors else 0,
        )
        raise IngestionError("Embedding step produced zero (or mismatched) vectors.")
    logger.info("Embedded | doc=%s | %d vectors (dim=%d)", document_id, len(vectors), len(vectors[0]) if vectors else 0)

    upserted = vectorstore.upsert_chunks(
        user_id=user_id,
        document_id=document_id,
        chunks=[c.text for c in chunks],
        embeddings=vectors,
        source_name=source_name,
    )
    if upserted == 0:
        logger.error("INGEST FAILED (zero vectors upserted) | doc=%s", document_id)
        raise IngestionError("Vector store reported zero vectors upserted.")

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

    invalidate_user_cache(user_id)

    elapsed = time.perf_counter() - t0
    logger.info(
        "INGEST DONE | user=%s doc=%s source=%r | %d chunks upserted in %.2fs",
        user_id, document_id, source_name, upserted, elapsed,
    )

    return IngestionResult(chunk_count=upserted)