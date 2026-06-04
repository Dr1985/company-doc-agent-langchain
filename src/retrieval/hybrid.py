"""Hybrid retrieval combining vector similarity and BM25 keyword search.

Also provides parent-document recall: when a chunk is matched, fetch
adjacent chunks or the full document for richer context.
"""

from collections import defaultdict
from typing import List, Optional

from sqlmodel import Session as DBSession, select

from src.data.db_manager import db_manager
from src.data.models.document import Document, DocumentChunk
from src.data.schemas.document import ChunkResult
from src.retrieval.bm25 import bm25_retriever
from src.retrieval.retriever import retriever as vector_retriever
from src.system.logs import logger

# ── Constants ────────────────────────────────────────────────────

RRF_K = 60  # Reciprocal Rank Fusion constant
DEFAULT_TOP_K = 5
PARENT_WINDOW = 2  # adjacent chunks on each side for parent-doc recall


# ── Hybrid Search ────────────────────────────────────────────────

async def hybrid_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    document_ids: Optional[List[int]] = None,
    vector_weight: float = 0.6,
) -> List[ChunkResult]:
    """Combine vector and BM25 results using Reciprocal Rank Fusion.

    Args:
        query: Search query.
        top_k: Number of final results to return.
        document_ids: Filter by document IDs.
        vector_weight: Weight of vector results vs BM25 (0-1).

    Returns:
        Fused and re-ranked list of ChunkResult.
    """
    # Run both searches in parallel (vector is async, BM25 is sync)
    vector_results = await vector_retriever.search(
        query=query,
        top_k=top_k * 2,  # oversample for fusion
        document_ids=document_ids,
    )
    bm25_results = bm25_retriever.search(
        query=query,
        top_k=top_k * 2,
        document_ids=document_ids,
    )

    # Reciprocal Rank Fusion
    fused: dict[int, tuple[float, ChunkResult]] = {}

    # Score vector results
    for rank, r in enumerate(vector_results):
        score = vector_weight / (RRF_K + rank + 1)
        if r.chunk_id in fused:
            fused[r.chunk_id] = (fused[r.chunk_id][0] + score, r)
        else:
            fused[r.chunk_id] = (score, r)

    # Score BM25 results
    bm25_weight = 1.0 - vector_weight
    for rank, r in enumerate(bm25_results):
        score = bm25_weight / (RRF_K + rank + 1)
        if r.chunk_id in fused:
            fused[r.chunk_id] = (fused[r.chunk_id][0] + score, fused[r.chunk_id][1])
        else:
            fused[r.chunk_id] = (score, r)

    # Sort by fused score and return top_k
    sorted_items = sorted(fused.values(), key=lambda x: x[0], reverse=True)

    results = []
    for score, chunk in sorted_items[:top_k]:
        chunk.score = round(score, 4)
        results.append(chunk)

    logger.info(
        "hybrid_search_completed",
        query_length=len(query),
        vector_count=len(vector_results),
        bm25_count=len(bm25_results),
        fused_count=len(results),
    )
    return results


# ── Parent Document Recall ───────────────────────────────────────

async def parent_document_recall(
    chunk_results: List[ChunkResult],
    window: int = PARENT_WINDOW,
) -> List[ChunkResult]:
    """Expand each chunk result with adjacent chunks for richer context.

    For each retrieved chunk, fetch ``window`` chunks before and after
    from the same document, de-duplicate, and return as additional
    context chunks tagged with ``score=0``.
    """
    if not chunk_results:
        return []

    # Group by document_id, track which chunk indices we need
    doc_chunks: dict[int, set[int]] = {}
    for r in chunk_results:
        if r.document_id not in doc_chunks:
            doc_chunks[r.document_id] = set()
        doc_chunks[r.document_id].add(r.chunk_index)

    # Expand the requested indices
    expanded: dict[int, set[int]] = {}
    for doc_id, indices in doc_chunks.items():
        all_indices = set(indices)
        for idx in indices:
            for delta in range(-window, window + 1):
                if delta == 0:
                    continue
                all_indices.add(idx + delta)
        expanded[doc_id] = all_indices

    # Fetch parent chunks from DB
    parent_results: List[ChunkResult] = []
    with DBSession(db_manager.engine) as session:
        for doc_id, indices in expanded.items():
            # Fetch document filename
            doc = session.get(Document, doc_id)
            filename = doc.filename if doc else ""

            # Fetch chunks
            if indices:
                all_idx = sorted(indices)
                # Batch query for efficiency
                chunks = session.exec(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == doc_id)
                    .where(DocumentChunk.chunk_index.in_(all_idx))
                ).all()

                for chunk in chunks:
                    parent_results.append(ChunkResult(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        filename=filename,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        score=0.0,  # parent chunks have score 0
                    ))

    logger.info(
        "parent_document_recall_completed",
        input_chunks=len(chunk_results),
        parent_chunks=len(parent_results),
        window=window,
    )
    return parent_results


