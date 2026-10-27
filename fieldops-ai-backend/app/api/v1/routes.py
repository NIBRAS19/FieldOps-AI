import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api import schemas as sc
from app.core.config import get_settings
from app.core.deps import current_user, require
from app.core.errors import AppError
from app.db import models as m
from app.db.session import get_session, session_factory
from app.security import tokens
from app.security.rbac import MATRIX, Perm
from app.services import admin, approvals, audit, evaluations, investigations, knowledge, tickets

log = logging.getLogger("app.api")
router = APIRouter(prefix="/api/v1")
S = Depends(get_session)


# ---------------------------------------------------------------- health / auth
@router.get("/health/live", tags=["health"])
def live():
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
def ready(session: Session = S):
    try:
        session.execute(text("SELECT 1"))
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "unavailable"
    if db != "ok":
        raise AppError("NOT_READY", "Database is unavailable.", 503)
    return {"status": "ok", "checks": {"database": db}, "model_mode": get_settings().model_mode, "connector_mode": "mock_only"}


def _demo_ws(session: Session) -> m.Workspace:
    s = get_settings()
    ws = session.scalar(select(m.Workspace).where(m.Workspace.mode == "demo").limit(1))
    if not (s.demo_mode and s.demo_auth_enabled) or not ws:
        raise AppError("NOT_FOUND", "Demo access is not enabled.", 404)
    return ws


@router.get("/auth/demo-users", tags=["auth"])
def demo_users(session: Session = S):
    ws = _demo_ws(session)
    rows = session.scalars(select(m.User).where(m.User.workspace_id == ws.id, m.User.active.is_(True))).all()
    return {"simulated_auth": True, "warning": "Demo access only. This is not identity verification.",
            "users": [{"id": u.id, "display_name": u.display_name, "role": u.role} for u in rows]}


@router.post("/auth/demo-login", tags=["auth"])
def demo_login(body: sc.DemoLogin, session: Session = S):
    ws = _demo_ws(session)
    u = session.scalar(select(m.User).where(m.User.id == body.user_id, m.User.workspace_id == ws.id, m.User.active.is_(True)))
    if not u:
        raise AppError("NOT_FOUND", "Demo user not found.", 404)
    audit.record(session, ws.id, "demo_login", "user", u.id, user=u, result="info", reason="Simulated demo access; not identity verification.")
    session.commit()
    token, ttl = tokens.issue(u.id, ws.id)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl, "simulated_auth": True}


@router.get("/me", tags=["auth"])
def me(user: m.User = Depends(current_user), session: Session = S):
    ws = session.get(m.Workspace, user.workspace_id)
    team = session.get(m.Team, user.team_id) if user.team_id else None
    return {"id": user.id, "display_name": user.display_name, "email": user.email, "role": user.role, "team": team.name if team else None,
            "permissions": sorted(p.value for p in MATRIX[user.role]), "workspace": {"id": ws.id, "name": ws.name, "mode": ws.mode},
            "simulated_auth": get_settings().demo_auth_enabled}


@router.get("/overview", tags=["overview"])
def overview(user: m.User = Depends(require(Perm.tickets_read)), session: Session = S):
    return admin.overview(session, user)


# ---------------------------------------------------------------- tickets
@router.get("/tickets", tags=["tickets"])
def list_tickets(q: str | None = None, status: str | None = None, priority: str | None = None, category: str | None = None, assignee_id: str | None = None,
                 ai_state: str | None = None, sla: str | None = None, sort: str = "priority", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 user: m.User = Depends(require(Perm.tickets_read)), session: Session = S):
    return tickets.list_tickets(session, user, q=q, status=status, priority=priority, category=category, assignee_id=assignee_id, ai_state=ai_state, sla=sla,
                                sort=sort, page=page, page_size=page_size)


@router.post("/tickets", status_code=201, tags=["tickets"])
def create_ticket(body: sc.TicketCreate, user: m.User = Depends(require(Perm.tickets_write)), session: Session = S):
    t = tickets.create_ticket(session, user, body.model_dump())
    session.commit()
    return tickets.detail(session, user, t.id)


@router.get("/tickets/{ticket_id}", tags=["tickets"])
def get_ticket(ticket_id: str, user: m.User = Depends(require(Perm.tickets_read)), session: Session = S):
    return tickets.detail(session, user, ticket_id)


@router.get("/tickets/{ticket_id}/events", tags=["tickets"])
def ticket_events(ticket_id: str, user: m.User = Depends(require(Perm.tickets_read)), session: Session = S):
    return {"items": tickets.events(session, user, ticket_id)}


@router.post("/tickets/{ticket_id}/notes", status_code=201, tags=["tickets"])
def add_note(ticket_id: str, body: sc.NoteIn, user: m.User = Depends(require(Perm.tickets_write)), session: Session = S):
    tickets.add_note(session, user, ticket_id, body.text)
    session.commit()
    return {"items": tickets.events(session, user, ticket_id)}


