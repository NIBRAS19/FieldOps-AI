"""Investigation workflow. Pure and DB-free so it is unit-testable and reusable by the evaluation runner.

Nodes: input_validation -> classification -> retrieval -> evidence_filter -> plan_generation ->
schema_validation -> policy_check -> approval_creation -> completion.
(The graph is explicit and small; it maps 1:1 onto a LangGraph StateGraph if you later adopt it.)"""
import time
from dataclasses import dataclass, field

from app.ai.model_adapter import ModelAdapter, ProviderTimeout
from app.ai.retrieval import ChunkRef, search, tokenize
from app.domain.enums import ActionType
from app.domain.policy import FORBIDDEN_INTENT, INJECTION, TRANSITIONS, risk_for, validate_payload
from app.observability.logging import redact

WORKFLOW_VERSION = "wf-1.0.0"
PROMPT_VERSION = "prompt-2026.10"
TEAM_BY_CATEGORY = {"connectivity": "Network Ops", "access": "Identity & Access", "device": "Device Support",
                    "application": "App Support", "request": "Service Desk", "other": "Service Desk"}
CAT_WORDS = {
    "connectivity": "vpn wifi wireless network connect connection internet drops",
    "access": "access permission password mfa login authenticator account folder sharepoint",
    "device": "laptop battery charging screen device keyboard boot charger",
    "application": "application app crash crashes software excel license workbook macro",
    "request": "request order monitor hardware hire peripheral",
}


@dataclass
class TicketIn:
    display_id: str
    title: str
    description: str
    priority: str = "medium"
    status: str = "new"
    assignee_id: str | None = None
    team_name: str | None = None
    customer_alias: str | None = None
    asset_tag: str | None = None


@dataclass
class PipelineConfig:
    top_k: int = 4
    max_retries: int = 2


@dataclass
class Ctx:
    ticket: TicketIn
    chunks: list[ChunkRef]            # already filtered by workspace, active status and role (FR-043)
    excluded_sources: int
    eligible_sources: int
    related_cases: int
    teams: dict[str, str]             # team name -> team id
    default_assignees: dict[str, str | None]
    model: ModelAdapter
    cfg: PipelineConfig = field(default_factory=PipelineConfig)
    role: str = "agent"
    fault: str = "none"


@dataclass
class EventDraft:
    step: str
    status: str
    detail: str
    duration_ms: int = 1
    attempt: int | None = None
    source_ids: list[str] = field(default_factory=list)
    error_code: str | None = None


@dataclass
class ProposalDraft:
    action_type: str
    payload: dict
    summary: str
    rationale: str
    expected_effect: str
    rollback_note: str
    evidence_ids: list[str]


@dataclass
class Result:
    outcome: str                      # ready | blocked | failed
    events: list[EventDraft]
    output: dict | None = None
    drafts: list[ProposalDraft] = field(default_factory=list)
    error_code: str | None = None
    retrieved_keys: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)


def sanitize(s: str) -> str:
    return redact(s)[:4000]


def classify(text: str) -> tuple[str, int]:
    toks = tokenize(text)
    best, hits = "other", 0
    for cat, words in CAT_WORDS.items():
        n = sum(1 for w in words.split() if w in toks)
        if n > hits:
            best, hits = cat, n
    return best, hits


def validate_plan(plan: dict, retrieved: set[str]) -> list[str]:
    e: list[str] = []
    if not plan.get("summary"):
        e.append("summary missing")
    if not isinstance(plan.get("steps"), list):
        return e + ["steps must be a list"]
    for s in plan["steps"]:
        for cid in s.get("evidence_ids", []):
            if cid not in retrieved:
                e.append(f"step {s.get('n')} cites unknown {cid}")
    return e


