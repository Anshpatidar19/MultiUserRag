import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    text: str
    index: int


def _split_on(text: str, pattern: re.Pattern) -> list[str]:
    parts = [p.strip() for p in pattern.split(text) if p.strip()]
    return parts


def _pack(units: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""

    for unit in units:
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""
            current = f"{tail} {unit}".strip()
        else:
            for i in range(0, len(unit), chunk_size - overlap or chunk_size):
                chunks.append(unit[i : i + chunk_size])
            current = ""

    if current:
        chunks.append(current)

    return chunks


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[Chunk]:
    text = text.strip()
    if not text:
        logger.warning("chunk_text() called with empty/whitespace-only text — returning 0 chunks.")
        return []

    paragraphs = _split_on(text, PARAGRAPH_SPLIT)
    if not paragraphs:
        paragraphs = [text]

    units: list[str] = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            units.append(para)
        else:
            sentences = _split_on(para, SENTENCE_SPLIT) or [para]
            units.extend(sentences)

    raw_chunks = _pack(units, chunk_size, overlap)
    chunks = [Chunk(text=c, index=i) for i, c in enumerate(raw_chunks) if c.strip()]

    sizes = [len(c.text) for c in chunks]
    logger.info(
        "chunk_text(): input=%d chars -> %d paragraphs -> %d chunks "
        "(chunk_size=%d, overlap=%d, avg_chunk_len=%d, min=%d, max=%d)",
        len(text),
        len(paragraphs),
        len(chunks),
        chunk_size,
        overlap,
        (sum(sizes) // len(sizes)) if sizes else 0,
        min(sizes) if sizes else 0,
        max(sizes) if sizes else 0,
    )
    return chunks