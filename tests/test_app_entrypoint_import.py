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
    "src.agent.workflow",
    "src.agent.tools",
    "src.agent.tools.__init__",
    "src.services.llm_provider",
    "src.config.settings",
    "src.system.logs",
    "src.system.middleware",
    "src.system.tracing",
]


def reset_modules():
    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)


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

    main_module = importlib.import_module("src.main")

    assert main_module.app.title == "FastAPI LangGraph Template"
    assert any(route.path == "/" for route in main_module.app.routes)
    assert any(route.path.endswith("/health") for route in main_module.app.routes)

