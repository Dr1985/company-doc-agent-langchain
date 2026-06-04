import importlib
import sys

from langchain_core.messages import HumanMessage

from src.data.schemas.chat import Message


ENV_KEYS = [
    "APP_ENV",
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "LONG_TERM_MEMORY_ENABLED",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_HOST",
    "LANGFUSE_TRACING_ENABLED",
]

MODULES_TO_RESET = [
    "src.utils.graph",
    "src.config.settings",
    "src.system.logs",
    "src.system.tracing",
]


class DeepSeekLikeLLM:
    model_name = "deepseek-chat"

    def get_num_tokens_from_messages(self, messages):
        raise NotImplementedError(
            "get_num_tokens_from_messages() is not presently implemented for model deepseek-chat"
        )


def load_graph_module(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("LONG_TERM_MEMORY_ENABLED", "false")

    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)

    return importlib.import_module("src.utils.graph")


def test_prepare_messages_falls_back_when_native_token_counting_is_unsupported(monkeypatch):
    graph_module = load_graph_module(monkeypatch)
    monkeypatch.setattr(graph_module.settings, "MAX_TOKENS", 1000)

    messages = [Message(role="user", content="你好，你是谁？")]
    prepared_messages = graph_module.prepare_messages(
        messages=messages,
        llm=DeepSeekLikeLLM(),
        system_prompt="你是一个有帮助的助手。",
    )

    assert [message.role for message in prepared_messages] == ["system", "user"]
    assert prepared_messages[0].content == "你是一个有帮助的助手。"
    assert prepared_messages[1].content == "你好，你是谁？"


def test_prepare_messages_accepts_langchain_human_message(monkeypatch):
    graph_module = load_graph_module(monkeypatch)
    monkeypatch.setattr(graph_module.settings, "MAX_TOKENS", 1000)

    prepared_messages = graph_module.prepare_messages(
        messages=[HumanMessage(content="你好，你是谁？")],
        llm=DeepSeekLikeLLM(),
        system_prompt="你是一个有帮助的助手。",
    )

    assert [message.role for message in prepared_messages] == ["system", "user"]
    assert prepared_messages[1].content == "你好，你是谁？"


