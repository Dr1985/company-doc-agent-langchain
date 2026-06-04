import asyncio
import importlib
import sys
import types


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
    "LANGFUSE_SAMPLE_RATE",
    "LANGFUSE_FLUSH_AT",
    "LANGFUSE_FLUSH_INTERVAL",
    "PROJECT_NAME",
    "OPENAI_BASE_URL",
    "OPENROUTER_BASE_URL",
    "DEEPSEEK_BASE_URL",
]

MODULES_TO_RESET = [
    "src.main",
    "src.interface.router",
    "src.interface.auth",
    "src.interface.interaction",
    "src.interface.stats",
    "src.agent.workflow",
    "src.agent.tools",
    "src.agent.tools.__init__",
    "src.services.llm_provider",
    "src.services.cache",
    "src.services.stats_service",
    "src.config.settings",
    "src.system.logs",
    "src.system.middleware",
    "src.system.tracing",
    "src.retrieval",
    "src.retrieval.hybrid",
]


def _make_fake_services(monkeypatch):
    """Set up minimal fake modules so main.py can import without heavy deps."""
    fake_cache = types.ModuleType("src.services.cache")
    fake_cache.cache_service = types.SimpleNamespace(
        get=lambda query_embedding: None,
        set=lambda *a, **kw: None,
        invalidate=lambda document_id: None,
        stats=lambda: {"ready": False, "entries": 0},
    )
    monkeypatch.setitem(sys.modules, "src.services.cache", fake_cache)

    fake_stats = types.ModuleType("src.services.stats_service")
    fake_stats.get_overview = lambda: {}
    fake_stats.get_daily_trend = lambda days=7: []
    fake_stats.get_model_usage = lambda: []
    monkeypatch.setitem(sys.modules, "src.services.stats_service", fake_stats)


def reset_modules():
    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)


def test_fastapi_entrypoint_sets_selector_event_loop_policy_on_windows(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("LONG_TERM_MEMORY_ENABLED", "false")

    fake_db_module = types.ModuleType("src.data.db_manager")

    class DatabaseService:
        def __init__(self, *args, **kwargs):
            pass

    class FakeDBManager:
        async def health_check(self):
            return True

    fake_db_module.DatabaseService = DatabaseService
    fake_db_module.db_manager = FakeDBManager()

    selector_policy_calls = []

    class FakeWindowsSelectorEventLoopPolicy:
        pass

    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", FakeWindowsSelectorEventLoopPolicy, raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: selector_policy_calls.append(policy))

    reset_modules()
    monkeypatch.setitem(sys.modules, "src.data.db_manager", fake_db_module)
    _make_fake_services(monkeypatch)

    importlib.import_module("src.main")

    assert len(selector_policy_calls) == 1
    assert isinstance(selector_policy_calls[0], FakeWindowsSelectorEventLoopPolicy)


def test_fastapi_entrypoint_imports_with_stubbed_database(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    # Prevent .env file from restoring values by mocking load_dotenv
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("LONG_TERM_MEMORY_ENABLED", "false")

    fake_db_module = types.ModuleType("src.data.db_manager")

    class DatabaseService:
        def __init__(self, *args, **kwargs):
            pass

    class FakeDBManager:
        async def health_check(self):
            return True

    fake_db_module.DatabaseService = DatabaseService
    fake_db_module.db_manager = FakeDBManager()

    reset_modules()
    monkeypatch.setitem(sys.modules, "src.data.db_manager", fake_db_module)
    _make_fake_services(monkeypatch)

    main_module = importlib.import_module("src.main")

    assert main_module.app.title == "FastAPI LangGraph Template"
    assert any(route.path == "/" for route in main_module.app.routes)
    assert any(route.path.endswith("/health") for route in main_module.app.routes)


def test_fastapi_entrypoint_run_uses_embedded_uvicorn_launcher(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("LONG_TERM_MEMORY_ENABLED", "false")
    monkeypatch.setenv("UVICORN_HOST", "127.0.0.1")
    monkeypatch.setenv("UVICORN_PORT", "8012")
    monkeypatch.setenv("UVICORN_RELOAD", "true")

    fake_db_module = types.ModuleType("src.data.db_manager")

    class DatabaseService:
        def __init__(self, *args, **kwargs):
            pass

    class FakeDBManager:
        async def health_check(self):
            return True

    fake_db_module.DatabaseService = DatabaseService
    fake_db_module.db_manager = FakeDBManager()

    uvicorn_calls = []
    fake_uvicorn = types.ModuleType("uvicorn")

    def fake_run(app, host, port, reload, log_level):
        uvicorn_calls.append(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "log_level": log_level,
            }
        )

    fake_uvicorn.run = fake_run

    reset_modules()
    monkeypatch.setitem(sys.modules, "src.data.db_manager", fake_db_module)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    _make_fake_services(monkeypatch)

    main_module = importlib.import_module("src.main")
    main_module.run()

    assert len(uvicorn_calls) == 1
    assert uvicorn_calls[0]["app"] is main_module.app
    assert uvicorn_calls[0]["host"] == "127.0.0.1"
    assert uvicorn_calls[0]["port"] == 8012
    assert uvicorn_calls[0]["reload"] is True
    assert uvicorn_calls[0]["log_level"] == "debug"


