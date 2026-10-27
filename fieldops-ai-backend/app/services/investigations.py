import hashlib
import json
import logging
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.model_adapter import get_adapter
from app.ai.pipeline import PROMPT_VERSION, WORKFLOW_VERSION, Ctx, PipelineConfig, TicketIn, run_pipeline
from app.core.config import get_settings
from app.core.errors import AppError
from app.db import models as m
from app.db.types import utcnow
from app.domain.enums import RunStatus
from app.domain.policy import payload_hash, risk_for, validate_payload
from app.observability.logging import redact
from app.services import audit, knowledge, tickets
from app.services.refs import check_refs

log = logging.getLogger("app.runs")
ACTIVE = (RunStatus.queued, RunStatus.running)


def start_run(session: Session, user: m.User, ticket: m.Ticket) -> m.InvestigationRun:
    """Create the durable run record BEFORE any model work so a failure is always inspectable."""
    s = get_settings()
    since = utcnow() - timedelta(minutes=1)
    recent = session.scalars(select(m.InvestigationRun.id).where(m.InvestigationRun.started_by == user.id, m.InvestigationRun.started_at >= since)).all()
    if len(recent) >= s.investigations_per_minute:
        audit.record(session, user.workspace_id, "investigation_rate_limited", "ticket", ticket.display_id, user=user, result="denied")
        session.commit()
        raise AppError("RATE_LIMITED", f"At most {s.investigations_per_minute} investigations per minute.", 429)
    active = session.scalar(select(m.InvestigationRun.id).where(m.InvestigationRun.ticket_id == ticket.id, m.InvestigationRun.status.in_(ACTIVE)))
    if active:
        raise AppError("RUN_IN_PROGRESS", "An investigation is already running for this ticket.", 409)
    ws = session.get(m.Workspace, user.workspace_id)
    cfg = ws.settings_json
    ih = hashlib.sha256(json.dumps([ticket.title, ticket.description, ticket.status, ticket.version], sort_keys=True).encode()).hexdigest()
    run = m.InvestigationRun(workspace_id=user.workspace_id, ticket_id=ticket.id, started_by=user.id, status=RunStatus.queued, model_provider="fixture",
                             model_name="fixture-v1", prompt_version=PROMPT_VERSION, workflow_version=WORKFLOW_VERSION, input_hash=ih,
                             retrieval_config={"mode": "lexical", "top_k": cfg.get("top_k", 4), "max_retries": cfg.get("max_retries", 2), "fault": cfg.get("fault", "none")})
    session.add(run)
    session.flush()
    audit.record(session, user.workspace_id, "investigation_started", "ticket", ticket.display_id, user=user, run_id=run.id,
                 reason=f"Run {run.id} queued (fixture mode{', fault=' + cfg['fault'] if cfg.get('fault', 'none') != 'none' else ''}).")
    session.commit()
    return run


def _build_ctx(session: Session, run: m.InvestigationRun, ticket: m.Ticket, starter: m.User) -> Ctx:
    chunks, eligible, excluded = knowledge.eligible_chunks(session, run.workspace_id, starter.role)
    users, teams = tickets.directory(session, run.workspace_id)
    team_ids = {t.name: t.id for t in teams.values()}
    defaults: dict[str, str | None] = {}
    for name, tid in team_ids.items():
        cand = [u for u in users.values() if u.team_id == tid and u.active and u.role in ("lead", "agent")]
        defaults[name] = sorted(cand, key=lambda u: u.role != "agent")[0].id if cand else None
    asset = session.get(m.Asset, ticket.asset_id) if ticket.asset_id else None
    related = len(session.scalars(select(m.HistoricalCase.id).where(m.HistoricalCase.workspace_id == run.workspace_id, m.HistoricalCase.category == ticket.category)).all())
    cfg = run.retrieval_config
    t_in = TicketIn(ticket.display_id, ticket.title, ticket.description, ticket.priority, ticket.status, ticket.assignee_id,
                    teams[ticket.team_id].name if ticket.team_id in teams else None, ticket.customer_alias, asset.asset_tag if asset else None)
    return Ctx(t_in, chunks, excluded, eligible, related, team_ids, defaults, get_adapter(get_settings().model_mode, cfg.get("fault", "none")),
               PipelineConfig(cfg.get("top_k", 4), cfg.get("max_retries", 2)), starter.role, cfg.get("fault", "none"))


