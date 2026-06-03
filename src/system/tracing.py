"""Langfuse tracing helpers.

This module centralizes Langfuse client creation and provides small helper
functions for request tracing, LangChain callback creation, and safe trace/span
updates. Tracing is automatically disabled when credentials are missing or the
feature is turned off via configuration.

Best Practices:
- Use trace IDs for correlating related operations
- Add meaningful metadata to traces and spans
- Use appropriate span hierarchy (trace -> span -> nested spans)
- Tag traces for better filtering and analysis
- Update traces with user context and session information
- Capture input/output for debugging and evaluation
- Set appropriate levels (INFO, WARNING, ERROR) for observability
"""

from contextlib import nullcontext
from functools import lru_cache
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.types import TraceContext

from src.config.settings import settings
from src.system.logs import logger

# Low-value paths that should not create Langfuse traces.
_UNTRACED_PATHS = {
    "/",
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    f"{settings.API_V1_STR}/health",
    f"{settings.API_V1_STR}/openapi.json",
}
_UNTRACED_PREFIXES = ("/docs", "/redoc")


@lru_cache(maxsize=1)
def get_langfuse_client() -> Optional[Langfuse]:
    """Return the shared Langfuse client when tracing is enabled."""
    if not settings.LANGFUSE_TRACING_ENABLED:
        return None

    if not settings.LANGFUSE_CONFIGURED:
        logger.warning(
            "langfuse_tracing_enabled_without_credentials",
            has_public_key=bool(settings.LANGFUSE_PUBLIC_KEY),
            has_secret_key=bool(settings.LANGFUSE_SECRET_KEY),
        )
        return None

    try:
        return Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            base_url=settings.LANGFUSE_BASE_URL,
            debug=settings.LANGFUSE_DEBUG,
            tracing_enabled=settings.LANGFUSE_TRACING_ENABLED,
            environment=settings.ENVIRONMENT.value,
            release=settings.LANGFUSE_RELEASE,
            sample_rate=settings.LANGFUSE_SAMPLE_RATE,
            flush_at=settings.LANGFUSE_FLUSH_AT,
            flush_interval=settings.LANGFUSE_FLUSH_INTERVAL,
        )
    except Exception as exc:
        logger.warning("langfuse_client_initialization_failed", error=str(exc), exc_info=True)
        return None


def is_langfuse_enabled() -> bool:
    """Return whether Langfuse tracing is available for the current process."""
    return get_langfuse_client() is not None


def should_trace_request(path: str) -> bool:
    """Return whether a request path should be traced."""
    normalized_path = (path or "/").rstrip("/") or "/"
    if normalized_path in _UNTRACED_PATHS:
        return False
    return not any(normalized_path.startswith(prefix) for prefix in _UNTRACED_PREFIXES)


def create_trace_id(seed: str) -> Optional[str]:
    """Create a stable Langfuse trace ID derived from a request seed."""
    client = get_langfuse_client()
    if not client:
        return None
    return client.create_trace_id(seed=seed)


def get_trace_url(trace_id: Optional[str]) -> Optional[str]:
    """Return the Langfuse trace URL for a trace ID when available.

    Fails gracefully — if the Langfuse API is unreachable or credentials
    are invalid, returns None instead of raising.
    """
    if not trace_id:
        return None

    client = get_langfuse_client()
    if not client:
        return None

    try:
        return client.get_trace_url(trace_id=trace_id)
    except Exception as exc:
        logger.warning(
            "langfuse_get_trace_url_failed",
            trace_id=trace_id,
            error=str(exc),
        )
        return None


def get_langchain_callbacks(
    update_trace: bool = False,
    trace_context: Optional[TraceContext] = None,
) -> List[CallbackHandler]:
    """Create per-request Langfuse LangChain callback handlers.
    
    Args:
        update_trace: Whether callbacks should update the current trace
        trace_context: Optional trace context to link callbacks to a specific trace
        
    Returns:
        List of CallbackHandler instances for LangChain integration
    """
    client = get_langfuse_client()
    if not client:
        return []

    return [
        CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            update_trace=update_trace,
        )
    ]


def start_trace_span(
    name: str,
    *,
    trace_context: Optional[TraceContext] = None,
    input: Optional[Any] = None,
    output: Optional[Any] = None,
    metadata: Optional[Any] = None,
    version: Optional[str] = None,
    level: Optional[str] = None,
    status_message: Optional[str] = None,
):
    """Start a Langfuse span if tracing is enabled, otherwise return a no-op context."""
    client = get_langfuse_client()
    if not client:
        return nullcontext()

    return client.start_as_current_span(
        trace_context=trace_context,
        name=name,
        input=input,
        output=output,
        metadata=metadata,
        version=version,
        level=level,
        status_message=status_message,
    )


def capture_current_trace_context() -> Optional[TraceContext]:
    """Capture the active Langfuse trace and parent observation context."""
    client = get_langfuse_client()
    if not client:
        return None

    trace_id = client.get_current_trace_id()
    if not trace_id:
        return None

    trace_context: TraceContext = {"trace_id": trace_id}
    observation_id = client.get_current_observation_id()
    if observation_id:
        trace_context["parent_span_id"] = observation_id

    return trace_context


