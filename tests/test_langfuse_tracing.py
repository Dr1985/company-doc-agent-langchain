import importlib
import sys


ENV_KEYS = [
    "APP_ENV",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_HOST",
    "LANGFUSE_TRACING_ENABLED",
    "LANGFUSE_SAMPLE_RATE",
    "LANGFUSE_FLUSH_AT",
    "LANGFUSE_FLUSH_INTERVAL",
    "LANGFUSE_RELEASE",
]

MODULES_TO_RESET = [
    "src.config.settings",
    "src.system.logs",
    "src.system.tracing",
]


def load_tracing(monkeypatch, **env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    # Explicitly set auth keys to empty to prevent .env file restore
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    monkeypatch.setenv("APP_ENV", "test")

    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)

    settings_module = importlib.import_module("src.config.settings")
    tracing_module = importlib.import_module("src.system.tracing")
    return settings_module, tracing_module


def test_langfuse_tracing_is_disabled_without_credentials(monkeypatch):
    settings_module, tracing_module = load_tracing(monkeypatch)

    assert settings_module.settings.LANGFUSE_CONFIGURED is False
    assert settings_module.settings.LANGFUSE_TRACING_ENABLED is False
    assert tracing_module.get_langfuse_client() is None
    assert tracing_module.get_langchain_callbacks() == []
    assert tracing_module.capture_current_trace_context() is None
    assert tracing_module.should_trace_request("/metrics") is False
    assert tracing_module.should_trace_request("/api/chatbot/chat") is True


def test_langfuse_tracing_uses_base_url_and_creates_callbacks(monkeypatch):
    settings_module, tracing_module = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_BASE_URL="https://langfuse.example.com",
    )

    client = tracing_module.get_langfuse_client()
    callbacks = tracing_module.get_langchain_callbacks()
    trace_id = tracing_module.create_trace_id("request-123")

    assert client is not None
    assert settings_module.settings.LANGFUSE_CONFIGURED is True
    assert settings_module.settings.LANGFUSE_TRACING_ENABLED is True
    assert settings_module.settings.LANGFUSE_BASE_URL == "https://langfuse.example.com"
    assert settings_module.settings.LANGFUSE_HOST == "https://langfuse.example.com"
    assert len(callbacks) == 1
    assert isinstance(trace_id, str)
    assert trace_id

    tracing_module.shutdown_langfuse()