def _finish_failed(session: Session, run: m.InvestigationRun, code: str, summary: str) -> None:
    run.status, run.error_code, run.error_summary, run.disposition = RunStatus.failed, code, summary[:300], "failed"
    run.finished_at = utcnow()
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    audit.record(session, run.workspace_id, "investigation_finished", "investigation_run", run.id, actor="system", result="failure", run_id=run.id, reason=f"{code}: {summary[:200]}")
    session.commit()


def execute_run(session: Session, run_id: str, step_delay_ms: int | None = None) -> m.InvestigationRun:
    """Runs the workflow, persists each step as a run_event, then creates pending proposals. Safe to call from a background task."""
    delay = get_settings().run_step_delay_ms if step_delay_ms is None else step_delay_ms
    run = session.get(m.InvestigationRun, run_id)
    if run is None or run.status != RunStatus.queued:
        return run
    res = session.execute(update(m.InvestigationRun).where(m.InvestigationRun.id == run_id, m.InvestigationRun.status == RunStatus.queued).values(status=RunStatus.running))
    session.commit()
    if res.rowcount != 1:
        return run
    session.refresh(run)
    ticket = session.get(m.Ticket, run.ticket_id)
    starter = session.get(m.User, run.started_by)
    try:
        ctx = _build_ctx(session, run, ticket, starter)
    except AppError as e:
        _finish_failed(session, run, e.code, e.message)
        return run
    except Exception as e:  # noqa: BLE001 - run must end in a visible failed state
        log.exception("run setup failed", extra={"run_id": run_id})
        _finish_failed(session, run, "internal_error", type(e).__name__)
        return run
    result = run_pipeline(ctx)
    for i, e in enumerate(result.events, 1):
        if delay:
            time.sleep(delay / 1000)
        session.refresh(run)
        if run.status == RunStatus.cancelled:
            return run  # cancelled by a user: stop; no proposals are created
        session.add(m.RunEvent(workspace_id=run.workspace_id, run_id=run.id, sequence_no=i, step_name=e.step, status=e.status, duration_ms=e.duration_ms,
                               input_summary_json={"attempt": e.attempt} if e.attempt else {}, output_summary_json={"detail": redact(e.detail)},
                               source_ids=e.source_ids, error_code=e.error_code))
        session.commit()
        log.info("step", extra={"event": "run_step", "run_id": run.id, "step": e.step, "status": e.status})
    session.refresh(run)
    if run.status == RunStatus.cancelled:
        return run
    if result.outcome == "failed":
        _finish_failed(session, run, result.error_code or "failed", "Run failed; no plan was produced and nothing was fabricated.")
        return run

    output = result.output or {}
    if result.outcome == "ready":
        for old in session.scalars(select(m.ActionProposal).where(m.ActionProposal.ticket_id == ticket.id, m.ActionProposal.status == "pending")):
            old.status, old.updated_at = "cancelled", utcnow()
            audit.record(session, run.workspace_id, "proposal_superseded", "action_proposal", old.id, actor="system", run_id=run.id, reason=f"Superseded by run {run.id}.")
        ws = session.get(m.Workspace, run.workspace_id)
        expiry = utcnow() + timedelta(minutes=int(ws.settings_json.get("approval_expiry_minutes", 30)))
        for idx, d in enumerate(result.drafts, 1):
            clean, errs = validate_payload(d.action_type, d.payload)
            errs += check_refs(session, run.workspace_id, d.action_type, clean)
            if errs:
                audit.record(session, run.workspace_id, "proposal_dropped", "action_proposal", f"{run.id}:{idx}", actor="agent", result="denied", run_id=run.id, reason="; ".join(errs)[:300])
                continue
            risk, why = risk_for(d.action_type, clean)
            p = m.ActionProposal(workspace_id=run.workspace_id, ticket_id=ticket.id, run_id=run.id, proposed_by=run.started_by, action_type=d.action_type, risk_class=risk,
                                 risk_reason=why, payload_json=clean, original_payload_json=clean, payload_hash=payload_hash(d.action_type, ticket.id, clean, 1),
                                 summary=d.summary, rationale=d.rationale, expected_effect=d.expected_effect, rollback_note=d.rollback_note, evidence_ids=d.evidence_ids,
                                 status="pending", expires_at=expiry, idempotency_key=f"prop:{run.id}:{idx}")
            session.add(p)
            session.flush()
            output["action_proposals"].append(p.id)
            audit.record(session, run.workspace_id, "proposal_created", "action_proposal", p.id, actor="agent", run_id=run.id,
                         after={"action_type": p.action_type, "risk": risk, "hash": p.payload_hash}, reason="Awaiting human approval. Nothing executed.")
    run.output_json = output
    has_props = bool(output.get("action_proposals"))
    run.status = RunStatus.awaiting_review if has_props else RunStatus.completed
    run.disposition = ("blocked" if result.outcome == "blocked" else "insufficient_evidence" if output.get("needs_more_information")
                       else "awaiting_approval" if has_props else "suggestion_only")
    run.finished_at = utcnow()
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    audit.record(session, run.workspace_id, "investigation_finished", "investigation_run", run.id, actor="system", run_id=run.id,
                 reason=f"Run ended as {run.status} ({run.disposition}).")
    session.commit()
    return run


