"""BM25 keyword-based retrieval over document chunks.

Provides lexical search as a complement to vector similarity search,
enabling hybrid retrieval that combines semantic and keyword matching.
"""

import math
from typing import List, Optional

from sqlmodel import Session as DBSession

from src.data.db_manager import db_manager
from src.data.models.document import DocumentChunk
from src.data.schemas.document import ChunkResult
from src.system.logs import logger


class BM25Retriever:
    """Keyword search using the BM25 ranking function.

    Builds an in-memory index from all document chunks and scores
    queries against chunks using term-frequency and inverse-document-frequency.
    """

    # BM25 hyper-parameters
    k1: float = 1.5
    b: float = 0.75

    def __init__(self):
        self._corpus: List[dict] = []  # [{id, doc_id, filename, idx, content, tokens}]
        self._doc_count: int = 0
        self._avg_dl: float = 0.0
        self._idf: dict[str, float] = {}

    # ── tokenisation ──────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Simple whitespace + punctuation tokenizer for Chinese/English."""
        import re
        # Keep Chinese characters, letters, digits; split on everything else
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())
        return tokens

    # ── index building ────────────────────────────────────────────

    def _load_corpus(self, document_ids: Optional[List[int]] = None) -> None:
        """Load chunks from the database and build the in-memory index."""
        with DBSession(db_manager.engine) as session:
            query = session.query(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
            )
            if document_ids:
                query = query.filter(DocumentChunk.document_id.in_(document_ids))
            rows = query.all()

        self._corpus = []
        doc_lengths = []
        df: dict[str, int] = {}  # document frequency

        for row in rows:
            tokens = self._tokenize(row.content or "")
            self._corpus.append({
                "id": row.id,
                "document_id": row.document_id,
                "chunk_index": row.chunk_index,
                "content": row.content,
                "tokens": tokens,
            })
            doc_lengths.append(len(tokens))
            for token in set(tokens):
                df[token] = df.get(token, 0) + 1

        self._doc_count = len(self._corpus)
        self._avg_dl = sum(doc_lengths) / max(self._doc_count, 1)

        # Compute IDF
        self._idf = {}
        for token, freq in df.items():
            self._idf[token] = math.log(
                (self._doc_count - freq + 0.5) / (freq + 0.5) + 1.0
            )

        logger.info(
            "bm25_index_built",
            chunks=self._doc_count,
            vocab=len(self._idf),
            filtered=bool(document_ids),
        )

    # ── scoring ────────────────────────────────────────────────────

    def _score(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        """Compute BM25 score for a single document."""
        dl = len(doc_tokens)
        tf: dict[str, int] = {}
        for t in doc_tokens:
            tf[t] = tf.get(t, 0) + 1

        score = 0.0
        for token in set(query_tokens):
            idf = self._idf.get(token, 0.0)
            term_freq = tf.get(token, 0)
            numerator = term_freq * (self.k1 + 1)
            denominator = term_freq + self.k1 * (1 - self.b + self.b * dl / max(self._avg_dl, 1))
            score += idf * numerator / max(denominator, 1e-9)
        return score

    # ── public API ─────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        document_ids: Optional[List[int]] = None,
    ) -> List[ChunkResult]:
        """Search chunks by keyword relevance.

        Args:
            query: Natural-language query string.
            top_k: Number of results to return.
            document_ids: Optional filter — only search within these docs.

        Returns:
            List of ``ChunkResult`` ordered by descending BM25 score.
        """
        self._load_corpus(document_ids)

        if self._doc_count == 0:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Score every document
        scored = []
        for doc in self._corpus:
            s = self._score(query_tokens, doc["tokens"])
            if s > 0:
                scored.append((s, doc))

        # Sort by score descending, take top_k
        scored.sort(key=lambda x: x[0], reverse=True)

        # Normalize scores to [0, 1]
        max_score = scored[0][0] if scored else 1.0
        results = []
        for i, (score, doc) in enumerate(scored[:top_k]):
            results.append(ChunkResult(
                chunk_id=doc["id"],
                document_id=doc["document_id"],
                filename="",  # filled by caller if needed
                chunk_index=doc["chunk_index"],
                content=doc["content"][:512],
                score=round(score / max(max_score, 1e-9), 4),
            ))

        logger.info(
            "bm25_search_completed",
            query_length=len(query),
            top_k=top_k,
            results=len(results),
        )
        return results


# Singleton
bm25_retriever = BM25Retriever()
