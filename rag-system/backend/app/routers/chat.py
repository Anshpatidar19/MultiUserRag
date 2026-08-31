"""
routers/chat.py

The orchestration for a single turn: retrieve -> generate (streamed) ->
score confidence -> persist -> trace.
"""

import json
import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser, get_current_user
from app.llm.client import stream_answer, is_small_talk
from app.llm.confidence import compute_confidence
from app.models import ChatRequest
from app.observability.tracing import query_trace, stage_span, record_confidence
from app.config import get_settings
from app.retrieval.hybrid import hybrid_search
from app.retrieval.rerank import rerank

router = APIRouter(prefix="/chat", tags=["chat"])
settings = get_settings()
logger = logging.getLogger(__name__)


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
    t0 = time.perf_counter()
    logger.info("QUERY START | user=%s session=%s branch=%s | %r", user.id, body.session_id, branch, body.message)

    def event_stream():
        with query_trace(user_id=user.id, session_id=body.session_id, query=body.message, branch=branch) as trace:
            user.db.table("chat_messages").insert(
                {"session_id": body.session_id, "user_id": user.id, "role": "user", "content": body.message}
            ).execute()

            chunks = []
            if branch == "rag":
                yield f"data: {json.dumps({'type': 'status', 'message': 'Searching your documents…'})}\n\n"
                with stage_span(trace, "retrieval", query=body.message) as span:
                    fused = hybrid_search(user.db, user.id, body.message)
                    reranked = rerank(body.message, fused)
                    filtered = [
                        c
                        for c in reranked
                        if c.rerank_score is None or c.rerank_score >= settings.retrieval_min_rerank_score
                    ]
                    chunks = filtered[: settings.retrieval_top_k]
                    span.update(output={"retrieved": [c.text[:200] for c in chunks]})

                    logger.info(
                        "RETRIEVAL SUMMARY | fused=%d -> reranked=%d -> above_threshold(%.2f)=%d -> final_top_k=%d",
                        len(fused), len(reranked), settings.retrieval_min_rerank_score, len(filtered), len(chunks),
                    )
                    for i, c in enumerate(chunks):
                        logger.info(
                            "  chunk #%d | source=%r | rrf=%.4f | rerank=%s",
                            i + 1, c.source_name, c.rrf_score,
                            f"{c.rerank_score:.4f}" if c.rerank_score is not None else "n/a",
                        )
                yield f"data: {json.dumps({'type': 'status', 'message': 'Reading relevant sources…'})}\n\n"
            else:
                logger.info("SMALL TALK branch — retrieval skipped for this query.")
                yield f"data: {json.dumps({'type': 'status', 'message': 'Thinking…'})}\n\n"

            history = _load_history(user.db, body.session_id, user.id)

            yield f"data: {json.dumps({'type': 'status', 'message': 'Writing an answer…'})}\n\n"

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

            elapsed = time.perf_counter() - t0
            logger.info(
                "QUERY DONE | user=%s session=%s | chunks_used=%d | confidence=%.2f (%s) | grounded=%s | %.2fs",
                user.id, body.session_id, len(chunks), confidence.score, confidence.label, grounded, elapsed,
            )

            yield f"data: {json.dumps({'type': 'done', 'citations': citations, 'confidence_score': confidence.score, 'confidence_label': confidence.label, 'grounded': grounded})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")