"""Retrieval module — vector, BM25, hybrid search and parent-document recall."""

from src.retrieval.retriever import VectorRetriever, retriever
from src.retrieval.bm25 import BM25Retriever, bm25_retriever
from src.retrieval.hybrid import (
    hybrid_search,
    parent_document_recall,
    rag_retrieve,
)

__all__ = [
    "VectorRetriever",
    "retriever",
    "BM25Retriever",
    "bm25_retriever",
    "hybrid_search",
    "parent_document_recall",
    "rag_retrieve",
]
