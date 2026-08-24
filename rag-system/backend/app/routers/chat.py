"""
routers/chat.py

The orchestration for a single turn: retrieve -> generate (streamed) ->
score confidence -> persist -> trace. This is intentionally the one
place that ties every other module together, per the "thin
orchestration layer" non-functional requirement -- no retrieval,
confidence, or generation logic lives in this file itself.
"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser, get_current_user
from app.llm.client import stream_answer, is_small_talk
from app.llm.confidence import compute_confidence
from app.models import ChatRequest
from app.observability.tracing import query_trace, stage_span, record_confidence
from app.retrieval.hybrid import hybrid_search
from app.retrieval.rerank import rerank

router = APIRouter(prefix="/chat", tags=["chat"])


def _load_history(db, session_id: str, user_id: str) -> list[dict]:
    resp = (
        db.table("chat_messages")
        .select("role, content")
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    return [{"role": r["role"], "content": r["content"]} for r in resp.data]


@router.post("")
async def chat(body: ChatRequest, user: CurrentUser = Depends(get_current_user)):
    branch = "small_talk" if is_small_talk(body.message) else "rag"

    def event_stream():
        with query_trace(user_id=user.id, session_id=body.session_id, query=body.message, branch=branch) as trace:
            # Persist the user's message first.
            user.db.table("chat_messages").insert(
                {"session_id": body.session_id, "user_id": user.id, "role": "user", "content": body.message}
            ).execute()

            chunks = []
            if branch == "rag":
                with stage_span(trace, "retrieval", query=body.message) as span:
                    fused = hybrid_search(user.db, user.id, body.message)
                    chunks = rerank(body.message, fused)
                    span.update(output={"retrieved": [c.text[:200] for c in chunks]})

            history = _load_history(user.db, body.session_id, user.id)

            full_answer = ""
            with stage_span(trace, "generation", language=body.language) as gen_span:
                for delta in stream_answer(
                    question=body.message, chunks=chunks, history=history, language_hint=body.language
                ):
                    full_answer += delta
                    yield f"data: {json.dumps({'type': 'token', 'content': delta})}\n\n"
                gen_span.update(output={"answer": full_answer})

            confidence = compute_confidence(full_answer, chunks)
            grounded = confidence.label != "Low" and bool(chunks)
            record_confidence(trace, confidence.score, confidence.label, confidence.components)

            citations = [
                {
                    "source_name": c.source_name,
                    "relevance_score": round(c.rrf_score, 4),
                    "preview": c.text[:220],
                    "document_id": c.document_id,
                }
                for c in chunks
            ]

            # Persist the assistant turn.
            user.db.table("chat_messages").insert(
                {
                    "session_id": body.session_id,
                    "user_id": user.id,
                    "role": "assistant",
                    "content": full_answer,
                    "citations": citations,
                    "confidence": confidence.score,
                }
            ).execute()
            user.db.table("chat_sessions").update({"last_active_at": "now()"}).eq(
                "id", body.session_id
            ).eq("user_id", user.id).execute()

            yield f"data: {json.dumps({'type': 'done', 'citations': citations, 'confidence_score': confidence.score, 'confidence_label': confidence.label, 'grounded': grounded})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
