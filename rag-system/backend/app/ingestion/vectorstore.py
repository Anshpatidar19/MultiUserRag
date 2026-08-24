"""
vectorstore.py

Thin wrapper around Pinecone that makes multi-tenancy structural rather
than a filter someone could forget to apply: every call requires a
`user_id` and routes it straight into `namespace=user_id`. Pinecone
namespaces are physically separate index partitions, so a query issued
against namespace A cannot return vectors from namespace B even if the
caller's `top_k` were huge -- unlike a metadata filter, which is only as
safe as remembering to include it on every single query.

Chunk IDs are deterministic (`{document_id}::{chunk_index}`) so
re-uploading the same document overwrites its old vectors instead of
duplicating them (upsert semantics), which is what guards against the
"duplicate upload -> duplicate vectors" failure mode called out in the
spec.
"""

from functools import lru_cache
from pinecone import Pinecone, ServerlessSpec

from app.config import get_settings

settings = get_settings()


@lru_cache
def _get_index():
    pc = Pinecone(api_key=settings.pinecone_api_key)
    existing = [i["name"] for i in pc.list_indexes()]
    if settings.pinecone_index_name not in existing:
        pc.create_index(
            name=settings.pinecone_index_name,
            dimension=settings.embedding_dim,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region=settings.pinecone_environment),
        )
    return pc.Index(settings.pinecone_index_name)


def upsert_chunks(
    user_id: str,
    document_id: str,
    chunks: list[str],
    embeddings: list[list[float]],
    source_name: str,
) -> int:
    index = _get_index()
    vectors = [
        {
            "id": f"{document_id}::{i}",
            "values": emb,
            "metadata": {
                "document_id": document_id,
                "chunk_index": i,
                "text": chunk,
                "source_name": source_name,
            },
        }
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    index.upsert(vectors=vectors, namespace=user_id)
    return len(vectors)


def delete_document(user_id: str, document_id: str) -> None:
    index = _get_index()
    # Delete by metadata filter so we don't need to know the exact chunk
    # count up front.
    index.delete(namespace=user_id, filter={"document_id": {"$eq": document_id}})


def query(user_id: str, query_embedding: list[float], top_k: int) -> list[dict]:
    """
    ALWAYS scoped to namespace=user_id. There is no code path in this
    module that allows querying across namespaces -- this is the hard
    isolation boundary described in the spec, not an optimization.
    """
    index = _get_index()
    result = index.query(
        namespace=user_id,
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
    )
    return [
        {
            "id": match["id"],
            "score": match["score"],
            "document_id": match["metadata"]["document_id"],
            "chunk_index": match["metadata"]["chunk_index"],
            "text": match["metadata"]["text"],
            "source_name": match["metadata"]["source_name"],
        }
        for match in result.get("matches", [])
    ]
