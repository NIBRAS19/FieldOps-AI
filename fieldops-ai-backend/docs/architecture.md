# Architecture (implemented)

Modular monolith (FastAPI + SQLAlchemy 2 + Pydantic v2). SQLite by default for local/test; PostgreSQL via `DATABASE_URL` (Docker Compose).

```
HTTP -> correlation-id middleware -> routes (app/api/v1) -> require(Perm) -> services -> DB
                                                         \-> investigations -> ai/pipeline (pure) -> model adapter (fixture)
                                                         \-> approvals -> integrations/mock adapter (local synthetic records only)
```
- `domain/policy.py` — allowlist, payload schemas, transitions, risk classes, payload hash, approval rules. The model never decides these.
- `ai/pipeline.py` — DB-free workflow: input_validation, classification, retrieval, evidence_filter, plan_generation, schema_validation, policy_check, approval_creation, completion. Each step is persisted as a `run_event`.
- `services/approvals.py` — atomic compare-and-set on `(status=pending, payload_hash, expires_at)`; decision is committed before execution; execution re-validates hash/schema/references/transition and uses a unique idempotency key.
- `integrations/mock/ticketing.py` — the only adapter. Server config (not the client) decides mock vs live.
- Run lifecycle: run row created `queued` first; FastAPI background task executes it; cancelled/interrupted runs end in a visible state (`recover_stale_runs` on startup).

## Deliberate deviations from the PRD recommendations
- **LangGraph not used.** The graph is a small explicit pipeline; it maps onto a StateGraph if adopted later.
- **No pgvector yet.** Lexical retrieval first, as the PRD recommends; add vectors only after a labeled retrieval eval set.
- **Model mode: fixture only.** Other modes return `MODEL_MODE_UNAVAILABLE`.
- **Background execution:** in-process task, not a durable queue (PRD allows this for the local demo). Process restart marks active runs `interrupted`.
- **Auth:** demo role-selector tokens only (`DEMO_AUTH_ENABLED`), refused at startup unless `DEMO_MODE=true`.
- **Ticket status enum** follows the PRD data model (`new, triaged, in_progress, awaiting_information, resolved, closed`).