@router.put("/tickets/{ticket_id}/assignment", tags=["tickets"])
def assign(ticket_id: str, body: sc.AssignIn, user: m.User = Depends(require(Perm.tickets_write)), session: Session = S):
    t = tickets.assign_direct(session, user, ticket_id, body.assignee_id)
    session.commit()
    return tickets.detail(session, user, t.id)


# ---------------------------------------------------------------- investigations
def run_out(session: Session, r: m.InvestigationRun, with_output: bool = True) -> dict:
    t = session.get(m.Ticket, r.ticket_id)
    out = {"id": r.id, "ticket_id": r.ticket_id, "ticket_display_id": t.display_id, "started_by": r.started_by, "status": r.status, "disposition": r.disposition,
           "model_provider": r.model_provider, "model_name": r.model_name, "prompt_version": r.prompt_version, "workflow_version": r.workflow_version,
           "retrieval_config": r.retrieval_config, "error_code": r.error_code, "error_summary": r.error_summary, "label": r.label, "label_reason": r.label_reason,
           "eval_sample": r.eval_sample, "started_at": r.started_at, "finished_at": r.finished_at, "duration_ms": r.duration_ms,
           "token_usage": r.token_usage_json, "cost_estimate": r.cost_estimate}
    if with_output:
        out["output"] = r.output_json
    return out


def _background_execute(run_id: str) -> None:
    try:
        with session_factory()() as s:
            investigations.execute_run(s, run_id)
    except Exception:  # noqa: BLE001
        log.exception("background run crashed", extra={"run_id": run_id})
        with session_factory()() as s:  # never leave a run stuck as running
            r = s.get(m.InvestigationRun, run_id)
            if r and r.status in ("queued", "running"):
                investigations._finish_failed(s, r, "internal_error", "Unexpected error during run.")


@router.post("/tickets/{ticket_id}/investigations", status_code=202, tags=["investigations"])
def start_investigation(ticket_id: str, body: sc.StartInvestigation, bg: BackgroundTasks, user: m.User = Depends(require(Perm.investigate)), session: Session = S):
    t = tickets.get_ticket(session, user, ticket_id)
    run = investigations.start_run(session, user, t)
    bg.add_task(_background_execute, run.id)
    return run_out(session, run, with_output=False)


@router.get("/tickets/{ticket_id}/investigations", tags=["investigations"])
def ticket_runs(ticket_id: str, user: m.User = Depends(require(Perm.investigations_read)), session: Session = S):
    return {"items": [run_out(session, r, False) for r in investigations.list_runs(session, user, ticket_id=ticket_id)]}


@router.get("/investigations", tags=["investigations"])
def list_runs(status: str | None = None, ticket_id: str | None = None, started_by: str | None = None, error_code: str | None = None,
              user: m.User = Depends(require(Perm.investigations_read)), session: Session = S):
    return {"items": [run_out(session, r, False) for r in investigations.list_runs(session, user, status=status, ticket_id=ticket_id, started_by=started_by, error_code=error_code)]}


@router.get("/investigations/{run_id}", tags=["investigations"])
def get_run(run_id: str, user: m.User = Depends(require(Perm.investigations_read)), session: Session = S):
    r = investigations.get_run(session, user, run_id)
    ps = session.scalars(select(m.ActionProposal.id).where(m.ActionProposal.run_id == r.id)).all()
    return {**run_out(session, r), "proposal_ids": ps}


@router.get("/investigations/{run_id}/events", tags=["investigations"])
def run_events(run_id: str, user: m.User = Depends(require(Perm.investigations_read)), session: Session = S):
    r = investigations.get_run(session, user, run_id)
    return {"run_status": r.status, "items": [{"sequence_no": e.sequence_no, "step": e.step_name, "status": e.status, "duration_ms": e.duration_ms,
                                               "detail": e.output_summary_json.get("detail"), "attempt": e.input_summary_json.get("attempt"), "source_ids": e.source_ids,
                                               "error_code": e.error_code, "created_at": e.created_at} for e in investigations.run_events(session, r)]}


@router.post("/investigations/{run_id}/cancel", tags=["investigations"])
def cancel_run(run_id: str, user: m.User = Depends(require(Perm.investigate)), session: Session = S):
    return run_out(session, investigations.cancel_run(session, user, run_id), False)


@router.post("/investigations/{run_id}/retry", status_code=202, tags=["investigations"])
def retry_run(run_id: str, bg: BackgroundTasks, user: m.User = Depends(require(Perm.investigate)), session: Session = S):
    old = investigations.get_run(session, user, run_id)
    if old.status != "failed":
        raise AppError("INVALID_STATE", "Only failed runs can be retried.", 409)
    run = investigations.start_run(session, user, tickets.get_ticket(session, user, old.ticket_id))
    bg.add_task(_background_execute, run.id)
    return run_out(session, run, False)


