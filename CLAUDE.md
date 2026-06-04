# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Install dependencies
make install                 # pip install uv && uv sync

# Run (development — with hot reload)
make dev                     # sources .env.development, runs uvicorn --reload on port 8000

# Run (staging / production)
make staging
make prod

# Lint & format
make lint                    # ruff check .
make format                  # ruff format .

# Tests
pytest                       # run all tests
pytest -m "not slow"         # skip slow tests
pytest tests/test_retrieval.py -k "test_hybrid"  # run a single test

# Docker (full stack: app + PostgreSQL/pgvector + Prometheus + Grafana)
make docker-compose-up ENV=development
make docker-compose-down ENV=development

# Evaluation
make eval                    # interactive mode
make eval-quick              # default settings, no prompts
```

Package management uses **`uv`** (not pip). Dependencies live in `pyproject.toml`; lockfile is `uv.lock`.

## Architecture

This is a **RAG chatbot backend** — a Chinese-enterprise internal knowledge-base Q&A assistant built with FastAPI + LangGraph.

### Core request flow

1. **FastAPI** (`src/main.py`) — entry point, middleware (CORS, logging, metrics, rate-limiting), mounts API router and static frontend.
2. **API routes** (`src/interface/`) — three routers under `/api/v1/`:
   - `/auth/*` — register, login, session management (JWT + bcrypt)
   - `/chatbot/*` — sync chat (`/chat`) and SSE streaming (`/chat/stream`)
   - `/documents/*` — upload, list, sync, retrieve (MinIO-backed)
3. **LangGraph Agent** (`src/agent/workflow.py`) — the core agent is a `StateGraph` with three nodes:
   ```
   retrieve → chat → (tool_call | END)
                ↑        │
                └────────┘
   ```
   - `retrieve` — hybrid search (pgvector cosine + BM25) with parent document recall
   - `chat` — LLM call with tools bound; system prompt switches between RAG and default based on whether context was retrieved
   - `tool_call` — executes tools (currently DuckDuckGo web search), feeds results back to chat
   - Checkpointer: `AsyncPostgresSaver` (persists conversation state in PostgreSQL)
   - Long-term memory: `mem0` AsyncMemory (pgvector-backed, stores user facts across sessions)

### Key subsystems

| Layer | Location | Role |
|-------|----------|------|
| LLM provider | `src/services/llm_provider.py` | Model registry + circular fallback (OpenAI → DeepSeek → OpenRouter) |
| Embedding | `src/embedding/qwen_embedding.py` | Qwen text-embedding-v4 via DashScope (batched HTTP) |
| Retrieval | `src/retrieval/` | Vector (pgvector), BM25 (in-memory), hybrid RRF fusion |
| Ingestion | `src/ingestion/pipeline.py` | Upload → PDF/DOCX/TXT parse → chunk → embed → store in pgvector |
| Storage | `src/services/storage.py` | MinIO (S3-compatible) singleton |
| Database | `src/data/db_manager.py` | SQLModel singleton for user/session CRUD |
| Config | `src/config/settings.py` | Hand-written `Settings` class, loads `.env.{environment}` |
| Observability | `src/system/` | structlog, Prometheus metrics, Langfuse tracing, slowapi rate limiting |

### Design patterns

- **Module-level singletons**: `settings`, `db_manager`, `storage`, `qwen_embedding`, `retriever`, `bm25_retriever`, `llm_service`, `limiter` — all initialized once at import time.
- **FastAPI `Depends()`** for auth: JWT token → session → user, injected into route handlers.
- **Graceful degradation in production**: if PostgreSQL, Langfuse, or LLM are unavailable, the app starts anyway and logs warnings rather than crashing.
- **Background ingestion**: document processing runs via FastAPI `BackgroundTasks` so the upload endpoint returns immediately.
- **Environment-aware config**: `Settings` loads from `.env.{APP_ENV}` (development/staging/production/test), with env-specific overrides (pool sizes, log levels, debug flags).

### Python version

Requires **Python ≥ 3.13**. Windows uses `WindowsSelectorEventLoopPolicy` for psycopg async compat (set in `src/main.py`).
