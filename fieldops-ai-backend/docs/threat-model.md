# Threat model (summary) — what is enforced and where it is tested

| Threat | Control | Test |
|---|---|---|
| Unauthenticated / forged token access | JWT (exp/iss/aud), role re-read from DB each request | `test_unauthenticated_and_bad_tokens`, `test_role_comes_from_database_not_token` |
| Missing role checks (UI-only) | `require(Perm)` on every protected route; denials audited | `test_role_enforcement_server_side` |
| IDOR / cross-tenant reads | Every query scoped by workspace; 404 for not-visible objects; agent object-level scope | `test_cross_workspace_isolation`, `test_agent_object_level_scope` |
| Client-supplied tenant/tools/prompt/simulation flag | Pydantic `extra="forbid"` | `test_client_cannot_inject_workspace_tools_or_simulation_flag` |
| Prompt injection in documents | Instruction-like chunks quarantined; model output never grants permissions | `test_pipeline_quarantines_injection_and_blocks_forbidden`, eval E12/E13 |
| Excessive agency (refund, delete, shell, credentials) | Tool allowlist; forbidden intent blocks the run; no proposals | eval E14/E15, `test_policy_blocked_and_insufficient_evidence` |
| Approval bypass / replay / stale approval | CAS on status+hash+expiry; self-approval rule; idempotency keys | `test_agent_cannot_approve_own_high_risk_proposal`, `test_stale_hash_and_expired_proposals_cannot_execute`, eval E20–E23 |
| Time-of-check/time-of-use on ticket state | Execution re-validates; optimistic ticket version | `test_state_change_after_review_fails_safely` |
| Audit tampering | ORM guard on update/delete (add DB-level triggers/permissions before production) | `test_audit_is_append_only` |
| Secret / PII leakage in logs or events | `redact()` on logs, run events, audit, notes; generic 500 errors | unit via flows |
| Abuse / cost | Per-user investigation rate limit; eval concurrency cap; request size limits | `test_rate_limit_on_investigations` |

Not covered yet: real authentication, DB-level audit immutability, durable job queue, live-provider data handling, load/performance testing, PostgreSQL CI run.