@router.post("/investigations/{run_id}/label", tags=["investigations"])
def label_run(run_id: str, body: sc.LabelIn, user: m.User = Depends(require(Perm.label_runs)), session: Session = S):
    return run_out(session, investigations.label_run(session, user, run_id, body.label, body.reason), False)


# ---------------------------------------------------------------- proposals
@router.get("/action-proposals", tags=["proposals"])
def list_proposals(status: str | None = None, risk_class: str | None = None, proposed_by: str | None = None, ticket_id: str | None = None,
                   user: m.User = Depends(require(Perm.proposals_read)), session: Session = S):
    users, _ = tickets.directory(session, user.workspace_id)
    return {"items": [approvals.proposal_out(session, p, users) for p in approvals.list_proposals(session, user, status=status, risk=risk_class, proposed_by=proposed_by, ticket_id=ticket_id)]}


@router.get("/action-proposals/{pid}", tags=["proposals"])
def get_proposal(pid: str, user: m.User = Depends(require(Perm.proposals_read)), session: Session = S):
    approvals.expire_due(session, user.workspace_id)
    p = approvals.get_proposal(session, user, pid)
    users, _ = tickets.directory(session, user.workspace_id)
    return approvals.proposal_out(session, p, users)


def _decided(session: Session, user: m.User, p: m.ActionProposal) -> dict:
    users, _ = tickets.directory(session, user.workspace_id)
    return approvals.proposal_out(session, p, users)


@router.post("/action-proposals/{pid}/approve", tags=["proposals"])
def approve(pid: str, body: sc.ApproveIn, user: m.User = Depends(require(Perm.proposals_decide)), session: Session = S):
    return _decided(session, user, approvals.decide(session, user, pid, "approve", expected_hash=body.payload_hash, comment=body.comment))


@router.post("/action-proposals/{pid}/edit-approve", tags=["proposals"])
def edit_approve(pid: str, body: sc.EditApproveIn, user: m.User = Depends(require(Perm.proposals_decide)), session: Session = S):
    return _decided(session, user, approvals.decide(session, user, pid, "edit_approve", expected_hash=body.payload_hash, edited_payload=body.edited_payload, comment=body.comment))


@router.post("/action-proposals/{pid}/reject", tags=["proposals"])
def reject(pid: str, body: sc.RejectIn, user: m.User = Depends(require(Perm.proposals_decide)), session: Session = S):
    return _decided(session, user, approvals.decide(session, user, pid, "reject", expected_hash=body.payload_hash, reason_code=body.reason_code, comment=body.comment))


@router.post("/action-proposals/{pid}/retry-execution", tags=["proposals"])
def retry_execution(pid: str, user: m.User = Depends(require(Perm.proposals_decide)), session: Session = S):
    return _decided(session, user, approvals.retry_execution(session, user, pid))


# ---------------------------------------------------------------- knowledge
@router.get("/knowledge/sources", tags=["knowledge"])
def list_sources(user: m.User = Depends(require(Perm.kb_read)), session: Session = S):
    return {"items": knowledge.list_sources(session, user)}


@router.get("/knowledge/sources/{ident}", tags=["knowledge"])
def get_source(ident: str, user: m.User = Depends(require(Perm.kb_read)), session: Session = S):
    return knowledge.source_detail(session, user, ident)


@router.post("/knowledge/search", tags=["knowledge"])
def search(body: sc.SearchIn, user: m.User = Depends(require(Perm.kb_read)), session: Session = S):
    return {"items": knowledge.search_knowledge(session, user, body.query, body.top_k)}


@router.post("/knowledge/sources", status_code=201, tags=["knowledge"])
def create_source(body: sc.SourceCreate, user: m.User = Depends(require(Perm.kb_manage)), session: Session = S):
    s = knowledge.create_manual_source(session, user, body.title, body.text)
    session.commit()
    return knowledge.source_detail(session, user, s.id)


@router.post("/knowledge/sources/{ident}/versions", status_code=201, tags=["knowledge"])
def new_version(ident: str, body: sc.SourceVersion, user: m.User = Depends(require(Perm.kb_manage)), session: Session = S):
    s = knowledge.new_version(session, user, ident, body.text)
    session.commit()
    return knowledge.source_detail(session, user, s.id)


@router.put("/knowledge/sources/{ident}/status", tags=["knowledge"])
def set_source_status(ident: str, body: sc.SourceStatus, user: m.User = Depends(require(Perm.kb_manage)), session: Session = S):
    s = knowledge.set_status(session, user, ident, body.status)
    session.commit()
    return knowledge.source_detail(session, user, s.id)


