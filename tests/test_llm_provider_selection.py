import asyncio
import importlib
import sys

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)


ENV_KEYS = [
    "APP_ENV",
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEFAULT_LLM_MODEL",
    "LONG_TERM_MEMORY_ENABLED",
    "LONG_TERM_MEMORY_PROVIDER",
    "LONG_TERM_MEMORY_MODEL",
    "LONG_TERM_MEMORY_EMBEDDER_PROVIDER",
    "LONG_TERM_MEMORY_EMBEDDER_API_KEY",
    "LONG_TERM_MEMORY_EMBEDDER_BASE_URL",
    "LONG_TERM_MEMORY_EMBEDDER_MODEL",
    "LONG_TERM_MEMORY_EMBEDDER_DIMS",
    "EVALUATION_LLM",
    "EVALUATION_BASE_URL",
    "EVALUATION_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_HOST",
    "LANGFUSE_TRACING_ENABLED",
    "LANGFUSE_SAMPLE_RATE",
    "LANGFUSE_FLUSH_AT",
    "LANGFUSE_FLUSH_INTERVAL",
]

MODULES_TO_RESET = [
    "src.services.llm_provider",
    "src.config.settings",
    "src.system.logs",
    "src.system.tracing",
]


def load_settings_and_provider(monkeypatch, **env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    # Prevent .env file from restoring values by mocking load_dotenv.
    # Some .env values (e.g. EVALUATION_BASE_URL="") are empty strings
    # that still prevent os.getenv() from falling back to defaults.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)

    settings_module = importlib.import_module("src.config.settings")
    provider_module = importlib.import_module("src.services.llm_provider")
    return settings_module, provider_module


def test_auto_selects_deepseek_when_only_deepseek_key_exists(monkeypatch):
    settings_module, provider_module = load_settings_and_provider(
        monkeypatch,
        APP_ENV="test",
        DEEPSEEK_API_KEY="deepseek-test-key",
        OPENAI_API_KEY=None,
    )

    settings = settings_module.settings

    assert settings.ACTIVE_LLM_PROVIDER == settings_module.LLMProvider.DEEPSEEK
    assert settings.DEFAULT_LLM_MODEL == "deepseek-chat"
    assert provider_module.LLMRegistry.get_all_names() == ["deepseek-chat"]
    assert settings.EVALUATION_BASE_URL == settings.DEEPSEEK_BASE_URL
    assert settings.LONG_TERM_MEMORY_AVAILABLE is False
    assert "embedder" in settings.LONG_TERM_MEMORY_DISABLED_REASON


def test_auto_prefers_openai_when_both_provider_keys_exist(monkeypatch):
    settings_module, provider_module = load_settings_and_provider(
        monkeypatch,
        APP_ENV="test",
        OPENAI_API_KEY="openai-test-key",
        DEEPSEEK_API_KEY="deepseek-test-key",
    )

    settings = settings_module.settings
    model_names = provider_module.LLMRegistry.get_all_names()

    assert settings.ACTIVE_LLM_PROVIDER == settings_module.LLMProvider.OPENAI
    assert settings.DEFAULT_LLM_MODEL == "gpt-5-mini"
    assert model_names[0] == "gpt-5-mini"
    assert "deepseek-chat" in model_names


def test_explicit_deepseek_provider_uses_openai_embedder_when_available(monkeypatch):
    settings_module, provider_module = load_settings_and_provider(
        monkeypatch,
        APP_ENV="test",
        LLM_PROVIDER="deepseek",
        OPENAI_API_KEY="openai-test-key",
        DEEPSEEK_API_KEY="deepseek-test-key",
    )

    settings = settings_module.settings

    assert settings.ACTIVE_LLM_PROVIDER == settings_module.LLMProvider.DEEPSEEK
    assert provider_module.LLMRegistry.get_all_names()[0] == "deepseek-chat"
    assert settings.LONG_TERM_MEMORY_PROVIDER == settings_module.LLMProvider.DEEPSEEK
    assert settings.LONG_TERM_MEMORY_AVAILABLE is True
    assert settings.get_long_term_memory_llm_config()["deepseek_base_url"] == settings.DEEPSEEK_BASE_URL
    assert settings.get_long_term_memory_embedder_config()["openai_base_url"] == settings.OPENAI_BASE_URL


def test_alibaba_embedding_config_can_use_openai_compatible_embedder(monkeypatch):
    settings_module, _ = load_settings_and_provider(
        monkeypatch,
        APP_ENV="test",
        LLM_PROVIDER="deepseek",
        DEEPSEEK_API_KEY="deepseek-test-key",
        LONG_TERM_MEMORY_PROVIDER="deepseek",
        LONG_TERM_MEMORY_EMBEDDER_PROVIDER="openai",
        LONG_TERM_MEMORY_EMBEDDER_API_KEY="aliyun-test-key",
        LONG_TERM_MEMORY_EMBEDDER_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1",
        LONG_TERM_MEMORY_EMBEDDER_MODEL="text-embedding-v4",
        LONG_TERM_MEMORY_EMBEDDER_DIMS="1024",
    )

    settings = settings_module.settings
    embedder_config = settings.get_long_term_memory_embedder_config()
    vector_store_config = settings.get_long_term_memory_vector_store_config()

    assert settings.LONG_TERM_MEMORY_AVAILABLE is True
    assert embedder_config["model"] == "text-embedding-v4"
    assert embedder_config["embedding_dims"] == 1024
    assert embedder_config["openai_base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert vector_store_config["embedding_model_dims"] == 1024


def test_llm_service_propagates_runnable_config_to_model_calls(monkeypatch):
    _, provider_module = load_settings_and_provider(
        monkeypatch,
        APP_ENV="test",
        OPENAI_API_KEY="openai-test-key",
    )

    service = provider_module.LLMService()

    class FakeLLM:
        def __init__(self):
            self.config = None
            self.messages = None

        async def ainvoke(self, messages, config=None):
            self.messages = messages
            self.config = config
            return AIMessage(content="ok")

    fake_llm = FakeLLM()
    service._llm = fake_llm

    runnable_config = {"callbacks": ["langfuse-callback"], "metadata": {"trace_id": "trace-123"}}
    response = asyncio.run(service.call([HumanMessage(content="hello")], config=runnable_config))

    assert response.content == "ok"
    assert fake_llm.config == runnable_config
    assert fake_llm.messages[0].content == "hello"