def get_run(session: Session, user: m.User, run_id: str) -> m.InvestigationRun:
    run = session.scalar(select(m.InvestigationRun).where(m.InvestigationRun.id == run_id, m.InvestigationRun.workspace_id == user.workspace_id))
    if not run:
        raise AppError("NOT_FOUND", "Investigation not found.", 404)
    tickets.get_ticket(session, user, run.ticket_id)  # object-level check through the ticket
    return run


def list_runs(session: Session, user: m.User, *, status=None, ticket_id=None, started_by=None, error_code=None) -> list[m.InvestigationRun]:
    stmt = select(m.InvestigationRun).where(m.InvestigationRun.workspace_id == user.workspace_id).order_by(m.InvestigationRun.started_at.desc())
    if status:
        stmt = stmt.where(m.InvestigationRun.status == status)
    if started_by:
        stmt = stmt.where(m.InvestigationRun.started_by == started_by)
    if error_code:
        stmt = stmt.where(m.InvestigationRun.error_code == error_code)
    if ticket_id:
        stmt = stmt.where(m.InvestigationRun.ticket_id == tickets.get_ticket(session, user, ticket_id).id)
    visible = set(session.scalars(select(m.Ticket.id).where(*tickets.visibility(user))))
    return [r for r in session.scalars(stmt) if r.ticket_id in visible]


def run_events(session: Session, run: m.InvestigationRun) -> list[m.RunEvent]:
    return list(session.scalars(select(m.RunEvent).where(m.RunEvent.run_id == run.id).order_by(m.RunEvent.sequence_no)))


def cancel_run(session: Session, user: m.User, run_id: str) -> m.InvestigationRun:
    run = get_run(session, user, run_id)
    res = session.execute(update(m.InvestigationRun).where(m.InvestigationRun.id == run.id, m.InvestigationRun.status.in_(ACTIVE))
                          .values(status=RunStatus.cancelled, finished_at=utcnow(), disposition="cancelled"))
    if res.rowcount != 1:
        raise AppError("INVALID_STATE", "Only queued or running investigations can be cancelled.", 409)
    audit.record(session, user.workspace_id, "run_cancelled", "investigation_run", run.id, user=user, run_id=run.id, reason="Cancelled before any proposal was created.")
    session.commit()
    session.refresh(run)
    return run


def label_run(session: Session, user: m.User, run_id: str, label: str, reason: str) -> m.InvestigationRun:
    run = get_run(session, user, run_id)
    run.label, run.label_reason = label, redact(reason)[:300]
    audit.record(session, user.workspace_id, "run_labeled", "investigation_run", run.id, user=user, run_id=run.id, after={"label": label},
                 reason="Original run output unchanged.")
    session.commit()
    return run


def recover_stale_runs(session: Session) -> int:
    """A run left queued/running by a process restart must not stay 'running' forever."""
    stale = session.scalars(select(m.InvestigationRun).where(m.InvestigationRun.status.in_(ACTIVE))).all()
    for r in stale:
        r.status, r.error_code, r.error_summary, r.disposition, r.finished_at = RunStatus.failed, "interrupted", "Process restarted during run.", "failed", utcnow()
        audit.record(session, r.workspace_id, "run_interrupted", "investigation_run", r.id, actor="system", result="failure", run_id=r.id)
    session.commit()
    return len(stale)