# ── Full RAG Retrieval Pipeline ──────────────────────────────────

async def rag_retrieve(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    document_ids: Optional[List[int]] = None,
    include_parent_docs: bool = True,
) -> dict:
    """Complete RAG retrieval pipeline: hybrid search + parent document recall.

    Args:
        query: User query.
        top_k: Number of primary results.
        document_ids: Optional document filter.
        include_parent_docs: Whether to fetch parent document context.

    Returns:
        Dict with keys:
        - ``chunks``: primary hybrid search results
        - ``parent_chunks``: adjacent context chunks (if enabled)
        - ``context``: formatted string for LLM prompt
        - ``sources``: citation metadata for the response
    """
    # Step 1: Hybrid search
    chunks = await hybrid_search(
        query=query,
        top_k=top_k,
        document_ids=document_ids,
    )

    # Step 2: Parent document recall
    parent_chunks = []
    if include_parent_docs and chunks:
        parent_chunks = await parent_document_recall(chunks)

    # Step 3: Build formatted context for LLM
    # Build a mapping: (doc_id, chunk_index) -> list of adjacent parent chunk contents
    parent_by_doc_chunk: dict[tuple[int, int], list[str]] = defaultdict(list)
    for pc in parent_chunks:
        parent_by_doc_chunk[(pc.document_id, pc.chunk_index)].append(pc.content)

    context_parts = []
    for i, chunk in enumerate(chunks):
        doc_label = chunk.filename or f"文档{chunk.document_id}"

        # Collect parent context around this primary chunk
        surrounding_parts = []
        doc_id = chunk.document_id
        chunk_idx = chunk.chunk_index
        for delta in range(-PARENT_WINDOW, PARENT_WINDOW + 1):
            if delta == 0:
                continue
            adj_contents = parent_by_doc_chunk.get((doc_id, chunk_idx + delta), [])
            for adj_content in adj_contents:
                surrounding_parts.append(adj_content)

        surrounding = "\n".join(surrounding_parts)
        if surrounding:
            # Place surrounding context before the primary chunk so the LLM sees it first
            context_parts.append(
                f"【{i + 1}】{doc_label} (Chunk #{chunk.chunk_index})\n\n{surrounding}\n\n{chunk.content}"
            )
        else:
            context_parts.append(
                f"【{i + 1}】{doc_label} (Chunk #{chunk.chunk_index})\n{chunk.content}"
            )
    formatted_context = "\n\n---\n\n".join(context_parts) if context_parts else ""

    # Step 4: Build citation sources (only primary results)
    sources = []
    for chunk in chunks:
        sources.append({
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "filename": chunk.filename,
            "chunk_index": chunk.chunk_index,
            "score": chunk.score,
            "preview": chunk.content[:300],
        })

    logger.info(
        "rag_retrieve_completed",
        query_length=len(query),
        primary_chunks=len(chunks),
        parent_chunks=len(parent_chunks),
        has_context=bool(formatted_context),
    )

    return {
        "chunks": chunks,
        "parent_chunks": parent_chunks,
        "context": formatted_context,
        "sources": sources,
    }
