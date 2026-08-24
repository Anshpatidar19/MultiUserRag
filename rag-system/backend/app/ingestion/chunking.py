"""
chunking.py

Recursive character-based splitter: try to break on paragraph boundaries
first, then sentence boundaries, then word boundaries, only falling back
to a hard character cut as a last resort. The point is that a chunk
boundary landing mid-sentence is worse for embedding quality than a
slightly-off-target chunk size, so we prefer "close to chunk_size but
respects a natural boundary" over "exactly chunk_size."

Configurable overlap keeps a sliding window of context between adjacent
chunks so a fact split across a chunk boundary isn't lost to retrieval.
"""

import re
from dataclasses import dataclass

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
    """
    Greedily pack small units (paragraphs, sentences, or words) into
    chunks up to chunk_size chars, carrying `overlap` chars of trailing
    context forward into the next chunk.
    """
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
            # Single unit longer than chunk_size (e.g. a huge sentence);
            # hard-cut it rather than losing it entirely.
            for i in range(0, len(unit), chunk_size - overlap or chunk_size):
                chunks.append(unit[i : i + chunk_size])
            current = ""

    if current:
        chunks.append(current)

    return chunks


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[Chunk]:
    """
    chunk_size / overlap are in characters, not tokens -- simpler to
    reason about and good enough given the embedding model's short
    context window (all-MiniLM-L6-v2 truncates at 256 tokens anyway,
    so we deliberately keep chunk_size well under a rough 4-chars/token
    estimate for that limit).
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = _split_on(text, PARAGRAPH_SPLIT)
    if not paragraphs:
        paragraphs = [text]

    # If a single paragraph is already too big, break it into sentences
    # before packing, so we don't hard-cut mid-sentence unnecessarily.
    units: list[str] = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            units.append(para)
        else:
            sentences = _split_on(para, SENTENCE_SPLIT) or [para]
            units.extend(sentences)

    raw_chunks = _pack(units, chunk_size, overlap)
    return [Chunk(text=c, index=i) for i, c in enumerate(raw_chunks) if c.strip()]
