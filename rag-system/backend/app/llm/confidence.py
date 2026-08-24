"""
confidence.py

A CUSTOM confidence score -- explicitly not the LLM's self-reported
confidence, because models are known to be overconfident and their
stated confidence doesn't reliably track actual grounding. Instead we
blend three independently-measurable signals:

1. retrieval_similarity: mean of the top chunks' dense cosine scores.
   High => the query has strong semantic matches in the KB at all.
2. source_agreement: how many *distinct documents* (not just chunks)
   contributed to the top-k context. A claim triangulated across
   multiple independent sources is more trustworthy than one repeated
   from a single doc's neighboring chunks.
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
import re

from app.retrieval.hybrid import RetrievedChunk

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
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _label(score: float) -> str:
    if score >= 0.66:
        return "High"
    if score >= 0.35:
        return "Medium"
    return "Low"


def compute_confidence(answer: str, chunks: list[RetrievedChunk]) -> ConfidenceResult:
    if not chunks:
        return ConfidenceResult(score=0.0, label="Low", components={
            "retrieval_similarity": 0.0, "source_agreement": 0.0, "lexical_semantic_grounding": 0.0,
        })

    # 1. retrieval similarity (dense cosine scores are already 0..1-ish for normalized embeddings)
    dense_scores = [c.dense_score for c in chunks if c.dense_score is not None]
    retrieval_similarity = sum(dense_scores) / len(dense_scores) if dense_scores else 0.0
    retrieval_similarity = max(0.0, min(1.0, retrieval_similarity))

    # 2. source agreement: distinct documents represented, normalized
    distinct_docs = len({c.document_id for c in chunks})
    source_agreement = min(1.0, distinct_docs / 3.0)  # 3+ independent sources => full credit

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
