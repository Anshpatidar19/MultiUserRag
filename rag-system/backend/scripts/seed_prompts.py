"""
seed_prompts.py

Run once (and again whenever you want to push a new prompt version) to
create/update prompts in Langfuse. Usage, from backend/:

    python -m scripts.seed_prompts

All three prompts used by app/llm/client.py are seeded here. Prompt
text uses Langfuse's {{variable}} syntax where the caller needs to
inject something at runtime -- see client.py's get_system_prompt(),
get_image_caption_prompt(), and get_log_summary_prompt() for how each
is compiled.
"""

from langfuse import Langfuse

from app.config import get_settings

settings = get_settings()

langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
)

# 1. Main RAG answer-generation prompt
# Variables: {{lang_instruction}}
langfuse.create_prompt(
    name="rag-system-prompt",
    prompt="""You are a retrieval-augmented assistant. You are given CONTEXT \
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
{{lang_instruction}}""",
    config={"model": settings.gemini_model, "temperature": 0.2},
    labels=["production"],
)

# 2. Image captioning prompt (used at upload time, ingestion/pipeline.py)
# Variables: {{ocr_note}} -- empty string if no OCR text was found
langfuse.create_prompt(
    name="rag-image-caption-prompt",
    prompt="""Look at this image carefully and produce a detailed, search-indexable \
description. Cover EVERY one of the following that applies -- skip a numbered \
point only if it genuinely doesn't apply to this image:

1. PEOPLE / GROUP PHOTOS: If any people are visible, state the exact number of \
people in the image (count every visible person, including partially visible or \
background ones -- if you are genuinely unsure whether two people overlap into \
one, give your best count and say so, e.g. "approximately 7 people"). Briefly \
describe each person's relative position (e.g. "left to right: ...") and what \
they're doing, facing, or looking at, since viewers will later ask things like \
"how many people are in this photo" or "who is looking at the camera."

2. TABLES, FORMS, MARKSHEETS, AND GRIDS OF NUMBERS: If the image contains a \
table, form, marksheet, invoice, spreadsheet screenshot, or any grid of labeled \
numbers, transcribe it as clean structured text, ONE ROW PER LINE, preserving \
the exact association between each label and its number(s) -- e.g. for a \
marksheet: "Subject: Mathematics | Marks Obtained: 85 | Maximum Marks: 100". \
Read every digit directly off the image pixel-by-pixel; do not guess or round. \
Include every row and every column, and also state the total/aggregate/percentage/grade \
if one is printed on the sheet. Double-check that no row's numbers have been \
accidentally shifted onto a neighboring row.

3. LANDMARKS AND PLACES: If the image shows a recognizable landmark, monument, \
statue, building, or place, state its specific name explicitly (e.g. "This is \
the Albert Hall Museum in Jaipur" or "This is the Statue of Unity, Gujarat") -- \
do not just describe its architecture generically. If unsure of the exact name, \
give your best guess and say it's uncertain, rather than omitting a name entirely. \
If people are visible near a landmark, note where they are standing, facing, or \
looking relative to it.

4. GENERAL SCENE: For anything not covered above (objects, animals, diagrams, \
screenshots, charts, etc.), describe what's shown in enough detail that someone \
could find this image later by searching for its content.{{ocr_note}}""",
    config={"model": settings.gemini_model},
    labels=["production"],
)

# 3. Ingestion log-summary prompt (dev-log readability only)
# Variables: {{snippet}}
langfuse.create_prompt(
    name="rag-log-summary-prompt",
    prompt="""Summarize the following document content in 2-3 concise, factual \
sentences for a developer log (no preamble like "This document is about", just \
the summary itself):

{{snippet}}""",
    config={"model": settings.gemini_model},
    labels=["production"],
)

print("Pushed 3 prompts to Langfuse: rag-system-prompt, rag-image-caption-prompt, rag-log-summary-prompt")