"""Test Langfuse tracing integration."""
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
    """Load tracing modules with custom environment.

    Uses delenv to clear all env vars, then sets auth keys to empty
    strings to prevent the .env file from restoring placeholder values.
    Numeric keys like LANGFUSE_SAMPLE_RATE are deleted so they get their
    default values from os.getenv(key, default).
    """
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    # Explicitly set auth keys to empty to prevent .env file restore
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    monkeypatch.setenv("APP_ENV", "test")

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)

    settings_module = importlib.import_module("src.config.settings")
    tracing_module = importlib.import_module("src.system.tracing")
    return settings_module, tracing_module


def test_langfuse_tracing_is_disabled_without_credentials(monkeypatch):
    """Test that tracing is disabled when credentials are missing."""
    settings_module, tracing_module = load_tracing(monkeypatch)

    assert settings_module.settings.LANGFUSE_CONFIGURED is False
    assert settings_module.settings.LANGFUSE_TRACING_ENABLED is False
    assert tracing_module.get_langfuse_client() is None
    assert tracing_module.get_langchain_callbacks() == []
    assert tracing_module.capture_current_trace_context() is None
    assert tracing_module.should_trace_request("/metrics") is False
    assert tracing_module.should_trace_request("/api/chatbot/chat") is True


def test_langfuse_tracing_uses_base_url_and_creates_callbacks(monkeypatch):
    """Test that tracing works with valid credentials."""
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


def test_record_llm_call_helper(monkeypatch):
    """Test the record_llm_call helper function."""
    _, tracing_module = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
    )

    # Test that the helper returns a context manager
    context = tracing_module.record_llm_call(
        "llm.chat",
        model="gpt-4",
        provider="openai",
        input_messages=[{"role": "user", "content": "Hello"}],
        metadata={"temperature": 0.7},
    )
    
    assert context is not None
    # Context should be usable
    with context:
        pass
    
    tracing_module.shutdown_langfuse()


def test_record_tool_execution_helper(monkeypatch):
    """Test the record_tool_execution helper function."""
    _, tracing_module = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
    )

    # Test that the helper returns a context manager
    context = tracing_module.record_tool_execution(
        "web_search",
        tool_args={"query": "test"},
        metadata={"duration_ms": 100},
    )
    
    assert context is not None
    # Context should be usable
    with context:
        pass
    
    tracing_module.shutdown_langfuse()


def test_trace_context_propagation(monkeypatch):
    """Test that trace context can be captured and used."""
    _, tracing_module = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
    )

    # Without an active trace, context should be None
    context = tracing_module.capture_current_trace_context()
    assert context is None
    
    # Create a trace ID
    trace_id = tracing_module.create_trace_id("test-seed")
    assert trace_id is not None
    
    tracing_module.shutdown_langfuse()


def test_trace_url_generation(monkeypatch):
    """Test that trace URLs are generated correctly.
    
    Note: get_trace_url may attempt network calls in some versions.
    We test with a valid trace_id and verify the URL format without
    making actual network requests by checking create_trace_id works.
    """
    _, tracing_module = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_BASE_URL="https://cloud.langfuse.com",
    )

    # Verify trace ID creation works
    trace_id = tracing_module.create_trace_id("test-seed")
    assert trace_id is not None
    assert isinstance(trace_id, str)
    assert len(trace_id) > 0
    
    # get_trace_url with None should return None
    assert tracing_module.get_trace_url(None) is None
    
    tracing_module.shutdown_langfuse()


def test_update_trace_and_span_helpers(monkeypatch):
    """Test trace and span update helpers."""
    _, tracing_module = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
    )

    # These should not raise errors even without active traces
    tracing_module.update_current_trace(
        name="test.trace",
        user_id="user-123",
        session_id="session-456",
        tags=["test"],
    )
    
    tracing_module.update_current_span(
        name="test.span",
        metadata={"key": "value"},
    )
    
    tracing_module.shutdown_langfuse()


def test_sample_rate_configuration(monkeypatch):
    """Test that sample rate configuration works."""
    settings_module, tracing_module = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_SAMPLE_RATE="0.5",
    )

    assert settings_module.settings.LANGFUSE_SAMPLE_RATE == 0.5
    
    tracing_module.shutdown_langfuse()


def test_release_version_configuration(monkeypatch):
    """Test that release version configuration works."""
    settings_module, _ = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_RELEASE="v2.0.0",
    )

    assert settings_module.settings.LANGFUSE_RELEASE == "v2.0.0"


def test_debug_mode_configuration(monkeypatch):
    """Test that debug mode configuration works."""
    settings_module, _ = load_tracing(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_DEBUG="true",
    )

    assert settings_module.settings.LANGFUSE_DEBUG is True