@router.post("/knowledge/sources/{ident}/reindex", tags=["knowledge"])
def reindex(ident: str, user: m.User = Depends(require(Perm.kb_reindex)), session: Session = S):
    s = knowledge.reindex(session, user, ident)
    session.commit()
    return knowledge.source_detail(session, user, s.id)


# ---------------------------------------------------------------- evaluations
@router.get("/evaluations/datasets", tags=["evaluations"])
def datasets(user: m.User = Depends(require(Perm.eval_read)), session: Session = S):
    return {"items": evaluations.list_datasets(session, user)}


@router.post("/evaluations/runs", status_code=201, tags=["evaluations"])
def start_eval(body: sc.EvalStart, user: m.User = Depends(require(Perm.eval_run)), session: Session = S):
    return evaluations.run_out(session, evaluations.start_run(session, user, body.dataset_id))


@router.get("/evaluations/runs", tags=["evaluations"])
def eval_runs(user: m.User = Depends(require(Perm.eval_read)), session: Session = S):
    return {"items": [evaluations.run_out(session, r, False) for r in evaluations.list_runs(session, user)]}


@router.get("/evaluations/runs/{rid}", tags=["evaluations"])
def eval_run(rid: str, user: m.User = Depends(require(Perm.eval_read)), session: Session = S):
    return evaluations.run_out(session, evaluations.get_run(session, user, rid))


# ---------------------------------------------------------------- audit
READONLY_HIDDEN = {"demo_login", "config_changed", "role_changed", "permission_denied", "approval_denied"}


@router.get("/audit-events", tags=["audit"])
def audit_events(actor_id: str | None = None, event_type: str | None = None, target_id: str | None = None, result: str | None = None,
                 date_from: datetime | None = None, date_to: datetime | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                 user: m.User = Depends(require(Perm.audit_read)), session: Session = S):
    stmt = select(m.AuditEvent).where(m.AuditEvent.workspace_id == user.workspace_id).order_by(m.AuditEvent.created_at.desc())
    if user.role == "agent":  # own/team scope
        disp = set(session.scalars(select(m.Ticket.display_id).where(*tickets.visibility(user))))
        stmt = stmt.where((m.AuditEvent.actor_id == user.id) | ((m.AuditEvent.target_type == "ticket") & m.AuditEvent.target_id.in_(disp)))
    elif user.role == "readonly":  # demo-visible subset
        stmt = stmt.where(m.AuditEvent.event_type.not_in(READONLY_HIDDEN))
    for col, val in ((m.AuditEvent.actor_id, actor_id), (m.AuditEvent.event_type, event_type), (m.AuditEvent.target_id, target_id), (m.AuditEvent.result, result)):
        if val:
            stmt = stmt.where(col == val)
    if date_from:
        stmt = stmt.where(m.AuditEvent.created_at >= date_from)
    if date_to:
        stmt = stmt.where(m.AuditEvent.created_at <= date_to)
    rows = session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    users, _ = tickets.directory(session, user.workspace_id)
    return {"items": [{"id": a.id, "created_at": a.created_at, "actor_type": a.actor_type, "actor_id": a.actor_id,
                       "actor_name": users[a.actor_id].display_name if a.actor_id in users else a.actor_type, "actor_role": users[a.actor_id].role if a.actor_id in users else None,
                       "event_type": a.event_type, "target_type": a.target_type, "target_id": a.target_id, "result": a.result, "before": a.before_json,
                       "after": a.after_json, "reason": a.reason, "run_id": a.run_id, "correlation_id": a.correlation_id, "simulated": a.simulated} for a in rows],
            "page": page, "page_size": page_size}


# ---------------------------------------------------------------- admin
@router.get("/admin/config", tags=["admin"])
def get_config(user: m.User = Depends(require(Perm.config_manage)), session: Session = S):
    return admin.get_config(session, user)


@router.put("/admin/config", tags=["admin"])
def put_config(body: sc.ConfigPatch, user: m.User = Depends(require(Perm.config_manage)), session: Session = S):
    admin.set_config(session, user, body.model_dump())
    session.commit()
    return admin.get_config(session, user)


@router.get("/admin/users", tags=["admin"])
def users(user: m.User = Depends(require(Perm.users_manage)), session: Session = S):
    return {"items": admin.list_users(session, user)}


@router.put("/admin/users/{uid}/role", tags=["admin"])
def set_role(uid: str, body: sc.RoleIn, user: m.User = Depends(require(Perm.users_manage)), session: Session = S):
    admin.set_role(session, user, uid, body.role)
    session.commit()
    return {"items": admin.list_users(session, user)}


@router.post("/admin/demo-reset", tags=["admin"])
def demo_reset(body: sc.ResetIn, user: m.User = Depends(require(Perm.demo_reset)), session: Session = S):
    out = admin.demo_reset(session, user, body.confirm)
    session.commit()
    return out
