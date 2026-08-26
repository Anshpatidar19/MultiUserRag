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


def describe_image_with_vision(image_bytes: bytes) -> str:
    """
    Fallback used by ingestion/pipeline.py when OCR extracts nothing
    from an uploaded image (e.g. a photo/diagram with no text) -- asks
    Gemini to produce a searchable description so the image's *content*
    is still retrievable, not just literal text in it.

    Uses the same `gemini_model` as chat -- no separate vision-only
    model needed, since Gemini's models are natively multimodal (unlike
    the old Groq setup, which required switching to a distinct
    vision-capable model and was the source of a "content must be a
    string" 400 error when that switch was missed).
    """
    resp = _client.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Part.from_text(text="Describe this image in detail for search indexing."),
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        ],
    )
    return resp.text or ""