def update_current_trace(
    *,
    name: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    version: Optional[str] = None,
    input: Optional[Any] = None,
    output: Optional[Any] = None,
    metadata: Optional[Any] = None,
    tags: Optional[List[str]] = None,
    public: Optional[bool] = None,
) -> None:
    """Safely update the active Langfuse trace if one exists."""
    client = get_langfuse_client()
    if not client or not client.get_current_trace_id():
        return

    client.update_current_trace(
        name=name,
        user_id=user_id,
        session_id=session_id,
        version=version,
        input=input,
        output=output,
        metadata=metadata,
        tags=tags,
        public=public,
    )


def update_current_span(
    *,
    name: Optional[str] = None,
    input: Optional[Any] = None,
    output: Optional[Any] = None,
    metadata: Optional[Any] = None,
    version: Optional[str] = None,
    level: Optional[str] = None,
    status_message: Optional[str] = None,
) -> None:
    """Safely update the active Langfuse span if one exists."""
    client = get_langfuse_client()
    if not client or not client.get_current_observation_id():
        return

    client.update_current_span(
        name=name,
        input=input,
        output=output,
        metadata=metadata,
        version=version,
        level=level,
        status_message=status_message,
    )


def check_langfuse_auth() -> Optional[bool]:
    """Verify Langfuse credentials when tracing is enabled."""
    client = get_langfuse_client()
    if not client:
        return None
    return client.auth_check()


def shutdown_langfuse() -> None:
    """Flush and close the Langfuse client when the app shuts down."""
    client = get_langfuse_client()
    if not client:
        return
    client.shutdown()


def record_llm_call(
    name: str,
    *,
    model: str,
    provider: str,
    input_messages: Any,
    output_message: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    trace_context: Optional[TraceContext] = None,
    duration_ms: Optional[float] = None,
    error: Optional[Exception] = None,
):
    """Record an LLM call as a Langfuse span with standardized metadata.
    
    This helper creates a span specifically for LLM calls with consistent
    metadata structure for better analysis in Langfuse.
    
    Args:
        name: Span name (e.g., 'llm.chat', 'llm.completion')
        model: The model name used
        provider: The LLM provider (e.g., 'openai', 'deepseek')
        input_messages: Input messages sent to the LLM
        output_message: Output message from the LLM (if available)
        metadata: Additional metadata (temperature, max_tokens, etc.)
        trace_context: Optional trace context
        duration_ms: Duration of the LLM call in milliseconds
        error: Optional error if the call failed
    """
    client = get_langfuse_client()
    if not client:
        return nullcontext()
    
    span_metadata = {
        "model": model,
        "provider": provider,
        **(metadata or {}),
    }
    
    if duration_ms is not None:
        span_metadata["duration_ms"] = duration_ms
    
    level = "ERROR" if error else None
    status_message = str(error) if error else None
    
    return client.start_as_current_span(
        trace_context=trace_context,
        name=name,
        input=input_messages,
        output=output_message,
        metadata=span_metadata,
        level=level,
        status_message=status_message,
    )


def record_tool_execution(
    tool_name: str,
    *,
    tool_args: Any,
    tool_result: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    trace_context: Optional[TraceContext] = None,
    duration_ms: Optional[float] = None,
    error: Optional[Exception] = None,
):
    """Record a tool execution as a Langfuse span.
    
    Args:
        tool_name: Name of the tool being executed
        tool_args: Arguments passed to the tool
        tool_result: Result from the tool execution
        metadata: Additional metadata about the tool execution
        trace_context: Optional trace context
        duration_ms: Duration of tool execution in milliseconds
        error: Optional error if execution failed
    """
    client = get_langfuse_client()
    if not client:
        return nullcontext()
    
    span_metadata = {
        "tool_name": tool_name,
        **(metadata or {}),
    }
    
    if duration_ms is not None:
        span_metadata["duration_ms"] = duration_ms
    
    level = "ERROR" if error else None
    status_message = str(error) if error else None
    
    return client.start_as_current_span(
        trace_context=trace_context,
        name=f"tool.{tool_name}",
        input=tool_args,
        output=tool_result,
        metadata=span_metadata,
        level=level,
        status_message=status_message,
    )


def add_score(
    name: str,
    value: float,
    *,
    comment: Optional[str] = None,
    trace_id: Optional[str] = None,
    observation_id: Optional[str] = None,
):
    """Add a score/evaluation to a trace or observation.
    
    Scores are useful for tracking quality metrics, user feedback,
    or automated evaluations.
    
    Args:
        name: Score name (e.g., 'user_rating', 'quality_score')
        value: Numeric score value
        comment: Optional comment explaining the score
        trace_id: ID of the trace to score
        observation_id: ID of the observation to score (optional)
    """
    client = get_langfuse_client()
    if not client:
        return
    
    try:
        client.score(
            trace_id=trace_id or client.get_current_trace_id(),
            observation_id=observation_id,
            name=name,
            value=value,
            comment=comment,
        )
    except Exception as exc:
        logger.warning("failed_to_add_score", name=name, error=str(exc))

