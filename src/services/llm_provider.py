"""LLM service for managing LLM calls with retries and fallback mechanisms."""

import logging

from typing import (
    Any,
    Dict,
    List,
    Optional,
    cast,
)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from openai import (
    APIError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config.settings import (
    Environment,
    LLMProvider,
    settings,
)
from src.system.logs import logger
from src.system.tracing import (
    capture_current_trace_context,
    record_llm_call,
    update_current_span,
)


def _safe_dump_message(m: object) -> dict:
    """Safely dump a message (dict or BaseMessage) for tracing input."""
    if isinstance(m, dict):
        return {
            "role": str(m.get("role") or m.get("type") or "unknown"),
            "content": str(m.get("content", "")),
        }
    try:
        return {
            "role": getattr(m, "type", "unknown"),
            "content": str(getattr(m, "content", "")),
        }
    except Exception:
        return {"role": "unknown", "content": str(m)}


def _safe_response_dump(response: object) -> dict:
    """Safely dump an LLM response for tracing output."""
    if isinstance(response, dict):
        content = response.get("content", "")
        content_len = len(str(content)) if content else 0
        return {
            "response_type": str(response.get("type", "unknown")),
            "content_length": content_len,
            "has_tool_calls": bool(response.get("tool_calls")),
        }
    try:
        content = getattr(response, "content", None)
        content_len = len(str(content)) if content else 0
        return {
            "response_type": str(getattr(response, "type", "unknown")),
            "content_length": content_len,
            "has_tool_calls": bool(getattr(response, "tool_calls", None)),
        }
    except Exception:
        return {"response_type": "unknown", "content_length": 0, "has_tool_calls": False}


class LLMRegistry:
    """Registry of available LLM models with provider-aware configuration."""

    @classmethod
    def _provider_model_catalog(cls) -> Dict[LLMProvider, List[Dict[str, Any]]]:
        """Return model definitions grouped by provider."""
        return {
            LLMProvider.OPENAI: [
                {
                    "name": "gpt-5-mini",
                    "provider": LLMProvider.OPENAI,
                    "kwargs": {
                        "max_tokens": settings.MAX_TOKENS,
                        "reasoning": {"effort": "low"},
                    },
                },
                {
                    "name": "gpt-5",
                    "provider": LLMProvider.OPENAI,
                    "kwargs": {
                        "max_tokens": settings.MAX_TOKENS,
                        "reasoning": {"effort": "medium"},
                    },
                },
                {
                    "name": "gpt-5-nano",
                    "provider": LLMProvider.OPENAI,
                    "kwargs": {
                        "max_tokens": settings.MAX_TOKENS,
                        "reasoning": {"effort": "minimal"},
                    },
                },
                {
                    "name": "gpt-4o",
                    "provider": LLMProvider.OPENAI,
                    "kwargs": {
                        "temperature": settings.DEFAULT_LLM_TEMPERATURE,
                        "max_tokens": settings.MAX_TOKENS,
                        "top_p": 0.95 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.8,
                        "presence_penalty": 0.1 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.0,
                        "frequency_penalty": 0.1 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.0,
                    },
                },
                {
                    "name": "gpt-4o-mini",
                    "provider": LLMProvider.OPENAI,
                    "kwargs": {
                        "temperature": settings.DEFAULT_LLM_TEMPERATURE,
                        "max_tokens": settings.MAX_TOKENS,
                        "top_p": 0.9 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.8,
                    },
                },
            ],
            LLMProvider.DEEPSEEK: [
                {
                    "name": "deepseek-chat",
                    "provider": LLMProvider.DEEPSEEK,
                    "kwargs": {
                        "temperature": settings.DEFAULT_LLM_TEMPERATURE,
                        "max_tokens": settings.MAX_TOKENS,
                        "top_p": 0.9 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.8,
                    },
                }
            ],
            LLMProvider.OPENROUTER: [
                {
                    "name": "nvidia/nemotron-3-super-120b-a12b:free",
                    "provider": LLMProvider.OPENROUTER,
                    "kwargs": {
                        "temperature": settings.DEFAULT_LLM_TEMPERATURE,
                        "max_tokens": settings.MAX_TOKENS,
                        "top_p": 0.9 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.8,
                    },
                },
                {
                    "name": "openai/gpt-oss-120b:free",
                    "provider": LLMProvider.OPENROUTER,
                    "kwargs": {
                        "temperature": settings.DEFAULT_LLM_TEMPERATURE,
                        "max_tokens": settings.MAX_TOKENS,
                        "top_p": 0.9 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.8,
                    },
                },
                {
                    "name": "z-ai/glm-4.5-air:free",
                    "provider": LLMProvider.OPENROUTER,
                    "kwargs": {
                        "temperature": settings.DEFAULT_LLM_TEMPERATURE,
                        "max_tokens": settings.MAX_TOKENS,
                        "top_p": 0.9 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.8,
                    },
                },
            ],
        }

    @classmethod
    def _provider_order(cls) -> List[LLMProvider]:
        """Return available providers with the active provider first."""
        ordered_providers: List[LLMProvider] = []
        if settings.ACTIVE_LLM_PROVIDER in settings.AVAILABLE_LLM_PROVIDERS:
            ordered_providers.append(settings.ACTIVE_LLM_PROVIDER)

        for provider in settings.AVAILABLE_LLM_PROVIDERS:
            if provider not in ordered_providers:
                ordered_providers.append(provider)

        return ordered_providers

    @classmethod
    def list_models(cls) -> List[Dict[str, Any]]:
        """Build the current model registry based on configured providers."""
        models: List[Dict[str, Any]] = []
        catalog = cls._provider_model_catalog()
        for provider in cls._provider_order():
            models.extend(catalog.get(provider, []))
        return models

    @classmethod
    def _create_llm(cls, model_name: str, provider: LLMProvider, **kwargs) -> BaseChatModel:
        """Create a ChatOpenAI client for an OpenAI-compatible provider."""
        connection_config = settings.get_llm_client_config(provider)
        return ChatOpenAI(model=model_name, **connection_config, **kwargs)

    @classmethod
    def get(cls, model_name: str, **kwargs) -> BaseChatModel:
        """Get an LLM by name with optional argument overrides."""
        model_entry = None
        for entry in cls.list_models():
            if entry["name"] == model_name:
                model_entry = entry
                break

        if not model_entry:
            available_models = [entry["name"] for entry in cls.list_models()]
            raise ValueError(
                f"model '{model_name}' not found in registry. available models: {', '.join(available_models)}"
            )

        model_kwargs = dict(model_entry["kwargs"])
        model_kwargs.update(kwargs)
        logger.debug(
            "creating_llm_instance",
            model_name=model_name,
            provider=model_entry["provider"].value,
            custom_args=list(kwargs.keys()),
        )
        return cls._create_llm(model_name, model_entry["provider"], **model_kwargs)

    @classmethod
    def get_all_names(cls) -> List[str]:
        """Get all registered LLM names in order."""
        return [entry["name"] for entry in cls.list_models()]

    @classmethod
    def get_model_at_index(cls, index: int) -> Dict[str, Any]:
        """Get model entry at a specific index."""
        models = cls.list_models()
        if not models:
            raise ValueError("no llm models are configured")
        if 0 <= index < len(models):
            return models[index]
        return models[0]


class LLMService:
    """Service for managing LLM calls with retries and circular fallback."""

    def __init__(self):
        """Initialize the LLM service."""
        self._llm: Optional[BaseChatModel] = None
        self._current_model_index: int = 0
        self._bound_tools: List[Any] = []

        all_names = LLMRegistry.get_all_names()
        if not all_names:
            logger.error(
                "no_llm_models_configured",
                provider_preference=settings.LLM_PROVIDER.value,
                active_provider=settings.ACTIVE_LLM_PROVIDER.value,
                available_providers=[provider.value for provider in settings.AVAILABLE_LLM_PROVIDERS],
            )
            return

        try:
            self._llm = self._create_bound_llm(settings.DEFAULT_LLM_MODEL)
            if settings.DEFAULT_LLM_MODEL in all_names:
                self._current_model_index = all_names.index(settings.DEFAULT_LLM_MODEL)
            logger.info(
                "llm_service_initialized",
                default_model=settings.DEFAULT_LLM_MODEL,
                model_index=self._current_model_index,
                total_models=len(all_names),
                environment=settings.ENVIRONMENT.value,
                active_provider=settings.ACTIVE_LLM_PROVIDER.value,
                available_providers=[provider.value for provider in settings.AVAILABLE_LLM_PROVIDERS],
            )
        except (ValueError, Exception) as e:
            fallback_model = all_names[0]
            self._current_model_index = 0
            self._llm = self._create_bound_llm(fallback_model)
            logger.warning(
                "default_model_not_found_using_first",
                requested=settings.DEFAULT_LLM_MODEL,
                using=fallback_model,
                error=str(e),
            )

    def _create_bound_llm(self, model_name: str, **kwargs) -> BaseChatModel:
        """Create an LLM instance and bind tools if they are configured."""
        llm = LLMRegistry.get(model_name, **kwargs)
        if self._bound_tools:
            llm = cast(BaseChatModel, llm.bind_tools(self._bound_tools))
        return llm

    def _get_next_model_index(self) -> int:
        """Get the next model index in circular fashion."""
        total_models = len(LLMRegistry.get_all_names())
        if total_models == 0:
            return 0
        return (self._current_model_index + 1) % total_models

    def _switch_to_next_model(self) -> bool:
        """Switch to the next model in the registry (circular)."""
        try:
            next_index = self._get_next_model_index()
            next_model_entry = LLMRegistry.get_model_at_index(next_index)

            logger.warning(
                "switching_to_next_model",
                from_index=self._current_model_index,
                to_index=next_index,
                to_model=next_model_entry["name"],
            )

            self._current_model_index = next_index
            self._llm = self._create_bound_llm(next_model_entry["name"])

            logger.info("model_switched", new_model=next_model_entry["name"], new_index=next_index)
            return True
        except Exception as e:
            logger.error("model_switch_failed", error=str(e))
            return False

    @retry(
        stop=stop_after_attempt(settings.MAX_LLM_CALL_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_llm_with_retry(
        self, messages: List[BaseMessage], config: Optional[Dict[str, Any]] = None
    ) -> BaseMessage:
        """Call the LLM with automatic retry logic."""
        if not self._llm:
            raise RuntimeError("llm not initialized")

        model_name = self.get_current_model_name() or "unknown"
        
        # Determine provider from model name
        provider = settings.infer_provider_from_model(model_name)
        provider_str = provider.value if provider else settings.ACTIVE_LLM_PROVIDER.value
        
        trace_context = capture_current_trace_context()
        
        try:
            import time
            start_time = time.time()
            
            with record_llm_call(
                "llm.chat",
                model=model_name,
                provider=provider_str,
                input_messages=[_safe_dump_message(m) for m in messages[:5]],  # Sample first 5
                trace_context=trace_context,
                metadata={
                    "message_count": len(messages),
                    "temperature": getattr(self._llm, 'temperature', None),
                    "max_tokens": getattr(self._llm, 'max_tokens', None),
                },
            ):
                response = await self._llm.ainvoke(messages, config=config)
                duration_ms = (time.time() - start_time) * 1000
                
                # Update span with response and performance metrics
                update_current_span(
                    output=_safe_response_dump(response),
                    metadata={
                        "duration_ms": round(duration_ms, 2),
                        "tokens_estimated": len(str(response.content).split()) if response.content else 0,
                    },
                )
                
                logger.debug("llm_call_successful", message_count=len(messages), duration_ms=round(duration_ms, 2))
                return response
                
        except (RateLimitError, APITimeoutError, APIError) as e:
            duration_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
            update_current_span(
                level="ERROR",
                status_message=str(e),
                metadata={"duration_ms": round(duration_ms, 2)} if duration_ms else None,
            )
            logger.warning(
                "llm_call_failed_retrying",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise
        except OpenAIError as e:
            duration_ms = (time.time() - start_time) * 1000 if 'start_time' in locals() else None
            update_current_span(
                level="ERROR",
                status_message=str(e),
                metadata={"duration_ms": round(duration_ms, 2)} if duration_ms else None,
            )
            logger.error(
                "llm_call_failed",
                error_type=type(e).__name__,
                error=str(e),
            )
            raise

    async def call(
        self,
        messages: List[BaseMessage],
        model_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        **model_kwargs,
    ) -> BaseMessage:
        """Call the LLM with the specified messages and circular fallback."""
        if model_name:
            try:
                self._llm = self._create_bound_llm(model_name, **model_kwargs)
                all_names = LLMRegistry.get_all_names()
                if model_name in all_names:
                    self._current_model_index = all_names.index(model_name)
                logger.info("using_requested_model", model_name=model_name, has_custom_kwargs=bool(model_kwargs))
            except ValueError as e:
                logger.error("requested_model_not_found", model_name=model_name, error=str(e))
                raise
        elif model_kwargs and self._llm:
            current_model_name = self.get_current_model_name()
            if current_model_name:
                self._llm = self._create_bound_llm(current_model_name, **model_kwargs)

        total_models = len(LLMRegistry.get_all_names())
        if total_models == 0:
            raise RuntimeError("no llm models are configured. set OPENAI_API_KEY or DEEPSEEK_API_KEY")

        models_tried = 0
        starting_index = self._current_model_index
        last_error = None

        while models_tried < total_models:
            try:
                response = await self._call_llm_with_retry(messages, config=config)
                return response
            except OpenAIError as e:
                last_error = e
                models_tried += 1

                current_model_name = self.get_current_model_name() or "unknown"
                logger.error(
                    "llm_call_failed_after_retries",
                    model=current_model_name,
                    models_tried=models_tried,
                    total_models=total_models,
                    error=str(e),
                )

                if models_tried >= total_models:
                    starting_model_name = LLMRegistry.get_model_at_index(starting_index)["name"]
                    logger.error(
                        "all_models_failed",
                        models_tried=models_tried,
                        starting_model=starting_model_name,
                    )
                    break

                if not self._switch_to_next_model():
                    logger.error("failed_to_switch_to_next_model")
                    break

        raise RuntimeError(
            f"failed to get response from llm after trying {models_tried} models. last error: {str(last_error)}"
        )

    def get_current_model_name(self) -> Optional[str]:
        """Get the current model name if available."""
        all_names = LLMRegistry.get_all_names()
        if 0 <= self._current_model_index < len(all_names):
            return all_names[self._current_model_index]
        if self._llm and hasattr(self._llm, "model_name"):
            return self._llm.model_name
        return None

    def get_llm(self) -> Optional[BaseChatModel]:
        """Get the current LLM instance."""
        return self._llm

    def bind_tools(self, tools: List) -> "LLMService":
        """Bind tools to the current and future LLM instances."""
        self._bound_tools = list(tools)
        if self._llm:
            self._llm = cast(BaseChatModel, self._llm.bind_tools(self._bound_tools))
            logger.debug("tools_bound_to_llm", tool_count=len(self._bound_tools))
        return self


# Create global LLM service instance
llm_service = LLMService()
