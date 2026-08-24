"""
tracing.py

Langfuse instrumentation for the RAG pipeline. One trace per user query,
with:
- user_id and session_id threaded onto the trace, so a mentor/developer
  can filter Langfuse by user and replay a full multi-turn conversation
  in order (Langfuse groups traces by session_id automatically).
- named spans for each pipeline stage (retrieval, generation) rather
  than one opaque span, so slow/wrong stages are individually visible.
- the custom confidence score pushed as a Langfuse *score* on the trace
  (not just returned to the frontend for display), so confidence is
  queryable/sortable/filterable in the Langfuse UI after the fact --
  e.g. "show me every trace last week with confidence < 0.3."
- a "branch" tag (small_talk vs rag) so traces can be filtered by which
  code path a query took.

Pinned in requirements.txt: `langfuse==2.*` -- the 2.x -> 3.x jump
changed the client's context-manager API in a breaking way, so pinning
avoids silently breaking tracing on an unrelated `pip install -U`.
"""

from contextlib import contextmanager

from langfuse import Langfuse

from app.config import get_settings

settings = get_settings()

_langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
) if settings.langfuse_public_key else None


class NoopTrace:
    """Used when Langfuse isn't configured, so tracing calls are safe no-ops in dev."""

    def span(self, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def update(self, **kwargs):
        pass

    def score(self, **kwargs):
        pass

    def end(self, **kwargs):
        pass


@contextmanager
def query_trace(*, user_id: str, session_id: str, query: str, branch: str):
    if _langfuse is None:
        yield NoopTrace()
        return

    trace = _langfuse.trace(
        name="rag_query",
        user_id=user_id,
        session_id=session_id,
        input={"query": query},
        tags=[branch],
        metadata={"branch": branch},
    )
    try:
        yield trace
    finally:
        trace.update(output={"done": True})


@contextmanager
def stage_span(trace, name: str, **input_kwargs):
    if isinstance(trace, NoopTrace):
        yield NoopTrace()
        return
    span = trace.span(name=name, input=input_kwargs)
    try:
        yield span
    finally:
        span.end()


def record_confidence(trace, score: float, label: str, components: dict) -> None:
    if isinstance(trace, NoopTrace):
        return
    trace.score(name="confidence", value=score, comment=f"{label}: {components}")
