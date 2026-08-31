"""
client.py

Gemini generation via Google's official `google-genai` SDK (the current
recommended package -- NOT the older, now-superseded
`google-generativeai`), with streaming.

Gemini's models are natively multimodal, so unlike the previous
Groq-based implementation -- which needed a separate vision-only model
for image description, since its main chat model was text-only -- both
text chat and image description here run through the SAME model.

DESIGN DECISION -- agentic vs. hard-gated (spec section 4):
This system defaults to AGENTIC (settings.generation_mode == "agentic"):
the assistant always attempts an answer. When retrieved-context
confidence is low, it still answers using the LLM's general knowledge,
but the system prompt forces it to explicitly say the answer is "not
based on your documents." The alternative -- a hard code-level gate that
refuses to generate below `confidence_gate_threshold` -- is implemented
too (settings.generation_mode = "gated") and is a one-line config flip,
but is not the default.

Rationale for defaulting to agentic: for a knowledge-base assistant,
silently refusing ("I don't have enough information") is often *less*
useful than a clearly-labeled general-knowledge answer, because the user
still gets to decide whether to trust it -- whereas a hard refusal gives
them nothing and forces a manual fallback to a general search engine
anyway. Gated mode is provided for deployments where a wrong-but-labeled
answer is worse than no answer (e.g. compliance/legal contexts) -- that
tradeoff is a deployment decision, which is why it's a config flag and
documented here rather than hardcoded.
"""

from collections.abc import Iterator

from google import genai
from google.genai import types

from app.config import get_settings
from app.retrieval.hybrid import RetrievedChunk

settings = get_settings()

_client = genai.Client(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """You are a retrieval-augmented assistant. You are given CONTEXT \
retrieved from the user's private knowledge base. Answer the user's question.

Rules:
- If the CONTEXT contains a clear answer, use it and cite it naturally in prose.
- If the CONTEXT is empty, irrelevant, or only weakly related to the question, \
you may still answer from your own general knowledge, but you MUST prefix that \
part of the answer with a clear note, e.g. "(Not based on your documents — \
this is general knowledge)".
- Never present general knowledge as if it came from the user's documents.
- Be concise and directly answer the question first; do not pad with disclaimers \
beyond the one required note above.
- If the user's message is small talk / a greeting with no informational question, \
just respond naturally and briefly -- do not force in a documents disclaimer.
"""


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no relevant context retrieved from the knowledge base)"
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] Source: {c.source_name}\n{c.text}")
    return "\n\n".join(parts)


def is_small_talk(message: str) -> bool:
    """
    Cheap heuristic branch tag (used for observability tagging in
    observability/tracing.py) -- greetings/pleasantries shouldn't be
    forced through the "not based on your documents" framing.
    """
    normalized = message.strip().lower()
    greetings = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "bye", "good morning", "good evening"}
    return normalized in greetings or len(normalized.split()) <= 2 and any(g in normalized for g in greetings)


def _history_to_gemini(history: list[dict]) -> list[types.Content]:
    """
    Maps this app's stored {"role": "user"|"assistant", "content": str}
    turns (see chat_messages, constrained to those two role values by
    supabase/schema.sql) onto Gemini's Content objects.

    Two things don't carry over directly from the old OpenAI-style
    format:
    - Gemini has no "assistant" role -- a prior model turn is
      role="model".
    - Gemini has no "system" role in the contents list at all; the
      system prompt is passed separately via
      GenerateContentConfig.system_instruction (see stream_answer
      below), not as a message here.
    """
    mapped = []
    for turn in history[-6:]:  # bounded recent history for multi-turn continuity
        role = "model" if turn["role"] == "assistant" else "user"
        mapped.append(types.Content(role=role, parts=[types.Part.from_text(text=turn["content"])]))
    return mapped


def stream_answer(
    *,
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict],
    language_hint: str | None = None,
) -> Iterator[str]:
    context_block = build_context_block(chunks)
    lang_instruction = (
        f"\nRespond in the same language as the user's message (detected/requested: {language_hint})."
        if language_hint
        else "\nRespond in the same language the user wrote their message in (auto-detect; supports at least English and Hindi)."
    )

    contents = _history_to_gemini(history)
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"CONTEXT:\n{context_block}\n\nQUESTION:\n{question}")],
        )
    )

    stream = _client.models.generate_content_stream(
        model=settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT + lang_instruction,
            temperature=0.2,
        ),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text


