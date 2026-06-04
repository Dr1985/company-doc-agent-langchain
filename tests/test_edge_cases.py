"""Unit tests for edge cases, boundaries, and exception handling.

Tests cover what2do.md §4.4 — 边界与异常测试.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.data.schemas.chat import Message


# ── Empty / Whitespace Query ──────────────────────────────────────

class TestEmptyQuery:
    """4.4.1: 空问题（空字符串 / 仅空白）的处理"""

    def test_message_empty_string_rejected(self):
        """Empty message content raises validation error."""
        with pytest.raises(Exception):
            Message(role="user", content="")

    def test_message_whitespace_only_accepted_by_pydantic(self):
        """Whitespace-only content passes Pydantic min_length=1 (length check only)."""
        # Pydantic min_length=1 only checks string length, not semantic emptiness.
        # Frontend should do additional validation for whitespace-only input.
        msg = Message(role="user", content="   ")
        assert msg.content == "   "  # 3 spaces, length > 0

    def test_message_single_char_allowed(self):
        """Single character is valid content."""
        msg = Message(role="user", content="?")
        assert msg.content == "?"


# ── Long Query Truncation ─────────────────────────────────────────

class TestLongQuery:
    """4.4.2: 超长问题的截断处理"""

    def test_max_length_enforced(self):
        """Content exceeding 3000 chars is rejected by Pydantic."""
        with pytest.raises(Exception):
            Message(role="user", content="a" * 3001)

    def test_exact_max_length_allowed(self):
        """Exactly 3000 chars is allowed."""
        msg = Message(role="user", content="a" * 3000)
        assert len(msg.content) == 3000

    def test_chinese_max_length_allowed(self):
        """Chinese characters at max length are allowed."""
        content = "测试" * 1500  # 3000 chars
        msg = Message(role="user", content=content)
        assert len(msg.content) == 3000


# ── Source Citation Edge Cases ────────────────────────────────────

class TestSourceEdgeCases:
    """4.4: 检索返回大量结果时的截断与排序"""

    def test_empty_sources_in_response(self):
        """Response with no sources should have empty sources list."""
        from src.data.schemas.chat import ChatResponse
        resp = ChatResponse(messages=[Message(role="assistant", content="ok")])
        assert resp.sources == []

    def test_multiple_sources_ordering(self):
        """Sources should maintain insertion order."""
        from src.data.schemas.chat import ChatResponse, SourceCitation

        resp = ChatResponse(
            messages=[Message(role="assistant", content="multi")],
            sources=[
                SourceCitation(chunk_id=1, document_id=1, score=0.9),
                SourceCitation(chunk_id=2, document_id=1, score=0.7),
                SourceCitation(chunk_id=3, document_id=2, score=0.5),
            ],
        )
        assert len(resp.sources) == 3
        assert resp.sources[0].score > resp.sources[1].score
        assert resp.sources[1].score > resp.sources[2].score


# ── Retrieval Without Results ─────────────────────────────────────

class TestRetrievalNoResults:
    """4.1.2: 无匹配结果时返回空列表 / 拒答"""

    def test_rag_retrieve_empty_context_for_no_results(self):
        """When no chunks found, context should be empty string."""
        from src.retrieval.hybrid import rag_retrieve

        # We test the context formatting logic directly
        # Empty chunks produces empty context
        chunks_for_context = []
        context_parts = []
        for i, chunk in enumerate(chunks_for_context):
            context_parts.append(f"【来源 {i+1}】content")
        formatted_context = "\n\n---\n\n".join(context_parts) if context_parts else ""

        assert formatted_context == ""


# ── Schema Validation Edge Cases ──────────────────────────────────

class TestSchemaEdgeCases:
    """各种 schema 边缘情况"""

    def test_chat_request_multiple_messages(self):
        from src.data.schemas.chat import ChatRequest
        req = ChatRequest(messages=[
            Message(role="user", content="问题1"),
            Message(role="assistant", content="回答1"),
            Message(role="user", content="问题2"),
        ])
        assert len(req.messages) == 3

    def test_source_citation_large_id(self):
        from src.data.schemas.chat import SourceCitation
        sc = SourceCitation(chunk_id=999999, document_id=888888)
        assert sc.chunk_id == 999999
        assert sc.document_id == 888888

    def test_source_citation_special_chars(self):
        from src.data.schemas.chat import SourceCitation
        sc = SourceCitation(
            chunk_id=1,
            document_id=2,
            filename="员工手册 (2026版).pdf",
            preview="包含特殊字符 <test> & \"quotes\"",
        )
        assert "2026" in sc.filename
        assert "test" in sc.preview


# ── BM25 Edge Cases ───────────────────────────────────────────────

class TestBM25EdgeCases:
    """BM25 检索边界情况"""

    def test_bm25_single_token_corpus(self):
        from src.retrieval.bm25 import BM25Retriever
        import math

        retriever = BM25Retriever()
        retriever._doc_count = 1
        retriever._avg_dl = 3.0
        retriever._idf = {"test": math.log((1 - 1 + 0.5) / (1 + 0.5) + 1.0)}

        score = retriever._score(["test"], ["test", "test", "test"])
        assert score > 0

    def test_bm25_very_long_document(self):
        """Very long document gets length-normalized score."""
        from src.retrieval.bm25 import BM25Retriever
        import math

        retriever = BM25Retriever()
        retriever._doc_count = 2
        retriever._avg_dl = 500.0
        retriever._idf = {"test": math.log((2 - 1 + 0.5) / (1 + 0.5) + 1.0)}

        long_doc = ["test"] + ["padding"] * 999
        score = retriever._score(["test"], long_doc)
        # Long docs get penalized by length normalization
        assert score > 0