def run_pipeline(ctx: Ctx) -> Result:
    t = ctx.ticket
    events: list[EventDraft] = []
    clock = [time.perf_counter()]

    def ev(step: str, status: str, detail: str, **kw):
        now = time.perf_counter()
        events.append(EventDraft(step, status, detail, max(1, round((now - clock[0]) * 1000)), **kw))
        clock[0] = time.perf_counter()

    def fail(code: str) -> Result:
        return Result("failed", events, error_code=code)

    text = sanitize(f"{t.title}. {t.description}")
    if not text.strip(". "):
        ev("input_validation", "error", "Ticket has no usable text.", error_code="invalid_input")
        return fail("invalid_input")
    ev("input_validation", "ok", f"Ticket {t.display_id} validated for role \"{ctx.role}\". Fields sanitized. "
       f"Asset context: {(t.asset_tag + ' (synthetic record)') if t.asset_tag else 'none'}. Related synthetic cases: {ctx.related_cases}.")

    category, hits = classify(text)
    urgency = t.priority
    ev("classification", "ok", f"Rule-based classifier: category \"{category}\" ({hits} keyword hits), urgency suggestion \"{urgency}\".")

    if ctx.fault == "retrieval":
        ev("retrieval", "error", "Evidence service unavailable (simulated fault). No citations were fabricated.", error_code="retrieval_unavailable")
        return fail("retrieval_unavailable")
    picked, candidates = search(text, ctx.chunks, ctx.cfg.top_k)
    ev("retrieval", "ok", f"Lexical retrieval, top-k={ctx.cfg.top_k}. Access/status filter applied first: {ctx.eligible_sources} sources eligible, "
       f"{ctx.excluded_sources} excluded. {candidates} candidate chunks, {len(picked)} selected.", source_ids=[c.key for c, _ in picked])
    retrieved = {c.key for c, _ in picked}

    quarantined = [c.key for c, _ in picked if INJECTION.search(c.text)]
    usable = [(c, s) for c, s in picked if c.key not in quarantined]
    limitations = ["No live endpoint or system check was performed; all context is synthetic."]
    dropped: set[str] = set()
    by_key = {c.key: c for c, _ in usable}
    for c, _ in usable:
        other = by_key.get(c.conflicts_with) if c.conflicts_with else None
        if other:
            older = c if c.source_version < other.source_version else other
            dropped.add(older.key)
            limitations.append(f"Conflicting guidance between {c.key} (v{c.source_version}) and {other.key} (v{other.source_version}). "
                               f"Newer version preferred; confirm with the {other.source_owner} owner.")
    usable = sorted([(c, s) for c, s in usable if c.key not in dropped], key=lambda x: x[0].key)
    ev("evidence_filter", "warn" if quarantined or dropped else "ok",
       f"{len(usable)} chunks kept. Quarantined as untrusted instructions: {', '.join(quarantined) or 'none'}. "
       f"Dropped for version conflict: {', '.join(sorted(dropped)) or 'none'}.", source_ids=[c.key for c, _ in usable])
    if quarantined:
        limitations.append(f"Untrusted instruction-like content in {', '.join(quarantined)} was treated as data and excluded.")

    evidence = [{"source_id": c.source_key, "chunk_id": c.key, "claim_supported": c.section, "snippet": c.text,
                 "title": c.source_title, "source_version": c.source_version, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                for c, _ in usable]
    needs_more = not usable
    if needs_more:
        limitations.append("No adequate evidence found. The plan asks for clarification instead of guessing.")

    plan = None
    attempts = ctx.cfg.max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            plan = ctx.model.generate_plan(title=t.title, customer=t.customer_alias or "there", evidence=evidence, attempt=attempt)
            ev("plan_generation", "ok", f"{ctx.model.provider}/{ctx.model.model} returned a structured plan ({len(plan['steps'])} steps, {len(evidence)} citations).", attempt=attempt)
            break
        except ProviderTimeout:
            ev("plan_generation", "error", f"Provider timeout on attempt {attempt}/{attempts}.", attempt=attempt, error_code="provider_timeout")
    if plan is None:
        return Result("failed", events, error_code="provider_timeout", retrieved_keys=sorted(retrieved), quarantined=quarantined)

    errs = validate_plan(plan, retrieved)
    if errs:
        ev("schema_validation", "warn", f"Validation failed: {'; '.join(errs)}. Attempting one bounded repair.", attempt=1)
        try:
            plan = ctx.model.generate_plan(title=t.title, customer=t.customer_alias or "there", evidence=evidence, attempt=2)
        except ProviderTimeout:
            plan = {}
        if not plan or validate_plan(plan, retrieved):
            ev("schema_validation", "error", "Repair failed. Returning safe 'unable to generate a validated plan' state.", attempt=2, error_code="schema_invalid")
            return Result("failed", events, error_code="schema_invalid", retrieved_keys=sorted(retrieved), quarantined=quarantined)
        ev("schema_validation", "ok", "Repair attempt produced a valid object. Citations verified against the retrieved set.", attempt=2)
    else:
        ev("schema_validation", "ok", "Output is schema-valid. Every citation exists in the retrieved, authorized set.")

    output = {
        "summary": plan["summary"],
        "classification": {"category": category, "urgency_suggestion": urgency, "confidence": round(min(0.9, 0.35 + 0.08 * hits), 2),
                           "rationale": f"Matched {hits} {category} keyword(s) in the ticket text.",
                           "confidence_note": "Uncalibrated fixture estimate; not a probability."},
        "evidence": evidence, "recommended_steps": plan["steps"], "draft_response": plan["draft"],
        "action_proposals": [], "limitations": limitations, "needs_more_information": needs_more,
    }
    retrieved_list = sorted(retrieved)

    if FORBIDDEN_INTENT.search(text):
        limitations.append("Request includes operations outside the tool allowlist (refund, deletion, or credential disclosure). "
                           "No action was proposed; escalate to a human lead.")
        ev("policy_check", "blocked", "Blocked: ticket requests operations that are not on the tool allowlist. No proposals created.", error_code="policy_blocked")
        ev("approval_creation", "ok", "0 proposals created.")
        ev("completion", "blocked", "Run finished as blocked. Ticket not changed.")
        return Result("blocked", events, output, [], retrieved_keys=retrieved_list, quarantined=quarantined)

    ev_ids = [c.key for c, _ in usable]
    drafts: list[ProposalDraft] = []
    if needs_more:
        drafts.append(ProposalDraft(ActionType.request_more_information, {"text": plan["draft"]}, "Ask the requester for missing details",
                                    "Evidence was insufficient to recommend steps.", "Stores the request locally and sets the ticket to awaiting_information. Nothing is sent.",
                                    "Move the ticket back to in_progress.", []))
    else:
        note = f"AI investigation summary: {plan['summary']} Evidence: {', '.join(ev_ids)}. Human review required."
        drafts.append(ProposalDraft(ActionType.add_internal_note, {"text": note[:1500]}, "Save investigation summary as internal note",
                                    "Keeps the evidence trail with the ticket.", "Adds one internal note to the local ticket.", "Notes are append-only; add a correcting note.", ev_ids))
        drafts.append(ProposalDraft(ActionType.draft_customer_reply, {"text": plan["draft"][:1500]}, "Store the reply draft for the requester",
                                    "Draft is built from the cited steps.", "Stores an approved draft locally. Not sent.", "Replace the draft with a new one.", ev_ids))
        team = TEAM_BY_CATEGORY[category]
        if category != "other" and team in ctx.teams and (not t.assignee_id or t.team_name != team):
            p = {"team_id": ctx.teams[team]}
            if ctx.default_assignees.get(team):
                p["assignee_id"] = ctx.default_assignees[team]
            drafts.append(ProposalDraft(ActionType.assign_ticket, p, f"Assign to {team}", f"Category \"{category}\" is handled by {team}.",
                                        "Updates assignee and team on the local ticket.", "Reassign to the previous owner.", ev_ids))
        if t.status == "new":
            drafts.append(ProposalDraft(ActionType.change_local_status, {"to": "in_progress"}, "Move ticket to in_progress",
                                        "Investigation produced actionable steps.", "Status becomes in_progress.", "Move to awaiting_information if the requester must respond.", ev_ids))
        resolvable = [c.key for c, _ in usable if "resolvable" in c.tags]
        if t.status == "in_progress" and resolvable:
            drafts.append(ProposalDraft(ActionType.change_local_status, {"to": "resolved"}, "Move ticket to resolved",
                                        "A cited procedure says the ticket may be resolved after requester confirmation.",
                                        "Status becomes resolved and SLA tracking ends.", "Reopen by moving resolved to in_progress.", resolvable))

    kept, msgs = [], []
    for d in drafts:
        clean, errors = validate_payload(d.action_type, d.payload)
        if d.action_type == ActionType.change_local_status and clean.get("to") not in TRANSITIONS.get(t.status, set()):
            errors.append(f"Transition {t.status} -> {clean.get('to')} is not allowed.")
        if errors:
            msgs.append(f"{d.action_type}: {' '.join(errors)}")
        else:
            d.payload = clean
            kept.append(d)
    risks = ", ".join(risk_for(k.action_type, k.payload)[0] for k in kept) or "n/a"
    ev("policy_check", "warn" if msgs else "ok", f"{len(kept)}/{len(drafts)} proposals passed allowlist, schema and transition checks. Risk classes: {risks}."
       + (f" Dropped: {' | '.join(msgs)}" if msgs else ""))
    ev("approval_creation", "ok", f"{len(kept)} pending approval(s) will be created. Nothing is executed without a human decision.")
    ev("completion", "ok", "Investigation complete. This does not mean the ticket is resolved.")
    return Result("ready", events, output, kept, retrieved_keys=retrieved_list, quarantined=quarantined)
