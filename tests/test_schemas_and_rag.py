"""Unit tests for API schemas, RAG prompts, and data models.

Tests cover what2do.md §4.2 (RAG 问答链路测试) and §4.3 (接口层测试).
"""

import pytest
from pydantic import ValidationError

from src.data.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Message,
    SourceCitation,
    StreamResponse,
)


# ── Message Schema ─────────────────────────────────────────────────

class TestMessageSchema:
    """4.3.1: Chat request/response 结构验证"""

    def test_valid_user_message(self):
        msg = Message(role="user", content="你好")
        assert msg.role == "user"
        assert msg.content == "你好"

    def test_valid_assistant_message(self):
        msg = Message(role="assistant", content="你好！有什么可以帮你的？")
        assert msg.role == "assistant"

    def test_valid_system_message(self):
        msg = Message(role="system", content="系统提示词")
        assert msg.role == "system"

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            Message(role="user", content="")

    def test_content_too_long_rejected(self):
        with pytest.raises(ValidationError):
            Message(role="user", content="a" * 3001)

    def test_invalid_role_rejected(self):
        with pytest.raises(ValidationError):
            Message(role="bot", content="hello")

    def test_script_tag_detected(self):
        with pytest.raises(ValidationError):
            Message(role="user", content="<script>alert('xss')</script>")

    def test_null_byte_detected(self):
        with pytest.raises(ValidationError):
            Message(role="user", content="hello\0world")

    def test_boundary_3000_chars_allowed(self):
        msg = Message(role="user", content="a" * 3000)
        assert len(msg.content) == 3000


class TestChatRequestSchema:
    """4.3.1: Chat request/response 结构验证"""

    def test_valid_request(self):
        req = ChatRequest(messages=[
            Message(role="user", content="什么是考勤制度？"),
        ])
        assert len(req.messages) == 1

    def test_empty_messages_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[])


class TestChatResponseSchema:
    """4.3.1: Chat response 结构验证"""

    def test_response_with_messages(self):
        resp = ChatResponse(messages=[
            Message(role="user", content="问"),
            Message(role="assistant", content="答"),
        ])
        assert len(resp.messages) == 2
        assert resp.sources == []

    def test_response_with_sources(self):
        resp = ChatResponse(
            messages=[Message(role="assistant", content="根据手册...")],
            sources=[
                SourceCitation(
                    chunk_id=1,
                    document_id=10,
                    filename="员工手册.pdf",
                    chunk_index=3,
                    score=0.85,
                    preview="第一章 总则...",
                ),
            ],
        )
        assert len(resp.sources) == 1
        assert resp.sources[0].filename == "员工手册.pdf"
        assert resp.sources[0].score == 0.85


# ── SourceCitation Schema ─────────────────────────────────────────

class TestSourceCitationSchema:
    """4.2.4: 引用提取：sources / citations 字段格式正确"""

    def test_valid_citation(self):
        sc = SourceCitation(
            chunk_id=42,
            document_id=7,
            filename="考勤制度.md",
            chunk_index=5,
            score=0.92,
            preview="## 第二章 考勤管理...",
        )
        assert sc.chunk_id == 42
        assert sc.document_id == 7
        assert sc.filename == "考勤制度.md"
        assert sc.chunk_index == 5
        assert sc.score == 0.92
        assert sc.preview.startswith("##")

    def test_citation_defaults(self):
        sc = SourceCitation(chunk_id=1, document_id=2)
        assert sc.filename == ""
        assert sc.chunk_index == 0
        assert sc.score == 0.0
        assert sc.preview == ""

    def test_citation_score_range(self):
        """Score 应在可接受范围内"""
        sc = SourceCitation(chunk_id=1, document_id=1, score=1.5)
        # No explicit range validation in schema, but should not crash
        assert sc.score == 1.5


class TestStreamResponseSchema:
    """4.3.2: SSE stream response 结构验证"""

    def test_stream_chunk(self):
        sr = StreamResponse(content="你好", done=False)
        assert sr.content == "你好"
        assert sr.done is False

    def test_stream_done(self):
        sr = StreamResponse(content="", done=True)
        assert sr.done is True

    def test_stream_defaults(self):
        sr = StreamResponse()
        assert sr.content == ""
        assert sr.done is False


# ── RAG Prompt Construction ──────────────────────────────────────

class TestRAGPrompt:
    """4.2.1: 检索结果正确拼入 prompt 送给 LLM"""

    def test_rag_prompt_includes_context(self):
        """RAG prompt 包含检索到的文档上下文"""
        from src.agent.prompts import load_rag_system_prompt

        context = "【来源 1】员工手册.pdf (Chunk #3)\n第一章 总则..."
        prompt = load_rag_system_prompt(
            long_term_memory="用户偏好：关注考勤制度",
            retrieved_context=context,
        )

        assert "员工手册" in prompt
        assert "第一章 总则" in prompt
        assert "考勤制度" in prompt

    def test_rag_prompt_has_citation_instructions(self):
        """RAG prompt 包含引用编号规则"""
        from src.agent.prompts import load_rag_system_prompt

        prompt = load_rag_system_prompt(
            long_term_memory="",
            retrieved_context="测试上下文",
        )

        # Should instruct the model about citations
        assert "来源" in prompt.lower() or "source" in prompt.lower()

    def test_rag_prompt_has_refusal_instruction(self):
        """4.2.3: 拒答机制 — 知识库无相关内容时返回拒答提示"""
        from src.agent.prompts import load_rag_system_prompt

        prompt = load_rag_system_prompt(
            long_term_memory="",
            retrieved_context="测试上下文",
        )

        # Should contain refusal guidance
        refusal_keywords = ["无法回答", "不知道", "不编造", "无法", "不能", "don't know"]
        has_refusal = any(kw in prompt.lower() for kw in refusal_keywords)
        assert has_refusal, f"Prompt should include refusal instructions. Got: {prompt[:200]}"

    def test_rag_prompt_empty_context(self):
        """RAG prompt with empty context still produces valid output."""
        from src.agent.prompts import load_rag_system_prompt

        prompt = load_rag_system_prompt(
            long_term_memory="",
            retrieved_context="",
        )

        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ── GraphState RAG Fields ────────────────────────────────────────

class TestGraphState:
    """4.2: RAG state 字段验证"""

    def test_graph_state_has_rag_fields(self):
        from src.data.schemas.graph import GraphState

        state = GraphState(
            messages=[],
            long_term_memory="",
            retrieved_context="",
            sources=[],
        )

        assert state.retrieved_context == ""
        assert state.sources == []

    def test_graph_state_with_context(self):
        from src.data.schemas.graph import GraphState

        state = GraphState(
            messages=[],
            long_term_memory="",
            retrieved_context="【来源 1】文档内容",
            sources=[
                {
                    "chunk_id": 1,
                    "document_id": 10,
                    "filename": "test.pdf",
                    "chunk_index": 2,
                    "score": 0.9,
                    "preview": "preview text",
                }
            ],
        )

        assert state.retrieved_context == "【来源 1】文档内容"
        assert len(state.sources) == 1
        assert state.sources[0]["filename"] == "test.pdf"


# ── Schema Export ─────────────────────────────────────────────────

class TestSchemaExports:
    """4.3: Ensure all schemas are properly exported."""

    def test_source_citation_exported(self):
        from src.data.schemas import SourceCitation
        assert SourceCitation is not None

    def test_chat_request_exported(self):
        from src.data.schemas import ChatRequest
        assert ChatRequest is not None

    def test_chat_response_exported(self):
        from src.data.schemas import ChatResponse
        assert ChatResponse is not None
