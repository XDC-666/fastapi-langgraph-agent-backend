# FastAPI + LangGraph Backend Hardening Design

## Goal

Harden the existing FastAPI + synchronous SQLAlchemy + LangGraph application without replacing its architecture. Make LangGraph execution consistently asynchronous, enforce tenant isolation in RAG, close error/validation/authentication boundaries, make document replacement deterministic, and make the Docker/Alembic/frontend deployment path coherent and testable.

## Constraints

- Keep FastAPI, synchronous SQLAlchemy, LangGraph, Chroma, and the existing API surface.
- Do not rewrite the ORM to async SQLAlchemy.
- Isolate synchronous database work from async request/event-loop paths.
- Do not add unrelated product features or broad refactors.
- Restore the deleted baseline test suite and add regression coverage for every hardened boundary.
- Prefer generic client-facing errors; detailed exception information remains server-side only.

## Design

### Chat / LangGraph

`/api/v1/chat` becomes an async endpoint and the service uses `graph.ainvoke()` instead of `graph.invoke()`. Synchronous SQLAlchemy work (conversation/history assembly and persistence) runs through FastAPI's threadpool helper. Streaming continues to use `graph.astream()` and also keeps synchronous ORM work off the event loop.

RAG context assembly always passes the authenticated `user_id`. `retrieve_for_query` requires `owner_id` at the Python signature level so a future unscoped service call fails immediately rather than silently querying the whole collection.

Token usage is accumulated across all model messages/chunks produced during one Agent turn, including tool-call loops, rather than taking only the last model response.

### Knowledge base

Upload reads are bounded to a configured maximum plus one byte and reject unsupported extensions before parsing. Empty uploads and documents that parse to no meaningful text are rejected. Query `k` is constrained at the schema boundary.

Before adding replacement chunks for the same `(owner_id, filename)`, Chroma deletes the previous matching vectors. Metadata filters always include `owner_id`.

### Authentication / health / streaming errors

JWT subjects are converted to integer inside an explicit validation boundary; malformed subjects yield the existing standardized 401 response.

SSE failures log the exception server-side and emit a stable generic error message without `str(exc)`.

The async health endpoint executes the synchronous SQLAlchemy probe in a threadpool and reports `ok` only when both database and Redis probes succeed; otherwise it reports `degraded` with per-dependency booleans.

### Deployment / frontend

The Docker image includes `alembic.ini`, migration scripts, and the static frontend. A `.dockerignore` removes VCS, virtual environments, caches, and local data from the build context.

FastAPI serves the frontend under `/app/`, avoiding the broken `file://` + relative `/api/v1` workflow. Documentation directs users to the served frontend instead of opening the HTML file directly.

Dependency ranges gain conservative upper bounds on compatibility-sensitive framework/AI packages so future major-version releases do not silently change the environment. No lockfile is fabricated without a resolver run.

## Verification

Regression tests cover async non-stream invocation, RAG owner isolation, SSE error sanitization, upload limits/validation, token aggregation, malformed JWT subjects, health threadpool behavior, Chroma replacement cleanup, static frontend routing, and Docker/Alembic file inclusion. Verification also includes Python bytecode compilation, Alembic script discovery/offline checks when possible, Ruff when available, full pytest when dependencies are available, and Docker Compose smoke testing when Docker is available.
