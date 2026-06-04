"""Vector retrieval service using pgvector cosine similarity.

Given a query, embeds it with Qwen and finds the most similar
document chunks via ``<=>`` (cosine distance) in PostgreSQL.
"""

from typing import List, Optional

from sqlalchemy import text
from sqlmodel import Session as DBSession

from src.data.db_manager import db_manager
from src.data.models.document import Document, DocumentChunk
from src.data.schemas.document import ChunkResult
from src.embedding.qwen_embedding import qwen_embedding
from src.system.logs import logger


class VectorRetriever:
    """Semantic search over document chunks using pgvector."""

    async def search(
        self,
        query: str,
        top_k: int = 5,
        document_ids: Optional[List[int]] = None,
    ) -> List[ChunkResult]:
        """Search for chunks similar to the query.

        Args:
            query: Natural-language query string.
            top_k: Number of results to return (1‑50).
            document_ids: Optional filter — only search within these docs.

        Returns:
            List of ``ChunkResult`` ordered by descending similarity.
        """
        if not qwen_embedding.available:
            logger.warning("retrieval_embedding_unavailable")
            return []

        # 1. Embed the query
        query_vector = await qwen_embedding.embed_query(query)

        # 2. Build raw SQL with optional document filter
        dims = qwen_embedding.dims
        filter_clause = ""
        params: dict = {
            "query_vec": str(query_vector),
            "limit": top_k,
        }
        if document_ids:
            placeholders = ", ".join(str(d) for d in document_ids)
            filter_clause = f"AND c.document_id IN ({placeholders})"

        sql = text(f"""
            SELECT
                c.id          AS chunk_id,
                c.document_id,
                d.filename,
                c.chunk_index,
                c.content,
                1 - (c.embedding <=> CAST(:query_vec AS vector({dims}))) AS score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.embedding IS NOT NULL
              {filter_clause}
            ORDER BY c.embedding <=> CAST(:query_vec AS vector({dims}))
            LIMIT :limit
        """)

        # 3. Execute
        with DBSession(db_manager.engine) as session:
            result = session.execute(sql, params=params)
            rows = result.fetchall()

        results = [
            ChunkResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                filename=r.filename,
                chunk_index=r.chunk_index,
                content=r.content,
                score=float(r.score),
            )
            for r in rows
        ]

        logger.info(
            "vector_search_completed",
            query_length=len(query),
            top_k=top_k,
            results=len(results),
            filtered=bool(document_ids),
        )
        return results


# Singleton
retriever = VectorRetriever()
