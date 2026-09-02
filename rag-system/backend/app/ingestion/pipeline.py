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

OCR/VISION STRATEGY (changed -- see also loaders.py, llm/client.py):
--------------------------------------------------------------------
Previously, the vision-model fallback for images only ran when OCR
extracted *less than ~40 characters* of text -- the assumption being
"if OCR found a real amount of text, the image is basically a text
document and OCR is good enough." That assumption broke down for
EXACTLY the cases reported as broken:

- Group photos with a caption/timestamp/watermark: OCR can return a
  short-but-nonzero string, and even when it returns nothing, the old
  code path never asked "how many people are in this photo" -- nothing
  in the fallback description prompt asked for a count.
- Marksheets/tables: a real marksheet often has PLENTY of OCR'd
  characters (subject names, numbers) -- comfortably over the 40-char
  gate -- so the vision fallback was skipped entirely even though
  tesseract's column/row alignment for a grid of numbers is exactly
  where it's least reliable (confirmed: PSM 3 dropped every mark
  column outright; PSM 6 keeps the text but can still misalign long
  rows). A "found enough characters" check has no way to know whether
  those characters are still attached to the right row.

Both cases need the SAME fix: run the vision-capable model on the
actual image (or actual scanned page) every time, not just when OCR
came up short. Gemini's models are natively multimodal, so this is a
single extra call per image/scanned-page -- worth it for correctness,
and it only affects background ingestion, never a user-facing request
latency. The prompt itself (see llm/client.py::describe_image_with_vision)
now explicitly asks for an exact people-count and for row-preserving
table/marksheet transcription.

SUMMARY CHUNK (added):
-----------------------
`summarize_for_log()` was previously called ONLY to pretty-print the
`INGEST DONE` console line -- the 2-3 sentence summary it produces
(e.g. "These documents are official academic statements of marks
issued by ... to student Deepak Singh Chouhan") never made it into the
vector store. That's a real gap, not a cosmetic one: fixed-size
chunking splits a document's identifying details (name, roll number,
enrollment number) across many chunks, each diluted with OCR noise and
vision-model boilerplate -- so no single chunk is ever a clean answer
to a broad/vague query like "tell me about deepak". The LLM-written
summary IS that clean answer; it was just being thrown away.

