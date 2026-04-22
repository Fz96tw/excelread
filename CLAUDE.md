# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

ExcelRead is a document intelligence and RAG (Retrieval-Augmented Generation) platform that:
- Monitors documents (Excel, SharePoint, Confluence, URLs) for changes
- Extracts and vectorizes content for semantic search via FAISS
- Serves a Flask web app with Microsoft OAuth for browsing and querying documents
- Uses AI summarization (local Ollama LLM or Claude/OpenAI API) to generate briefings
- Integrates with Jira, SharePoint, Google Sheets, and Confluence
- Exposes an MCP (Model Context Protocol) server for Claude Desktop integration

## Running the Application

```bash
# Start all services
docker-compose up -d

# Start only infrastructure (Redis, Ollama)
docker-compose -f docker-compose-infra.yml up -d

# View logs for a specific service
docker-compose logs -f ai-connector

# Rebuild a single image and restart
docker-compose up -d --build ai-connector
```

The main app runs on `http://localhost:5000`. Ollama on port 11434. Redis on port 6379. MCP server on port 5050.

## Running Python Services Locally (without Docker)

```bash
# Main Flask app
python3 appnew.py --port 7000 --auth user_auth --callback http://localhost:7000 --env dev

# File watcher
python file_watcher.py

# Celery workers (two separate queues, both must run)
celery -A vector_worker worker -Q resync_queue --loglevel=info
celery -A vector_worker worker -Q url_processing_queue --loglevel=info

# Scheduler
python scheduler.py

# Summarizer service (FastAPI, not Flask)
python summarizer.py
uvicorn summarizer:app --host 0.0.0.0 --port 8000
```

Redis must be running locally for Celery workers. Set `REDIS_HOST=localhost` when running outside Docker.

## Testing

There is no test framework configured. The only test file is `vector_retriever_test.py`, run directly:

```bash
python vector_retriever_test.py
```

## Architecture

### Services (docker-compose.yml)

| Service | File | Port | Role |
|---|---|---|---|
| `ai-connector` | `appnew.py` | 5000 | Main Flask web app + REST API |
| `file_watcher` | `file_watcher.py` | — | Watches `config/<user>/docs.json` for changes |
| `resync_worker` | `vector_worker.py` | — | Celery: re-embeds full documents (`resync_queue`) |
| `url_worker` | `vector_worker.py` | — | Celery: processes new URLs (`url_processing_queue`) |
| `summarizer` | `summarizer.py` | 8000 | LLM inference (Ollama/Claude/OpenAI) — FastAPI |
| `scheduler` | `scheduler.py` | — | APScheduler: periodic Jira/Confluence/SP syncs |
| `mcpserver` | `mcpserver.py` | 5050 | MCP HTTP server for Claude Desktop |
| `redis` | — | 6379 | Celery broker + app state store |
| `ollama` | — | 11434 | Local LLM (llama3.2-1b) |

### Data Flow

1. User adds a document URL via the web UI → stored in `config/<username>/docs.json`
2. `file_watcher.py` detects the change → pushes a task to Celery
3. `vector_worker.py` fetches, chunks, and embeds the document → writes FAISS index to `config/<username>/vectors/<url_hash>/`
4. User queries via web UI or MCP → `vector_retriever.py` / `vector_rag_retriever.py` searches FAISS → LLM generates a response

### Two Task Systems (Important Distinction)

There are two independent task systems that are easy to confuse:

- **Celery** (`vector_worker.py`, `task_queue.py` for config) — distributed, Redis-backed, survives restarts. Used for actual vector processing (`resync_task_worker` on `resync_queue`, `process_url` on `url_processing_queue`).
- **`task_queue.py` ThreadPool** — in-memory, local, thread-based. Used only for UI task status monitoring in `appnew.py`. Tasks are lost on app restart.

### Redis Database Layout

Redis uses three separate databases — always specify the correct one when debugging:

| DB | Purpose |
|---|---|
| 0 | Celery broker (task messages) |
| 1 | Celery backend (task results) |
| 2 | App state (`redis_state.py` — URL embedding status per user) |

```bash
redis-cli -n 2  # App state DB
```

State keys follow the pattern `user:{user_id}:url:{url}` with fields `status`, `embedding_updated_at`, `error`.

Per-user Celery task tracking sets also live in DB 2: `celery:tasks:<username>` (a Redis set of active task IDs). These are written by `/resync_sharepoint` and `/resync_docslist`, polled by `/tasks/status`, and have a 1-hour TTL matching `result_expires=3600` in `vector_worker.py`.

### Pluggable Embedders

Controlled by `EMBEDDER_TYPE` env var. **Switching embedders invalidates all existing FAISS indices** — full re-embedding required.

| Type | Env | Cost | Dims |
|---|---|---|---|
| `sentence_transformer` | (default) | Free, local | 384 |
| `openai` | `OPENAI_API_KEY` | $$, API | 1536 |
| `cohere` | `COHERE_API_KEY` | $$, API | 1024 |

Set `EMBEDDER_MODEL` to override the default model for any backend.

### MCP Server Authentication