def describe_image_with_vision(
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
    ocr_text: str = "",
) -> str:
    """
    Fallback used by ingestion/pipeline.py when OCR extracts little or no
    usable text from an uploaded image (e.g. a photo/diagram with no
    text, or only a stray watermark/timestamp) -- asks Gemini to produce
    a searchable description so the image's *content* is still
    retrievable, not just literal text in it.

    The prompt below is deliberately more specific than a bare "describe
    this image" would be. A generic description (e.g. "a person stands
    near an ornate sandstone building with domes") is visually accurate
    but omits the ONE detail later identity questions actually search
    for -- the landmark's name -- because nothing in a generic prompt
    asks the model to commit to an identification. Since this caption is
    generated once at upload time and is the ONLY thing chat retrieval
    can ever search against for this image (chat itself has no image
    input -- see ChatRequest in models.py), it has to front-load
    identification now or "is this X" / "which monument is this"
    questions will never find a match later.

    `mime_type` MUST match the actual uploaded file's format -- a PNG
    sent with mime_type="image/jpeg" was a real bug here previously
    (hardcoded default) and can degrade or break Gemini's read of the
    image. Callers should always pass the real content type.

    `ocr_text`, if provided, is folded into the prompt so real text
    OCR *did* find (e.g. a sign, a caption, a label) isn't discarded
    just because it wasn't the whole story -- the model is asked to
    incorporate it rather than duplicate or ignore it.

    Uses the same `gemini_model` as chat -- no separate vision-only
    model needed, since Gemini's models are natively multimodal (unlike
    the old Groq setup, which required switching to a distinct
    vision-capable model and was the source of a "content must be a
    string" 400 error when that switch was missed).
    """
    ocr_note = (
        f"\n\nOCR already extracted this text from the image (it may be "
        f"partial, noisy, or have misaligned rows/columns -- scanned "
        f"tables and grids are exactly where OCR tends to garble which "
        f"number belongs to which row): \"{ocr_text.strip()}\". Use it as "
        "a hint for spellings/labels, but READ THE IMAGE YOURSELF for "
        "anything structured (tables, forms, grids of numbers) rather "
        "than trusting the OCR text's alignment -- your own reading of "
        "the pixels is the more reliable source for which value belongs "
        "to which row/column."
        if ocr_text.strip()
        else ""
    )
    prompt = (
        "Look at this image carefully and produce a detailed, search-indexable "
        "description. Cover EVERY one of the following that applies -- skip a "
        "numbered point only if it genuinely doesn't apply to this image:\n\n"
        "1. PEOPLE / GROUP PHOTOS: If any people are visible, state the exact "
        "number of people in the image (count every visible person, including "
        "partially visible or background ones -- if you are genuinely unsure "
        "whether two people overlap into one, give your best count and say so, "
        "e.g. \"approximately 7 people\"). Briefly describe each person's "
        "relative position (e.g. \"left to right: ...\") and what they're doing, "
        "facing, or looking at, since viewers will later ask things like "
        "\"how many people are in this photo\" or \"who is looking at the camera.\"\n\n"
        "2. TABLES, FORMS, MARKSHEETS, AND GRIDS OF NUMBERS: If the image contains "
        "a table, form, marksheet, invoice, spreadsheet screenshot, or any grid "
        "of labeled numbers, transcribe it as clean structured text, ONE ROW PER "
        "LINE, preserving the exact association between each label and its "
        "number(s) -- e.g. for a marksheet: \"Subject: Mathematics | Marks "
        "Obtained: 85 | Maximum Marks: 100\". Read every digit directly off the "
        "image pixel-by-pixel; do not guess or round. Include every row and every "
        "column, and also state the total/aggregate/percentage/grade if one is "
        "printed on the sheet. Double-check that no row's numbers have been "
        "accidentally shifted onto a neighboring row.\n\n"
        "3. LANDMARKS AND PLACES: If the image shows a recognizable landmark, "
        "monument, statue, building, or place, state its specific name explicitly "
        "(e.g. \"This is the Albert Hall Museum in Jaipur\" or \"This is the "
        "Statue of Unity, Gujarat\") -- do not just describe its architecture "
        "generically. If unsure of the exact name, give your best guess and say "
        "it's uncertain, rather than omitting a name entirely. If people are "
        "visible near a landmark, note where they are standing, facing, or "
        "looking relative to it.\n\n"
        "4. GENERAL SCENE: For anything not covered above (objects, animals, "
        "diagrams, screenshots, charts, etc.), describe what's shown in enough "
        "detail that someone could find this image later by searching for its "
        "content." + ocr_note
    )
    resp = _client.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
    )
    return resp.text or ""


_LOG_SUMMARY_MAX_INPUT_CHARS = 6000


def summarize_for_log(text: str) -> str:
    """
    Cheap, best-effort 2-3 sentence summary of a document's extracted
    text, generated purely so `INGEST DONE` log lines (see
    ingestion/pipeline.py) show a human-readable summary of *what was
    actually uploaded* in the VS Code terminal, not just a char/chunk
    count. Never raises -- ingestion must never fail because a nice-to-have
    log line couldn't be generated; callers should wrap this in try/except
    regardless, but it also fails soft internally as a second layer.
    """
    snippet = text.strip()[:_LOG_SUMMARY_MAX_INPUT_CHARS]
    if not snippet:
        return ""
    try:
        resp = _client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_text(
                    text=(
                        "Summarize the following document content in 2-3 concise, "
                        "factual sentences for a developer log (no preamble like "
                        "\"This document is about\", just the summary itself):\n\n"
                        f"{snippet}"
                    )
                ),
            ],
        )
        return (resp.text or "").strip()
    except Exception:  # noqa: BLE001 - logging-only helper, never break ingestion
        return ""