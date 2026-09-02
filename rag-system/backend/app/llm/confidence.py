"""
confidence.py

A CUSTOM confidence score -- explicitly not the LLM's self-reported
confidence, because models are known to be overconfident and their
stated confidence doesn't reliably track actual grounding. Instead we
blend three independently-measurable signals:

1. retrieval_similarity: how well-matched the retrieved chunks are to
   the query. Uses real dense cosine scores where available, and a
   sensible imputed estimate where a chunk only matched via the BM25
   keyword side (see _chunk_similarity_estimate below) -- an exact
   keyword hit is a real signal, not "no evidence."
2. source_agreement: how many *distinct documents* contributed to the
   top-k context, credited generously for a single well-matched source
   rather than assuming multi-document corroboration is required to
   trust an answer (a single-document knowledge base is a normal,
   common case).
3. lexical_semantic_grounding: token-overlap-based similarity between
   the generated answer and the retrieved context, as a lightweight
   proxy for "did the model actually use what we gave it, or drift into
   its own general knowledge." (A full entailment/NLI model would be
   more accurate; overlap is a fast, dependency-light approximation --
   swap in an NLI model here if better accuracy is worth the latency.)

The weights below are a starting point, tuned to be conservative (favor
flagging low confidence over over-trusting), not a claim of statistical
optimality -- documented here so the choice is explicit and revisitable.
"""

from dataclasses import dataclass

from app.retrieval.hybrid import RetrievedChunk
from app.retrieval.tokenizer import tokenize

WEIGHTS = {
    "retrieval_similarity": 0.4,
    "source_agreement": 0.25,
    "lexical_semantic_grounding": 0.35,
}


@dataclass
class ConfidenceResult:
    score: float  # 0..1
    label: str  # "High" | "Medium" | "Low"
    components: dict[str, float]


def _tokens(text: str) -> set[str]:
    # Uses the same stemming tokenizer as BM25 (retrieval/tokenizer.py),
    # not an independent copy -- so grounding overlap isn't unfairly
    # penalized just because the model phrased something as "accounting"
    # when the source text said "accounts" (or any other morphological
    # variant of the same word). See tokenizer.py for the full rationale.
    return set(tokenize(text))


def _label(score: float) -> str:
    if score >= 0.66:
        return "High"
    if score >= 0.35:
        return "Medium"
    return "Low"


def _chunk_similarity_estimate(c: RetrievedChunk) -> float:
    """
    Prefer the real dense cosine score. If a chunk only surfaced via
    the BM25 keyword side of hybrid search (dense_score is None -- it
    didn't rank in Pinecone's top candidates, only in the keyword
    search), that is NOT evidence of a weak match; it just means we
    don't have a cosine number for it. An exact keyword hit that made
    it through RRF fusion and reranking is still a real relevance
    signal, so it gets a moderate imputed score instead of silently
    contributing zero and dragging the whole calculation down.
    """
    if c.dense_score is not None:
        return max(0.0, min(1.0, c.dense_score))
    return 0.6 if c.bm25_score is not None else 0.3


def compute_confidence(answer: str, chunks: list[RetrievedChunk]) -> ConfidenceResult:
    if not chunks:
        return ConfidenceResult(score=0.0, label="Low", components={
            "retrieval_similarity": 0.0, "source_agreement": 0.0, "lexical_semantic_grounding": 0.0,
        })

    # 1. retrieval similarity -- averaged over ALL chunks, with missing
    # dense scores imputed rather than dropped (see docstring above).
    retrieval_similarity = sum(_chunk_similarity_estimate(c) for c in chunks) / len(chunks)
    retrieval_similarity = max(0.0, min(1.0, retrieval_similarity))

    # 2. source agreement -- a single matching document still earns
    # solid credit (0.6); additional distinct documents add on top of
    # that, rather than being required just to reach a baseline.
    distinct_docs = len({c.document_id for c in chunks})
    if distinct_docs <= 1:
        source_agreement = 0.6
    else:
        source_agreement = min(1.0, 0.6 + 0.2 * (distinct_docs - 1))

    # 3. lexical/semantic grounding: token overlap between answer and context
    answer_tokens = _tokens(answer)
    context_tokens: set[str] = set()
    for c in chunks:
        context_tokens |= _tokens(c.text)
    if answer_tokens:
        overlap = len(answer_tokens & context_tokens) / len(answer_tokens)
    else:
        overlap = 0.0
    lexical_semantic_grounding = overlap

    score = (
        WEIGHTS["retrieval_similarity"] * retrieval_similarity
        + WEIGHTS["source_agreement"] * source_agreement
        + WEIGHTS["lexical_semantic_grounding"] * lexical_semantic_grounding
    )
    score = round(max(0.0, min(1.0, score)), 4)

    return ConfidenceResult(
        score=score,
        label=_label(score),
        components={
            "retrieval_similarity": round(retrieval_similarity, 4),
            "source_agreement": round(source_agreement, 4),
            "lexical_semantic_grounding": round(lexical_semantic_grounding, 4),
        },
    )