# FieldOps AI — Frontend (Vue 3 + TypeScript + Vite)

Frontend for the **FieldOps AI** portfolio MVP described in `FieldOps_AI_Full_PRD.md`.
Status: **proposed portfolio project, synthetic data, mock actions only.** No backend exists yet.

## Run
```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build
```

## What is implemented (all 13 PRD screens)
Demo access/role picker · Overview · Ticket queue (URL-synced filters, sort, pagination, create modal) · Ticket workspace (AI panel, evidence drawer, related cases, notes) · Run detail (persisted-event timeline, step drawer, compare, labels) · Review inbox · Action review (approve / edit & approve with diff / reject, confirmation dialogs) · Knowledge library (chunks, test query, activate/deactivate) · Evaluations (23 cases, metric definitions, compare) · Run history · Audit log · Settings (policy, simulated faults, connectors, roles, reset) · Guided demo.

## Important: the backend is simulated in the browser
`src/mock/` is a local **fixture-mode engine**, not a real API, so the full flow works today:
- `pipeline.ts` — deterministic investigation workflow (classify → lexical retrieval → evidence filter → plan → schema validation → policy check → proposals), including quarantine of instruction-like chunks, version-conflict handling, forbidden-intent blocking, and simulated provider timeout / malformed output / retrieval failure.
- `policy.ts` — tool allowlist, payload validation, restricted status transitions, risk classes, approval permissions, content hash.
- `engine.ts` — state, audit log, approvals (hash check, expiry, idempotency, duplicate-decision block, edit versioning) and the mock execution adapter. State persists in `localStorage`.
- `evals.ts` — 23 synthetic cases run against the real pipeline/engine code.

Authorization here is client-side and **demonstrates the rules only**. The PRD requires the real backend to enforce them (section 4.3). When you build the FastAPI backend, replace `src/mock/engine.ts` with an API client and keep the views.

## Demo path
1. Enter as *Lena Lead* → Tickets → **FO-1001** → Investigate. Open a citation; note the quarantined community tip.
2. Reviews → open the internal-note proposal → Approve. Only the local record changes.
3. Runs → trace; Audit Log → `simulated_execution`.
4. Evaluations → Run suite; inspect E14 (blocked) and the approval cases.
