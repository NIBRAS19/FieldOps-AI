# FieldOps AI — Backend (FastAPI)

Backend for the **FieldOps AI** portfolio MVP (`FieldOps_AI_Full_PRD.md`). **Proposed portfolio project: synthetic data, simulated integrations, human-approved actions only.** No business impact or production use is claimed.

## Quick start (local, SQLite)
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
alembic upgrade head && python -m app.db.seed_cli
uvicorn app.main:app --reload          # docs at http://localhost:8000/docs
pytest                                  # 30 tests
```
## Docker (PostgreSQL)
```bash
cp .env.example .env   # set SECRET_KEY
docker compose up --build
```
## Demo flow (curl)
1. `GET /api/v1/auth/demo-users` → pick a user id (simulated auth, **not** identity verification)
2. `POST /api/v1/auth/demo-login {"user_id": ...}` → bearer token
3. `POST /api/v1/tickets/FO-1001/investigations {}` → 202; poll `/investigations/{id}` and `/investigations/{id}/events`
4. `GET /api/v1/action-proposals?status=pending` → `POST /action-proposals/{id}/approve {"payload_hash": ...}`
5. `GET /tickets/FO-1001/events`, `GET /audit-events`, `POST /evaluations/runs {}`

## API surface (all under `/api/v1`)
health (`/health/live`, `/health/ready`) · auth (`/auth/demo-users`, `/auth/demo-login`, `/me`) · `/overview` · tickets (list/create/detail/events/notes/assignment) · investigations (start/list/get/events/cancel/retry/label) · action-proposals (list/get/approve/edit-approve/reject/retry-execution) · knowledge (sources, versions, status, reindex, search) · evaluations (datasets, runs) · `/audit-events` · admin (config, users/role, demo-reset). Errors use `{"error":{"code","message","correlation_id"}}`.

## Roles (server-enforced, `app/security/rbac.py`)
admin · lead · agent · readonly — agents see only tickets assigned to them or owned by their team; agents cannot approve their own high-risk proposals; read-only cannot change anything.

## Layout
`app/api` routes · `app/core` config/deps/errors · `app/domain` enums+policy · `app/services` business logic · `app/ai` pipeline, retrieval, model adapter, eval runner · `app/integrations` adapters (mock only) · `app/db` models/seed · `alembic/` migrations · `data/evals` versioned eval cases · `docs/` architecture + threat model · `tests/` unit, integration, security.

## Honest status
Verified here: 30 automated tests pass (SQLite), migration upgrade/check/downgrade, a live uvicorn smoke run with progressive run events, 23/23 synthetic evaluation cases.
**Not verified:** PostgreSQL runtime (compose file and JSONB variants are written but untested here), Docker build, load behavior, any live model provider (not implemented). See `docs/architecture.md` for deliberate PRD deviations (no LangGraph, no pgvector, in-process background tasks, fixture model only).
