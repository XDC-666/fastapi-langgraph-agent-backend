# Backend Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Harden the existing FastAPI/LangGraph backend against async execution failures, cross-user RAG retrieval, deployment breakage, information leakage, unbounded uploads, usage undercounting, malformed JWTs, event-loop blocking, stale vectors, and frontend/deployment drift.

**Architecture:** Preserve synchronous SQLAlchemy and the existing API/models. Move LangGraph calls to async APIs, offload synchronous ORM probes/work from async paths, enforce RAG ownership at service signatures, and add bounded validation plus deterministic replacement semantics.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x, LangGraph, LangChain, Chroma, Alembic, pytest, Ruff, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-10-hardening-design.md`

## Global Constraints

- Keep FastAPI + synchronous SQLAlchemy + LangGraph; no async ORM rewrite.
- No unrelated feature work or broad project restructuring.
- Every behavioral fix gets regression coverage before or alongside the minimal production change.
- Client-facing streaming errors must not contain internal exception text.
- RAG retrieval always requires an authenticated owner id.

---

### Task 1: Restore the baseline test suite and establish regression scaffolding

**Files:**
- Restore: `tests/conftest.py`, `tests/test_basic.py`, `tests/test_chat.py`, `tests/test_login_lockout.py`, `tests/test_rate_limit.py`, `tests/test_usage.py`
- Create/Modify: focused tests under `tests/`

**Interfaces:**
- Consumes: uploaded Git index at `master` commit `fe8728f`
- Produces: baseline FakeGraph with async non-stream support and regression tests for hardened behavior

- [x] Restore deleted tracked tests from the Git index.
- [x] Change FakeGraph's non-stream test surface from synchronous `invoke()` to asynchronous `ainvoke()` so the tests fail against the old production call.
- [x] Add focused regression tests for RAG owner propagation, SSE sanitization, token aggregation, malformed JWT subject, upload validation, health offloading, vector replacement, frontend serving, and Docker migration assets.
- [x] Run the new tests; if dependency collection is blocked by the environment, record the exact missing dependency rather than treating it as a product failure.

### Task 2: Make non-stream chat async, tenant-scoped, and usage-complete

**Files:**
- Modify: `app/services/chat_service.py`
- Modify: `app/routers/chat.py`
- Modify: `app/services/usage_service.py`
- Test: `tests/test_chat.py`, `tests/test_usage.py`

**Interfaces:**
- Produces: `async def run_chat(...) -> tuple[int | None, str]`
- Produces: `merge_token_usage(current, new) -> tuple[int, int, int] | None`
- Produces: `extract_token_usage(*messages)` aggregating all message usage metadata

- [x] Verify regression tests fail because FakeGraph has no sync `invoke()` and because multi-message usage is undercounted.
- [x] Make `run_chat` async and execute conversation/history preparation plus persistence in the threadpool.
- [x] Replace `graph.invoke(...)` with `await graph.ainvoke(...)`.
- [x] Pass `owner_id=user_id` when assembling RAG context.
- [x] Aggregate usage across all result messages and all streaming model-call usage chunks.
- [x] Make the `/chat` route async and await `run_chat`.
- [x] Re-run focused tests.

### Task 3: Enforce RAG isolation, upload bounds, and deterministic replacement

**Files:**
- Modify: `app/config.py`
- Modify: `app/routers/knowledge.py`
- Modify: `app/services/knowledge_service.py`
- Create: `tests/test_knowledge.py`

**Interfaces:**
- Produces: `retrieve_for_query(query: str, owner_id: int, k: int = 3) -> str`
- Produces: configured upload byte limit and bounded `KnowledgeAsk.k`
- Produces: replacement delete filter for `(owner_id, source filename)` before `add_texts`

- [x] Add tests proving unscoped retrieval is impossible, owner filters are always applied, oversized/empty/unsupported uploads are rejected, `k` is bounded, and replacement deletes prior chunks before insertion.
- [x] Make `owner_id` required in `retrieve_for_query`.
- [x] Validate filename/extension and read at most `MAX_KNOWLEDGE_UPLOAD_BYTES + 1` bytes.
- [x] Reject empty bytes and parsed text with no non-whitespace content.
- [x] Constrain `k` with Pydantic `Field(ge=1, le=...)`.
- [x] Delete existing vectors matching owner and source before adding new chunks.
- [x] Re-run focused tests.

### Task 4: Harden SSE, authentication, and health behavior

**Files:**
- Modify: `app/routers/chat.py`
- Modify: `app/dependencies.py`
- Modify: `app/routers/health.py`
- Create/Modify: `tests/test_security_boundaries.py`, `tests/test_health.py`

**Interfaces:**
- Produces: stable generic SSE error payload
- Produces: malformed JWT `sub` -> HTTP 401
- Produces: synchronous `check_database()` helper invoked via threadpool

- [x] Add regression tests for internal exception redaction, non-integer JWT subjects, and event-loop-safe health DB probing.
- [x] Replace SSE `str(exc)` with a generic client message while retaining `logger.exception`.
- [x] Guard `int(user_id)` with `try/except (TypeError, ValueError)` and reject invalid/non-positive IDs.
- [x] Move the SQLAlchemy health probe into a sync helper and await it through `run_in_threadpool`.
- [x] Re-run focused tests.

### Task 5: Repair Docker/Alembic and frontend delivery

**Files:**
- Modify: `docker/Dockerfile`
- Create: `.dockerignore`
- Modify: `app/main.py`
- Modify: `frontend/index.html`
- Modify: `README.md`, `README_EN.md`
- Modify: `requirements.txt`, `pyproject.toml`
- Create/Modify: deployment/static tests

**Interfaces:**
- Produces: image containing `/app/alembic.ini`, `/app/alembic/`, and `/app/frontend/`
- Produces: frontend at `/app/` using same-origin `/api/v1`

- [x] Add static/deployment assertions that fail while Alembic assets/frontend are omitted and README recommends `file://` usage.
- [x] Copy migration config/scripts and frontend into the Docker image.
- [x] Add `.dockerignore` for `.git`, virtualenvs, caches, local data, logs, and editor files.
- [x] Mount the frontend with `StaticFiles` at `/app` and expose it from the root response.
- [x] Update both READMEs to use `http://localhost:8000/app/`.
- [x] Add conservative upper bounds for compatibility-sensitive dependencies in both dependency manifests without inventing a lockfile.
- [x] Re-run static/deployment assertions.

