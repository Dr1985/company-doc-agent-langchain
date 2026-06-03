"""Custom middleware for tracking metrics and other cross-cutting concerns."""

from contextlib import nullcontext
import time
import uuid
from typing import Callable

from fastapi import Request
from starlette.datastructures import (
    Headers,
    MutableHeaders,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import (
    ASGIApp,
    Message,
    Receive,
    Scope,
    Send,
)

from src.system.logs import (
    bind_context,
    clear_context,
)
from src.system.telemetry import (
    http_request_duration_seconds,
    http_requests_total,
)
from src.system.tracing import (
    create_trace_id,
    get_trace_url,
    should_trace_request,
    start_trace_span,
    update_current_span,
    update_current_trace,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for tracking HTTP request metrics."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Track metrics for each request.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The response from the application
        """
        start_time = time.time()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            duration = time.time() - start_time

            # Record metrics
            http_requests_total.labels(method=request.method, endpoint=request.url.path, status=status_code).inc()

            http_request_duration_seconds.labels(method=request.method, endpoint=request.url.path).observe(duration)

        return response


class LoggingContextMiddleware:
    """ASGI middleware for request-scoped logging context and Langfuse tracing."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Bind request context and trace the full request lifecycle, including streaming."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        clear_context()

        state = scope.setdefault("state", {})
        path = scope.get("path", "/")
        method = scope.get("method", "GET")
        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        trace_id = create_trace_id(request_id) if should_trace_request(path) else None
        trace_url = get_trace_url(trace_id)
        request_metadata = {
            "http.method": method,
            "http.path": path,
            "client_ip": scope.get("client")[0] if scope.get("client") else None,
            "user_agent": headers.get("user-agent"),
            "request_id": request_id,
        }

        state["request_id"] = request_id
        if trace_id:
            state["trace_id"] = trace_id
        if trace_url:
            state["trace_url"] = trace_url

        bind_context(request_id=request_id, http_method=method, http_path=path)
        if trace_id:
            bind_context(trace_id=trace_id)

        status_code = 500
        start_time = time.perf_counter()
        span_name = f"http {method} {path}"

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
                if trace_id:
                    response_headers["X-Langfuse-Trace-ID"] = trace_id

            await send(message)

        error_message = None

        trace_span = (
            start_trace_span(
                span_name,
                trace_context={"trace_id": trace_id},
                input={"method": method, "path": path},
                metadata=request_metadata,
            )
            if trace_id
            else nullcontext()
        )

        with trace_span:
            if trace_id:
                update_current_trace(
                    name=span_name,
                    metadata=request_metadata,
                    tags=["http", method.lower()],
                )

            try:
                await self.app(scope, receive, send_wrapper)
            except Exception as exc:
                error_message = str(exc)
                raise
            finally:
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                update_current_span(
                    level="ERROR" if error_message else None,
                    status_message=error_message,
                    output={"status_code": status_code},
                    metadata={"duration_ms": duration_ms, "http.status_code": status_code},
                )
                clear_context()
