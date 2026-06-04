"""Application configuration management.

This module handles environment-specific configuration loading, parsing, and management
for the application. It includes environment detection, .env file loading, and
configuration value parsing.
"""

import os
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from dotenv import load_dotenv


# Define environment types
class Environment(str, Enum):
    """Application environment types.

    Defines the possible environments the application can run in:
    development, staging, production, and test.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class LLMProvider(str, Enum):
    """Supported chat model providers."""

    AUTO = "auto"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"


# Determine environment
def get_environment() -> Environment:
    """Get the current environment.

    Returns:
        Environment: The current environment (development, staging, production, or test)
    """
    match os.getenv("APP_ENV", "development").lower():
        case "production" | "prod":
            return Environment.PRODUCTION
        case "staging" | "stage":
            return Environment.STAGING
        case "test":
            return Environment.TEST
        case _:
            return Environment.DEVELOPMENT


# Load appropriate .env file based on environment
def load_env_file():
    """Load environment-specific .env file."""
    env = get_environment()
    print(f"Loading environment: {env}")
    base_dir = Path(__file__).resolve().parents[2]

    # Define env files in priority order
    env_files = [
        base_dir / f".env.{env.value}.local",
        base_dir / f".env.{env.value}",
        base_dir / ".env.local",
        base_dir / ".env",
    ]

    # Load the first env file that exists
    for env_file in env_files:
        if env_file.is_file():
            load_dotenv(dotenv_path=env_file)
            print(f"Loaded environment from {env_file}")
            return str(env_file)

    # Fall back to default if no env file found
    return None


ENV_FILE = load_env_file()


# Parse list values from environment variables
def parse_list_from_env(env_key, default=None):
    """Parse a comma-separated list from an environment variable."""
    value = os.getenv(env_key)
    if not value:
        return default or []

    # Remove quotes if they exist
    value = value.strip("\"'")
    # Handle single value case
    if "," not in value:
        return [value]
    # Split comma-separated values
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_bool_from_env(env_key: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    value = os.getenv(env_key)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "t", "yes", "y", "on")


def parse_optional_int_from_env(env_key: str, default: Optional[int] = None) -> Optional[int]:
    """Parse an optional integer environment variable."""
    value = os.getenv(env_key)
    if value is None or not value.strip():
        return default
    return int(value)


def parse_optional_float_from_env(env_key: str, default: Optional[float] = None) -> Optional[float]:
    """Parse an optional float environment variable."""
    value = os.getenv(env_key)
    if value is None or not value.strip():
        return default
    return float(value)


# Parse dict of lists from environment variables with prefix
def parse_dict_of_lists_from_env(prefix, default_dict=None):
    """Parse dictionary of lists from environment variables with a common prefix."""
    result = default_dict or {}

    # Look for all env vars with the given prefix
    for key, value in os.environ.items():
        if key.startswith(prefix):
            endpoint = key[len(prefix) :].lower()  # Extract endpoint name
            # Parse the values for this endpoint
            if value:
                value = value.strip("\"'")
                if "," in value:
                    result[endpoint] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    result[endpoint] = [value]

    return result


class Settings:
    """Application settings without using pydantic."""

    @staticmethod
    def _normalize_provider(
        provider: Union[str, LLMProvider, None], allow_auto: bool = False
    ) -> LLMProvider:
        """Normalize a provider string into an enum value."""
        if isinstance(provider, LLMProvider):
            if provider == LLMProvider.AUTO and not allow_auto:
                return LLMProvider.OPENAI
            return provider

        normalized = (provider or "").strip().lower()
        if not normalized:
            return LLMProvider.AUTO if allow_auto else LLMProvider.OPENAI

        if normalized == LLMProvider.AUTO.value and allow_auto:
            return LLMProvider.AUTO
        if normalized == LLMProvider.OPENAI.value:
            return LLMProvider.OPENAI
        if normalized == LLMProvider.OPENROUTER.value:
            return LLMProvider.OPENROUTER
        if normalized == LLMProvider.DEEPSEEK.value:
            return LLMProvider.DEEPSEEK

        allowed_values = [LLMProvider.OPENAI.value, LLMProvider.OPENROUTER.value, LLMProvider.DEEPSEEK.value]
        if allow_auto:
            allowed_values.insert(0, LLMProvider.AUTO.value)
        raise ValueError(f"unsupported llm provider '{provider}'. expected one of: {', '.join(allowed_values)}")

    @staticmethod
    def infer_provider_from_model(model_name: str) -> Optional[LLMProvider]:
        """Infer a provider from a model name when possible."""
        normalized = (model_name or "").strip().lower()
        if not normalized:
            return None

        if "/" in normalized:
            return LLMProvider.OPENROUTER
        if normalized.startswith("deepseek-"):
            return LLMProvider.DEEPSEEK
        if normalized.startswith(("gpt-", "o1", "o3", "o4")):
            return LLMProvider.OPENAI
        return None

    @staticmethod
    def _provider_preference_order() -> List[LLMProvider]:
        """Return the default provider priority used in auto mode."""
        return [LLMProvider.OPENAI, LLMProvider.OPENROUTER, LLMProvider.DEEPSEEK]

    def get_llm_api_key(self, provider: Union[str, LLMProvider]) -> str:
        """Get the API key for a provider."""
        provider = self._normalize_provider(provider)
        if provider == LLMProvider.OPENROUTER:
            return self.OPENROUTER_API_KEY
        if provider == LLMProvider.DEEPSEEK:
            return self.DEEPSEEK_API_KEY
        return self.OPENAI_API_KEY

    def get_llm_base_url(self, provider: Union[str, LLMProvider]) -> str:
        """Get the base URL for a provider."""
        provider = self._normalize_provider(provider)
        if provider == LLMProvider.OPENROUTER:
            return self.OPENROUTER_BASE_URL
        if provider == LLMProvider.DEEPSEEK:
            return self.DEEPSEEK_BASE_URL
        return self.OPENAI_BASE_URL

    def get_llm_client_config(self, provider: Union[str, LLMProvider]) -> Dict[str, str]:
        """Return the connection settings for a provider."""
        return {
            "api_key": self.get_llm_api_key(provider),
            "base_url": self.get_llm_base_url(provider),
        }

    def _resolve_active_llm_provider(self) -> LLMProvider:
        """Resolve the active LLM provider during application startup."""
        if self.LLM_PROVIDER != LLMProvider.AUTO:
            return self.LLM_PROVIDER

        configured_model = os.getenv("DEFAULT_LLM_MODEL", "").strip()
        inferred_provider = self.infer_provider_from_model(configured_model)
        if inferred_provider and self.get_llm_api_key(inferred_provider):
            return inferred_provider

        configured_providers = [
            provider
            for provider in self._provider_preference_order()
            if self.get_llm_api_key(provider)
        ]
        if configured_providers:
            return configured_providers[0]
        return LLMProvider.OPENAI

    def _get_available_llm_providers(self) -> List[LLMProvider]:
        """Get the providers with configured API keys."""
        providers: List[LLMProvider] = []
        for provider in self._provider_preference_order():
            if self.get_llm_api_key(provider):
                providers.append(provider)
        return providers

    def _resolve_model_setting(
        self,
        env_key: str,
        defaults: Dict[LLMProvider, str],
        provider: Optional[LLMProvider] = None,
    ) -> str:
        """Resolve a model setting, honoring explicit environment overrides."""
        explicit_model = os.getenv(env_key, "").strip()
        if explicit_model:
            return explicit_model

        resolved_provider = provider or self.ACTIVE_LLM_PROVIDER
        return defaults.get(resolved_provider, defaults[LLMProvider.OPENAI])

    def _resolve_long_term_memory_provider(self) -> LLMProvider:
        """Resolve the provider used by long-term memory fact extraction."""
        provider = self._normalize_provider(
            os.getenv("LONG_TERM_MEMORY_PROVIDER", self.ACTIVE_LLM_PROVIDER.value),
            allow_auto=True,
        )
        if provider == LLMProvider.AUTO:
            return self.ACTIVE_LLM_PROVIDER
        return provider

    def _resolve_long_term_memory_embedder_provider(self) -> str:
        """Resolve the embedder provider for long-term memory."""
        explicit_provider = os.getenv("LONG_TERM_MEMORY_EMBEDDER_PROVIDER", "").strip().lower()
        if explicit_provider:
            return explicit_provider

        if os.getenv("LONG_TERM_MEMORY_EMBEDDER_API_KEY", "").strip() or self.OPENAI_API_KEY:
            return "openai"
        return ""

    def get_long_term_memory_embedding_dims(self) -> int:
        """Get the embedding dimensionality used by long-term memory."""
        return self.LONG_TERM_MEMORY_EMBEDDER_DIMS

    def get_long_term_memory_vector_store_config(self) -> Dict[str, Any]:
        """Build the mem0 vector-store configuration for long-term memory."""
        return {
            "collection_name": self.LONG_TERM_MEMORY_COLLECTION_NAME,
            "dbname": self.POSTGRES_DB,
            "user": self.POSTGRES_USER,
            "password": self.POSTGRES_PASSWORD,
            "host": self.POSTGRES_HOST,
            "port": self.POSTGRES_PORT,
            "embedding_model_dims": self.get_long_term_memory_embedding_dims(),
        }

    def _resolve_long_term_memory_state(self) -> Tuple[bool, str]:
        """Determine whether long-term memory can be initialized safely."""
        if not self.LONG_TERM_MEMORY_ENABLED:
            return False, "disabled via LONG_TERM_MEMORY_ENABLED=false"

        if not self.get_llm_api_key(self.LONG_TERM_MEMORY_PROVIDER):
            return (
                False,
                f"{self.LONG_TERM_MEMORY_PROVIDER.value} api key is missing for long-term memory llm provider",
            )

        if not self.LONG_TERM_MEMORY_EMBEDDER_PROVIDER:
            return (
                False,
                "no long-term memory embedder is configured; set LONG_TERM_MEMORY_EMBEDDER_PROVIDER or OPENAI_API_KEY",
            )

        if (
            self.LONG_TERM_MEMORY_EMBEDDER_PROVIDER == "openai"
            and not self.LONG_TERM_MEMORY_EMBEDDER_API_KEY
        ):
            return (
                False,
                "LONG_TERM_MEMORY_EMBEDDER_API_KEY or OPENAI_API_KEY is required for the openai embedder",
            )

        return True, ""

    def get_long_term_memory_llm_config(self) -> Dict[str, Any]:
        """Build the provider-specific mem0 LLM configuration."""
        provider = self.LONG_TERM_MEMORY_PROVIDER
        config: Dict[str, Any] = {
            "model": self.LONG_TERM_MEMORY_MODEL,
            "api_key": self.get_llm_api_key(provider),
            "temperature": self.DEFAULT_LLM_TEMPERATURE,
            "max_tokens": self.MAX_TOKENS,
        }

        if provider == LLMProvider.DEEPSEEK:
            config["deepseek_base_url"] = self.get_llm_base_url(provider)
        else:
            config["openai_base_url"] = self.get_llm_base_url(provider)

        return config

    def get_long_term_memory_llm_provider_name(self) -> str:
        """Return the mem0-compatible provider name for long-term memory."""
        if self.LONG_TERM_MEMORY_PROVIDER == LLMProvider.DEEPSEEK:
            return LLMProvider.DEEPSEEK.value
        return LLMProvider.OPENAI.value

    def get_long_term_memory_embedder_config(self) -> Dict[str, Any]:
        """Build the mem0 embedder configuration."""
        config: Dict[str, Any] = {
            "model": self.LONG_TERM_MEMORY_EMBEDDER_MODEL,
            "embedding_dims": self.get_long_term_memory_embedding_dims(),
        }

        if self.LONG_TERM_MEMORY_EMBEDDER_PROVIDER == "openai":
            config.update(
                {
                    "api_key": self.LONG_TERM_MEMORY_EMBEDDER_API_KEY,
                    "openai_base_url": self.LONG_TERM_MEMORY_EMBEDDER_BASE_URL,
                }
            )

        return config

    def __init__(self):
        """Initialize application settings from environment variables.

        Loads and sets all configuration values from environment variables,
        with appropriate defaults for each setting. Also applies
        environment-specific overrides based on the current environment.
        """
        # Set the environment
        self.ENVIRONMENT = get_environment()

        # Application Settings
        self.PROJECT_NAME = os.getenv("PROJECT_NAME", "FastAPI LangGraph Template")
        self.VERSION = os.getenv("VERSION", "1.0.0")
        self.DESCRIPTION = os.getenv(
            "DESCRIPTION", "A production-ready FastAPI template with LangGraph and Langfuse integration"
        )
        self.API_V1_STR = os.getenv("API_V1_STR", "/api")
        self.DEBUG = parse_bool_from_env("DEBUG", False)

        # CORS Settings
        self.ALLOWED_ORIGINS = parse_list_from_env("ALLOWED_ORIGINS", ["*"])

        # Langfuse Configuration
        self.LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        self.LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        self.LANGFUSE_BASE_URL = os.getenv(
            "LANGFUSE_BASE_URL",
            os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        ).strip()
        # Keep HOST for backwards compatibility with existing deployments.
        self.LANGFUSE_HOST = self.LANGFUSE_BASE_URL
        self.LANGFUSE_CONFIGURED = bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)
        self.LANGFUSE_TRACING_ENABLED = parse_bool_from_env(
            "LANGFUSE_TRACING_ENABLED", self.LANGFUSE_CONFIGURED
        )
        self.LANGFUSE_DEBUG = parse_bool_from_env("LANGFUSE_DEBUG", self.DEBUG)
        self.LANGFUSE_SAMPLE_RATE = min(max(float(os.getenv("LANGFUSE_SAMPLE_RATE", "1.0")), 0.0), 1.0)
        self.LANGFUSE_FLUSH_AT = parse_optional_int_from_env("LANGFUSE_FLUSH_AT", None)
        self.LANGFUSE_FLUSH_INTERVAL = parse_optional_float_from_env("LANGFUSE_FLUSH_INTERVAL", None)
        self.LANGFUSE_RELEASE = os.getenv("LANGFUSE_RELEASE", self.VERSION).strip() or self.VERSION

        # LangGraph Configuration
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
        self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
        self.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.DEEPSEEK_BASE_URL = os.getenv(
            "DEEPSEEK_BASE_URL",
            os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
        ).strip()
        self.LLM_PROVIDER = self._normalize_provider(os.getenv("LLM_PROVIDER", LLMProvider.AUTO.value), allow_auto=True)
        self.ACTIVE_LLM_PROVIDER = self._resolve_active_llm_provider()
        self.ACTIVE_LLM_API_KEY = self.get_llm_api_key(self.ACTIVE_LLM_PROVIDER)
        self.ACTIVE_LLM_BASE_URL = self.get_llm_base_url(self.ACTIVE_LLM_PROVIDER)
        self.AVAILABLE_LLM_PROVIDERS = self._get_available_llm_providers()
        self.DEFAULT_LLM_MODEL = self._resolve_model_setting(
            "DEFAULT_LLM_MODEL",
            {
                LLMProvider.OPENAI: "gpt-5-mini",
                LLMProvider.OPENROUTER: "nvidia/nemotron-3-super-120b-a12b:free",
                LLMProvider.DEEPSEEK: "deepseek-chat",
            },
        )
        self.DEFAULT_LLM_TEMPERATURE = float(os.getenv("DEFAULT_LLM_TEMPERATURE", "0.2"))
        self.MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2000"))
        self.MAX_LLM_CALL_RETRIES = int(os.getenv("MAX_LLM_CALL_RETRIES", "3"))

        # Long term memory Configuration
        self.LONG_TERM_MEMORY_ENABLED = parse_bool_from_env("LONG_TERM_MEMORY_ENABLED", True)
        self.LONG_TERM_MEMORY_PROVIDER = self._resolve_long_term_memory_provider()
        self.LONG_TERM_MEMORY_MODEL = self._resolve_model_setting(
            "LONG_TERM_MEMORY_MODEL",
            {
                LLMProvider.OPENAI: "gpt-5-nano",
                LLMProvider.OPENROUTER: "nvidia/nemotron-3-super-120b-a12b:free",
                LLMProvider.DEEPSEEK: "deepseek-chat",
            },
            provider=self.LONG_TERM_MEMORY_PROVIDER,
        )
        self.LONG_TERM_MEMORY_EMBEDDER_PROVIDER = self._resolve_long_term_memory_embedder_provider()
        self.LONG_TERM_MEMORY_EMBEDDER_MODEL = os.getenv(
            "LONG_TERM_MEMORY_EMBEDDER_MODEL", "text-embedding-3-small"
        ).strip()
        self.LONG_TERM_MEMORY_EMBEDDER_DIMS = parse_optional_int_from_env("LONG_TERM_MEMORY_EMBEDDER_DIMS", 1536)
        self.LONG_TERM_MEMORY_EMBEDDER_API_KEY = os.getenv(
            "LONG_TERM_MEMORY_EMBEDDER_API_KEY", self.OPENAI_API_KEY
        ).strip()
        self.LONG_TERM_MEMORY_EMBEDDER_BASE_URL = os.getenv(
            "LONG_TERM_MEMORY_EMBEDDER_BASE_URL", self.OPENAI_BASE_URL
        ).strip()
        self.LONG_TERM_MEMORY_COLLECTION_NAME = os.getenv("LONG_TERM_MEMORY_COLLECTION_NAME", "longterm_memory")
        (
            self.LONG_TERM_MEMORY_AVAILABLE,
            self.LONG_TERM_MEMORY_DISABLED_REASON,
        ) = self._resolve_long_term_memory_state()
        # Qwen Embedding Configuration
        self.QWEN_EMBEDDING_API_KEY = os.getenv("QWEN_EMBEDDING_API_KEY", "").strip()
        self.QWEN_EMBEDDING_BASE_URL = os.getenv(
            "QWEN_EMBEDDING_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).strip()
        self.QWEN_EMBEDDING_MODEL = os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4").strip()
        self.QWEN_EMBEDDING_DIMS = int(os.getenv("QWEN_EMBEDDING_DIMS", "1024"))
        self.QWEN_EMBEDDING_AVAILABLE = bool(self.QWEN_EMBEDDING_API_KEY)

        # MinIO / S3 Configuration
        self.MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000").strip()
        self.MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin").strip()
        self.MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin").strip()
        self.MINIO_BUCKET = os.getenv("MINIO_BUCKET", "documents").strip()
        self.MINIO_SECURE = parse_bool_from_env("MINIO_USE_SSL", False)

        # Ingestion Configuration
        self.INGESTION_CHUNK_SIZE = int(os.getenv("INGESTION_CHUNK_SIZE", "512"))
        self.INGESTION_CHUNK_OVERLAP = int(os.getenv("INGESTION_CHUNK_OVERLAP", "128"))
        self.MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(50 * 1024 * 1024)))  # 50 MB

        # JWT Configuration
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_DAYS", "30"))

        # Logging Configuration
        self.LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # "json" or "console"

        # Postgres Configuration
        self.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
        self.POSTGRES_DB = os.getenv("POSTGRES_DB", "food_order_db")
        self.POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
        self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
        self.POSTGRES_POOL_SIZE = int(os.getenv("POSTGRES_POOL_SIZE", "20"))
        self.POSTGRES_MAX_OVERFLOW = int(os.getenv("POSTGRES_MAX_OVERFLOW", "10"))
        self.CHECKPOINT_TABLES = ["checkpoint_blobs", "checkpoint_writes", "checkpoints"]

        # Rate Limiting Configuration
        self.RATE_LIMIT_DEFAULT = parse_list_from_env("RATE_LIMIT_DEFAULT", ["200 per day", "50 per hour"])

        # Rate limit endpoints defaults
        default_endpoints = {
            "chat": ["30 per minute"],
            "chat_stream": ["20 per minute"],
            "messages": ["50 per minute"],
            "register": ["10 per hour"],
            "login": ["20 per minute"],
            "root": ["10 per minute"],
            "health": ["20 per minute"],
        }

        # Update rate limit endpoints from environment variables
        self.RATE_LIMIT_ENDPOINTS = default_endpoints.copy()
        for endpoint in default_endpoints:
            env_key = f"RATE_LIMIT_{endpoint.upper()}"
            value = parse_list_from_env(env_key)
            if value:
                self.RATE_LIMIT_ENDPOINTS[endpoint] = value

        # Evaluation Configuration
        self.EVALUATION_LLM = self._resolve_model_setting(
            "EVALUATION_LLM",
            {
                LLMProvider.OPENAI: "gpt-5",
                LLMProvider.OPENROUTER: "nvidia/nemotron-3-super-120b-a12b:free",
                LLMProvider.DEEPSEEK: "deepseek-chat",
            },
        )
        self.EVALUATION_BASE_URL = os.getenv("EVALUATION_BASE_URL", self.ACTIVE_LLM_BASE_URL).strip()
        self.EVALUATION_API_KEY = os.getenv("EVALUATION_API_KEY", self.ACTIVE_LLM_API_KEY).strip()
        self.EVALUATION_SLEEP_TIME = int(os.getenv("EVALUATION_SLEEP_TIME", "10"))

        # Apply environment-specific settings
        self.apply_environment_settings()

    def apply_environment_settings(self):
        """Apply environment-specific settings based on the current environment."""
        env_settings = {
            Environment.DEVELOPMENT: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "200 per hour"],
            },
            Environment.STAGING: {
                "DEBUG": False,
                "LOG_LEVEL": "INFO",
                "RATE_LIMIT_DEFAULT": ["500 per day", "100 per hour"],
            },
            Environment.PRODUCTION: {
                "DEBUG": False,
                "LOG_LEVEL": "WARNING",
                "RATE_LIMIT_DEFAULT": ["200 per day", "50 per hour"],
            },
            Environment.TEST: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "1000 per hour"],  # Relaxed for testing
            },
        }

        # Get settings for current environment
        current_env_settings = env_settings.get(self.ENVIRONMENT, {})

        # Apply settings if not explicitly set in environment variables
        for key, value in current_env_settings.items():
            env_var_name = key.upper()
            # Only override if environment variable wasn't explicitly set
            if env_var_name not in os.environ:
                setattr(self, key, value)


# Create settings instance
settings = Settings()