Fix: generate the summary once (still best-effort / never fails
ingestion), prepend it to the chunk list as a labeled "document
summary" chunk BEFORE embedding, and reuse the same summary for both
the log line and the actual index. It's chunk index 0 of every
document, so a short/entity-style query has a real chance of a direct
hit instead of needing enough exact keyword overlap to statistically
outrank noisier chunks.
"""

import logging
import time
from dataclasses import dataclass

from app.ingestion import loaders, chunking, embeddings, vectorstore
from app.retrieval.bm25_cache import invalidate_user_cache

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


@dataclass
class IngestionResult:
    chunk_count: int


_LOADERS = {
    "csv": loaders.load_csv,
    "docx": loaders.load_docx,
}

SUMMARY_CHUNK_PREFIX = "[DOCUMENT SUMMARY]"


def _make_summary_text(*, source_name: str, full_text: str) -> str:
    """
    Best-effort: generate the same short summary used in the ingestion
    log, formatted as a standalone, self-contained chunk (source name +
    summary) so it reads sensibly on its own when retrieved out of
    context. Returns "" on any failure -- summary generation must never
    break ingestion; callers fall back to skipping the summary chunk.
    """
    from app.llm.client import summarize_for_log  # local import: avoids a
    # module-level import cycle (llm/client.py doesn't import pipeline.py,
    # but keeping this import local keeps pipeline.py's own import graph
    # -- loaders/chunking/embeddings/vectorstore only -- easy to reason
    # about at a glance).

    try:
        summary = summarize_for_log(full_text)
    except Exception:  # noqa: BLE001 - must never break ingestion
        summary = ""
    if not summary:
        return ""
    return f"{SUMMARY_CHUNK_PREFIX} {source_name}: {summary}"


def _load_source_text(
    *,
    source_type: str,
    source_name: str,
    file_bytes: bytes | None,
    youtube_url: str | None,
    describe_image_fn,
) -> str:
    """The `load` stage only -- returns raw extracted text, or raises LoaderError."""
    if source_type == "youtube":
        if not youtube_url:
            raise loaders.LoaderError("Missing YouTube URL.")
        return loaders.load_youtube(youtube_url)

    if source_type == "image":
        if file_bytes is None:
            raise loaders.LoaderError("Missing image file.")
        ocr_text = loaders.load_image(file_bytes)
        if describe_image_fn is not None:
            # Always run the vision model now (see module docstring) --
            # OCR text length is not a reliable signal for "this image
            # doesn't need a real visual read." OCR text is still passed
            # in and folded into the result; it's just no longer the
            # sole source of truth.
            vision_text = describe_image_fn(file_bytes, ocr_text=ocr_text)
            return f"{ocr_text}\n\n{vision_text}".strip() if ocr_text.strip() else vision_text
        return ocr_text

    if source_type == "pdf":
        if file_bytes is None:
            raise loaders.LoaderError("Missing file bytes for pdf.")
        # describe_image_fn doubles as the per-page vision callback for
        # scanned PDF pages -- same underlying Gemini call, just invoked
        # per rendered page image instead of once on a whole photo. See
        # loaders.load_pdf's docstring for why this matters for scanned
        # marksheets specifically.
        return loaders.load_pdf(file_bytes, describe_page_fn=describe_image_fn)

    if source_type in _LOADERS:
        if file_bytes is None:
            raise loaders.LoaderError(f"Missing file bytes for {source_type}.")
        return _LOADERS[source_type](file_bytes)

    raise loaders.LoaderError(f"Unsupported source_type: {source_type}")


def _log_ingestion_summary(
    *,
    document_id: str,
    user_id: str,
    source_name: str,
    source_type: str,
    text: str,
    summary: str,
    chunks: list,
    vectors: list,
    upserted: int,
    elapsed: float,
) -> None:
    """
    Prints a detailed, human-readable ingestion report to the console
    running `uvicorn app.main:app --reload` (i.e. the VS Code terminal)
    -- summary, metadata, and a per-chunk breakdown -- so you can see
    exactly what got extracted and indexed for every upload without
    digging through a database.

    `summary` is now passed in (computed once in `ingest_file`, shared
    with the actual summary chunk that gets embedded/indexed) rather
    than generated a second time here purely for the log line.
    """
    if not summary:
        summary = text.strip().replace("\n", " ")[:300] + ("…" if len(text.strip()) > 300 else "")

    embedding_dim = len(vectors[0]) if vectors else 0

    logger.info("=" * 100)
    logger.info("INGESTION SUMMARY — %s", source_name)
    logger.info("-" * 100)
    logger.info("  Document ID      : %s", document_id)
    logger.info("  User ID          : %s", user_id)
    logger.info("  Source type      : %s", source_type)
    logger.info("  Extracted chars  : %d", len(text))
    logger.info("  Chunk count      : %d", len(chunks))
    logger.info("  Embedding dim    : %d", embedding_dim)
    logger.info("  Vectors upserted : %d", upserted)
    logger.info("  Time taken       : %.2fs", elapsed)
    logger.info("-" * 100)
    logger.info("  Summary          : %s", summary)
    logger.info("-" * 100)
    logger.info("  Chunk details (%d total):", len(chunks))
    for c in chunks:
        preview = c.text[:140].replace("\n", " ")
        logger.info("    [chunk %03d] chars=%-5d | %r", c.index, len(c.text), preview)
    logger.info("=" * 100)


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
        text = _load_source_text(
            source_type=source_type,
            source_name=source_name,
            file_bytes=file_bytes,
            youtube_url=youtube_url,
            describe_image_fn=describe_image_fn,
        )
    except loaders.LoaderError as exc:
        logger.error("INGEST FAILED (load stage) | doc=%s | %s", document_id, exc)
        raise IngestionError(str(exc)) from exc

    if not text or not text.strip():
        logger.error("INGEST FAILED (no extractable text) | doc=%s", document_id)
        raise IngestionError(
            "No extractable content found in this file (even after OCR fallback where applicable)."
        )
    logger.info("Loaded text | doc=%s | %d chars extracted", document_id, len(text))

    summary_text = _make_summary_text(source_name=source_name, full_text=text)

    body_chunks = chunking.chunk_text(text)
    if not body_chunks:
        logger.error("INGEST FAILED (zero chunks after splitting) | doc=%s", document_id)
        raise IngestionError("Content was extracted but produced zero chunks after splitting.")

    chunks = list(body_chunks)
    if summary_text:
        # Prepend as index 0 and shift the rest, so it always gets a
        # deterministic chunk_id (f"{document_id}::0") like every other
        # chunk -- no schema change, no special-casing downstream in
        # vectorstore.py or document_chunks. The [DOCUMENT SUMMARY]
        # prefix makes it identifiable in citations/previews.
        chunks = [chunking.Chunk(text=summary_text, index=0)] + [
            chunking.Chunk(text=c.text, index=i + 1) for i, c in enumerate(body_chunks)
        ]
        logger.info("Added summary chunk | doc=%s | %d chars", document_id, len(summary_text))
    else:
        logger.warning(
            "No summary chunk added (summary generation failed/empty) | doc=%s -- "
            "broad/vague queries about this document may retrieve less reliably.",
            document_id,
        )
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

    _log_ingestion_summary(
        document_id=document_id,
        user_id=user_id,
        source_name=source_name,
        source_type=source_type,
        text=text,
        summary=summary_text,
        chunks=chunks,
        vectors=vectors,
        upserted=upserted,
        elapsed=elapsed,
    )

    return IngestionResult(chunk_count=upserted) 