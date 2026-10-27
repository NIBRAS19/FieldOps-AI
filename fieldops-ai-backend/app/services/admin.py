from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models as m
from app.db.seed import reset_domain
from app.db.types import utcnow
from app.domain.enums import Role
from app.services import audit, tickets

FAULTS = {"none", "timeout", "malformed", "retrieval"}
LIMITS = {"top_k": (1, 8), "max_retries": (0, 5), "approval_expiry_minutes": (1, 1440)}


def get_config(session: Session, user: m.User) -> dict:
    ws = session.get(m.Workspace, user.workspace_id)
    return {"workspace": {"id": ws.id, "name": ws.name, "mode": ws.mode}, "settings": ws.settings_json, "model_mode": "fixture", "connector_mode": "mock_only",
            "live_provider_configured": False}


def set_config(session: Session, user: m.User, patch: dict) -> dict:
    ws = session.get(m.Workspace, user.workspace_id)
    new = dict(ws.settings_json)
    for k, v in patch.items():
        if v is None:
            continue
        if k == "fault":
            if v not in FAULTS:
                raise AppError("VALIDATION_ERROR", f"fault must be one of {sorted(FAULTS)}.", 422)
            if ws.mode != "demo" and v != "none":
                raise AppError("POLICY_BLOCKED", "Fault injection is only available in demo workspaces.", 403)
        elif k in LIMITS and not (LIMITS[k][0] <= v <= LIMITS[k][1]):
            raise AppError("VALIDATION_ERROR", f"{k} must be between {LIMITS[k][0]} and {LIMITS[k][1]}.", 422)
        new[k] = v
    audit.record(session, user.workspace_id, "config_changed", "workspace", ws.id, user=user, before={k: ws.settings_json.get(k) for k in patch if patch[k] is not None},
                 after={k: v for k, v in patch.items() if v is not None})
    ws.settings_json, ws.updated_at = new, utcnow()
    return new


def list_users(session: Session, user: m.User) -> list[dict]:
    users, teams = tickets.directory(session, user.workspace_id)
    return [{"id": u.id, "display_name": u.display_name, "email": u.email, "role": u.role, "active": u.active,
             "team_name": teams[u.team_id].name if u.team_id in teams else None} for u in users.values()]


def set_role(session: Session, user: m.User, target_id: str, role: str) -> m.User:
    if role not in {r.value for r in Role}:
        raise AppError("VALIDATION_ERROR", "Unknown role.", 422)
    t = session.scalar(select(m.User).where(m.User.id == target_id, m.User.workspace_id == user.workspace_id))
    if not t:
        raise AppError("NOT_FOUND", "User not found.", 404)
    if t.id == user.id:
        raise AppError("POLICY_BLOCKED", "You cannot change your own role.", 403)
    before = t.role
    t.role, t.updated_at = role, utcnow()
    audit.record(session, user.workspace_id, "role_changed", "user", t.id, user=user, before={"role": before}, after={"role": role})
    return t


def demo_reset(session: Session, user: m.User, confirm: str) -> dict:
    ws = session.get(m.Workspace, user.workspace_id)
    if ws.mode != "demo":
        raise AppError("POLICY_BLOCKED", "Reset is only available in demo workspaces.", 403)
    if confirm != "RESET":
        raise AppError("CONFIRMATION_REQUIRED", "Send confirm='RESET' to reset the synthetic dataset.", 400)
    before = ws.settings_json.get("dataset_version", 1)
    ver = reset_domain(session, ws)
    # audit_events are deliberately preserved (append-only); the reset itself is recorded as an event.
    audit.record(session, user.workspace_id, "demo_reset", "workspace", ws.id, user=user, before={"dataset_version": before}, after={"dataset_version": ver},
                 reason="Synthetic domain data regenerated. Audit history retained. This is not a secure-erasure guarantee.")
    return {"dataset_version": ver}


def overview(session: Session, user: m.User) -> dict:
    visible = list(session.scalars(select(m.Ticket).where(*tickets.visibility(user))))
    ids = {t.id for t in visible}
    open_t = [t for t in visible if t.status not in ("resolved", "closed")]
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    runs = [r for r in session.scalars(select(m.InvestigationRun).where(m.InvestigationRun.workspace_id == user.workspace_id)) if r.ticket_id in ids]
    pending = session.scalar(select(func.count()).select_from(m.ActionProposal).where(m.ActionProposal.workspace_id == user.workspace_id, m.ActionProposal.status == "pending",
                                                                                      m.ActionProposal.ticket_id.in_(ids))) if ids else 0
    count = lambda key: {k: sum(1 for t in visible if getattr(t, key) == k) for k in {getattr(t, key) for t in visible}}  # noqa: E731
    ws = session.get(m.Workspace, user.workspace_id)
    return {"window": "current snapshot of synthetic data", "open_tickets": len(open_t), "high_priority_tickets": sum(1 for t in open_t if t.priority in ("high", "critical")),
            "awaiting_review": pending, "investigations_today": sum(1 for r in runs if r.started_at >= today), "failed_runs": sum(1 for r in runs if r.status == "failed"),
            "tickets_by_status": count("status"), "tickets_by_priority": count("priority"), "model_mode": "fixture", "connector_mode": "mock_only",
            "fault_injection": ws.settings_json.get("fault", "none"), "dataset_version": ws.settings_json.get("dataset_version", 1)}