All MCP requests require an `X-API-Key` header mapped to a username via `config/mcp.user.mapping.json`. Generate keys via `GET /get_new_mcp_key` in the main app. The mapping file is auto-created with example entries if missing.

### Key Files

- **`appnew.py`** — Main Flask app: OAuth, all REST endpoints, session management, UI routes. Production start: gunicorn with 4 workers, 8 threads, gthread worker class.
- **`refresh.py`** — Document sync orchestration: fetches/parses documents from all sources (SharePoint, Excel, Confluence, URLs) and triggers re-embedding. Called by both `scheduler.py` and Celery workers.
- **`vector_worker.py`** — Celery task definitions for both queues
- **`vector_embedder.py`** — Pluggable embedding strategies (SentenceTransformers, OpenAI, Cohere)
- **`vector_retriever.py`** — FAISS search; `vector_rag_retriever.py` adds deduplication/ranking
- **`file_watcher.py`** — Watchdog-based monitor; triggers Celery tasks on `docs.json` changes
- **`summarizer.py`** — FastAPI service wrapping Ollama; `summarizer_claude.py` and `summarizer_openai.py` for cloud variants
- **`aibrief.py`** — AI briefing generation logic (distinct from per-document summarization)
- **`mcp_proxy.py`** — HTTP-to-stdio bridge so Claude Desktop can reach the remote MCP server
- **`mcpserver.py`** — MCP server implementation exposing document retrieval as tools
- **`my_utils.py`** — Shared utilities: URL cleaning, Jira markup stripping, env file management, email sending
- **`redis_state.py`** — Thin wrapper around Redis DB 2 for URL embedding state
- **`task_queue.py`** — Celery app config + local ThreadPool task queue for UI monitoring

### Integration & Analytics Modules

Source-specific sync logic lives in dedicated files called by `refresh.py`:
- **`update_sharepoint.py`**, **`update_excel.py`**, **`update_googlesheet.py`** — per-source document fetchers
- **`read_jira.py`**, **`create_jira.py`** — Jira data extraction and ticket creation

Jira analytics are separate heavy modules (each 30–56KB), not part of the core RAG pipeline:
- **`cycletime.py`**, **`statustime.py`** — issue cycle/status time analytics
- **`runrate_assignee.py`**, **`runrate_created.py`**, **`runrate_resolved.py`** — run-rate reporting by dimension
- **`scope.py`** — scope tracking/analysis

### Frontend

`templates/` uses Jinja2 + vanilla JavaScript (no frontend build step). `form.html` is the main dashboard (~93KB); it polls `/tasks/status` via AJAX for real-time task updates. Static assets (logos, icons) are in `static/`.

### Legacy Files

`app.py` and `app2.py` are legacy Flask apps superseded by `appnew.py`. Do not modify or extend them.

### User Data Layout

```
config/
  <username>/
    docs.json            # User's document list (URL, metadata, sync settings)
    vectors/
      <url_hash>/
        index.faiss      # FAISS index for that document
        chunks.json      # Raw text chunks
        metadata.json    # Chunk metadata (source, page, etc.)
  mcp.user.mapping.json  # MCP API key → username mapping
  schedules.json         # APScheduler job definitions
```

### Authentication

Microsoft MSAL (Azure AD) OAuth2 flow. Credentials stored in `.env`. User sessions managed via Flask-Login + `session["user"]` dict from MSAL token. Google OAuth is a separate optional flow (`google_oauth_appnew.py`) used only for Google Sheets integration. No built-in token refresh — users must re-login on session expiry.

## Environment Variables

Key variables expected in `.env` (see `.env.bak` for reference):

- `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` — MSAL OAuth
- `FLASK_SECRET_KEY` — Flask session secret
- `REDIS_HOST` / `REDIS_URL` — Redis connection
- `OLLAMA_HOST` — Ollama endpoint (default: `http://ollama:11434`)
- `OLLAMA_MODEL` — Model name (default: `llama3.2:1b`)
- `SUMMARIZER_HOST` — Summarizer endpoint (default: `http://summarizer:8000`)
- `EMBEDDER_TYPE` — `sentence_transformer` | `openai` | `cohere`
- `EMBEDDER_MODEL` — Override default model for the selected embedder
- `ANTHROPIC_API_KEY` — For Claude-based summarization
- `OPENAI_API_KEY` — For OpenAI embeddings/summarization
- `COHERE_API_KEY` — For Cohere embeddings
- `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` — Jira integration
- `SHAREPOINT_*` — SharePoint credentials
- `CALLBACK` — OAuth callback URL (set to your public hostname in production)

## Known Gotchas

- **Ollama first-run**: First request to the summarizer will time out while the model downloads (~2 GB). This is expected.
- **Scheduler persistence**: APScheduler jobs are lost on container restart — no persisted state between runs.
- **docs.json must exist**: `file_watcher.py` does not auto-create `config/<username>/docs.json`; the file must exist before the watcher starts.
- **`task_queue.py` naming**: Despite the name, this file contains both the Celery app config AND a separate local `TaskQueue` class. They are unrelated.
