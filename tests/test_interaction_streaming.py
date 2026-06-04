import asyncio
import importlib
import json
import sys
import types
from contextlib import nullcontext
from dataclasses import dataclass

from src.data.schemas.chat import ChatRequest, Message


MODULES_TO_RESET = [
    "src.interface.interaction",
    "src.interface.auth",
    "src.config.settings",
    "src.agent.workflow",
    "src.system.rate_limit",
    "src.system.logs",
    "src.system.telemetry",
    "src.system.tracing",
    "src.data.models.session",
]


def reset_modules():
    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)


async def collect_stream_chunks(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return chunks


def load_interaction_module(monkeypatch, stream_chunks):
    trace_updates = []

    fake_auth_module = types.ModuleType("src.interface.auth")
    fake_auth_module.get_current_session = lambda: None

    fake_settings_module = types.ModuleType("src.config.settings")
    fake_settings_module.settings = types.SimpleNamespace(
        RATE_LIMIT_ENDPOINTS={
            "chat": ["10/minute"],
            "chat_stream": ["10/minute"],
            "messages": ["10/minute"],
        },
        ENVIRONMENT=types.SimpleNamespace(value="test"),
        ACTIVE_LLM_PROVIDER=types.SimpleNamespace(value="deepseek"),
        DEFAULT_LLM_MODEL="deepseek-chat",
    )

    fake_workflow_module = types.ModuleType("src.agent.workflow")

    class FakeLLM:
        def get_name(self):
            return "deepseek-chat"

    class FakeLLMService:
        def get_llm(self):
            return FakeLLM()

    class FakeLangGraphAgent:
        def __init__(self):
            self.llm_service = FakeLLMService()

        async def get_stream_response(self, messages, session_id, user_id=None, document_ids=None):
            for chunk in stream_chunks:
                yield chunk

        async def get_response(self, messages, session_id, user_id=None, document_ids=None):
            return {"messages": [], "sources": []}

        async def clear_chat_history(self, session_id):
            return None

    fake_workflow_module.LangGraphAgent = FakeLangGraphAgent

    fake_rate_limit_module = types.ModuleType("src.system.rate_limit")

    class FakeLimiter:
        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    fake_rate_limit_module.limiter = FakeLimiter()

    fake_logs_module = types.ModuleType("src.system.logs")
    fake_logs_module.logger = types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    fake_telemetry_module = types.ModuleType("src.system.telemetry")

    class FakeStreamMetric:
        def labels(self, **kwargs):
            return self

        def time(self):
            return nullcontext()

    fake_telemetry_module.llm_stream_duration_seconds = FakeStreamMetric()

    fake_tracing_module = types.ModuleType("src.system.tracing")
    fake_tracing_module.add_score = lambda *a, **k: None
    fake_tracing_module.capture_current_trace_context = lambda: None
    fake_tracing_module.update_current_trace = lambda **kwargs: trace_updates.append(kwargs)

    fake_session_module = types.ModuleType("src.data.models.session")

    @dataclass
    class Session:
        id: str
        user_id: int

    fake_session_module.Session = Session

    reset_modules()
    monkeypatch.setitem(sys.modules, "src.interface.auth", fake_auth_module)
    monkeypatch.setitem(sys.modules, "src.config.settings", fake_settings_module)
    monkeypatch.setitem(sys.modules, "src.agent.workflow", fake_workflow_module)
    monkeypatch.setitem(sys.modules, "src.system.rate_limit", fake_rate_limit_module)
    monkeypatch.setitem(sys.modules, "src.system.logs", fake_logs_module)
    monkeypatch.setitem(sys.modules, "src.system.telemetry", fake_telemetry_module)
    monkeypatch.setitem(sys.modules, "src.system.tracing", fake_tracing_module)
    monkeypatch.setitem(sys.modules, "src.data.models.session", fake_session_module)

    interaction_module = importlib.import_module("src.interface.interaction")
    return interaction_module, trace_updates


def test_chat_stream_passes_sources_events_without_appending_them_to_content(monkeypatch):
    interaction_module, trace_updates = load_interaction_module(
        monkeypatch,
        ["你好", 'data: {"type": "sources", "sources": []}\n\n'],
    )

    response = asyncio.run(
        interaction_module.chat_stream(
            request=None,
            chat_request=ChatRequest(messages=[Message(role="user", content="你好")]),
            session=interaction_module.Session(id="session-1", user_id=2),
        )
    )
    chunks = asyncio.run(collect_stream_chunks(response))
    payloads = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]

    assert payloads == [
        {"content": "你好", "done": False},
        {"type": "sources", "sources": []},
        {"content": "", "done": True},
    ]
    assert any(call.get("output") == {"assistant_message": "你好"} for call in trace_updates)


def test_chat_stream_keeps_non_json_data_prefixed_chunks_as_normal_text(monkeypatch):
    interaction_module, _ = load_interaction_module(monkeypatch, ["data: not-json"])

    response = asyncio.run(
        interaction_module.chat_stream(
            request=None,
            chat_request=ChatRequest(messages=[Message(role="user", content="测试")]),
            session=interaction_module.Session(id="session-2", user_id=2),
        )
    )
    chunks = asyncio.run(collect_stream_chunks(response))
    payloads = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]

    assert payloads == [
        {"content": "data: not-json", "done": False},
        {"content": "", "done": True},
    ]