### Task 6: Full verification and artifact packaging

**Files:**
- Review all changed files and tests
- Package: corrected repository ZIP

**Interfaces:**
- Produces: verified source tree plus explicit verification report

- [x] Run `python -m compileall -q app tests`.
- [x] Run `ruff check app tests` when Ruff is available.
- [x] Run `pytest -q tests/` when runtime dependencies are available.
- [x] Run Alembic script discovery/offline validation that does not require a live DB.
- [x] Run Docker/Compose configuration or smoke tests when Docker is available.
- [x] Review `git diff --check` and semantic diff for unintended line-ending-only churn.
- [x] Package the hardened repository without the uploaded Windows `.venv` or runtime caches.


## Verification environment note

- Native `pytest -q tests/` cannot collect in this Linux sandbox because `langchain_core` and the rest of the project AI dependency stack are not installed, and outbound package installation is DNS-blocked.
- A test-only dependency shim outside the repository was used to exercise the application logic and FastAPI/SQLAlchemy integration offline; the repository suite passes 41/41 under that harness.
- `ruff` and Docker CLI are not installed in the sandbox, so Ruff and Docker Compose runtime smoke tests could not be executed here.
- Python compilation, TOML/YAML parsing, Alembic head discovery/offline SQL generation, dependency-range compatibility against the uploaded Windows `.venv` metadata, and `git diff --check` all succeed.
