from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models as m
from app.db.types import utcnow
from app.domain.enums import Role
from app.observability.logging import correlation_id, redact
from app.services import audit

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def visibility(user: m.User):
    """Object-level scope. Agents see tickets assigned to them or owned by their team; others see the workspace."""
    conds = [m.Ticket.workspace_id == user.workspace_id]
    if user.role == Role.agent:
        own = [m.Ticket.assignee_id == user.id]
        if user.team_id:
            own.append(m.Ticket.team_id == user.team_id)
        conds.append(or_(*own))
    return conds


def get_ticket(session: Session, user: m.User, ident: str) -> m.Ticket:
    t = session.scalar(select(m.Ticket).where(*visibility(user), or_(m.Ticket.id == ident, m.Ticket.display_id == ident.upper())))
    if not t:
        raise AppError("NOT_FOUND", "Ticket not found.", 404)  # same response for missing and not-authorized (no existence leak)
    return t


def sla_band(t: m.Ticket) -> str:
    if t.status in ("resolved", "closed") or not t.sla_due_at:
        return "done"
    left = t.sla_due_at - utcnow()
    return "breached" if left < timedelta(0) else "at_risk" if left < timedelta(hours=4) else "ok"


def latest_run_status(session: Session, ws_id: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in session.scalars(select(m.InvestigationRun).where(m.InvestigationRun.workspace_id == ws_id).order_by(m.InvestigationRun.started_at)):
        out[r.ticket_id] = r.status
    return out


def directory(session: Session, ws_id: str) -> tuple[dict, dict]:
    users = {u.id: u for u in session.scalars(select(m.User).where(m.User.workspace_id == ws_id))}
    teams = {t.id: t for t in session.scalars(select(m.Team).where(m.Team.workspace_id == ws_id))}
    return users, teams


def ticket_out(t: m.Ticket, users: dict, teams: dict, ai_state: str = "not_started", assets: dict | None = None) -> dict:
    return {"id": t.id, "display_id": t.display_id, "title": t.title, "description": t.description, "category": t.category, "priority": t.priority,
            "status": t.status, "assignee_id": t.assignee_id, "assignee_name": users[t.assignee_id].display_name if t.assignee_id in users else None,
            "team_id": t.team_id, "team_name": teams[t.team_id].name if t.team_id in teams else None, "customer_alias": t.customer_alias,
            "asset_tag": (assets or {}).get(t.asset_id), "sla_due_at": t.sla_due_at, "sla_band": sla_band(t), "ai_state": ai_state, "synthetic": t.is_synthetic,
            "version": t.version, "created_at": t.created_at, "updated_at": t.updated_at}


def list_tickets(session: Session, user: m.User, *, q=None, status=None, priority=None, category=None, assignee_id=None, ai_state=None,
                 sla=None, sort="priority", page=1, page_size=20) -> dict:
    stmt = select(m.Ticket).where(*visibility(user))
    for col, val in ((m.Ticket.status, status), (m.Ticket.priority, priority), (m.Ticket.category, category)):
        if val:
            stmt = stmt.where(col == val)
    if assignee_id:
        stmt = stmt.where(m.Ticket.assignee_id.is_(None) if assignee_id == "none" else m.Ticket.assignee_id == assignee_id)
    if q:
        like = f"%{q.lower()}%"
        assets = select(m.Asset.id).where(m.Asset.workspace_id == user.workspace_id, func.lower(m.Asset.asset_tag).like(like))
        stmt = stmt.where(or_(func.lower(m.Ticket.display_id).like(like), func.lower(m.Ticket.title).like(like), func.lower(m.Ticket.description).like(like),
                              func.lower(func.coalesce(m.Ticket.customer_alias, "")).like(like), m.Ticket.asset_id.in_(assets)))
    rows = list(session.scalars(stmt))
    runs = latest_run_status(session, user.workspace_id)
    if ai_state:
        rows = [t for t in rows if runs.get(t.id, "not_started") == ai_state]
    if sla:
        rows = [t for t in rows if sla_band(t) == sla]
    key = {"priority": lambda t: (PRIORITY_ORDER[t.priority], t.sla_due_at or utcnow()), "updated": lambda t: -t.updated_at.timestamp(),
           "created": lambda t: -t.created_at.timestamp(), "sla": lambda t: (t.sla_due_at or utcnow()).timestamp()}.get(sort)
    if key is None:
        raise AppError("VALIDATION_ERROR", "Unknown sort key.", 422)
    rows.sort(key=key)
    users, teams = directory(session, user.workspace_id)
    assets = {a.id: a.asset_tag for a in session.scalars(select(m.Asset).where(m.Asset.workspace_id == user.workspace_id))}
    total = len(rows)
    page_rows = rows[(page - 1) * page_size: page * page_size]
    return {"items": [ticket_out(t, users, teams, runs.get(t.id, "not_started"), assets) for t in page_rows], "total": total, "page": page, "page_size": page_size}


def detail(session: Session, user: m.User, ident: str) -> dict:
    t = get_ticket(session, user, ident)
    users, teams = directory(session, user.workspace_id)
    assets = {a.id: a.asset_tag for a in session.scalars(select(m.Asset).where(m.Asset.id == t.asset_id))} if t.asset_id else {}
    runs = latest_run_status(session, user.workspace_id)
    related = session.scalars(select(m.HistoricalCase).where(m.HistoricalCase.workspace_id == user.workspace_id, m.HistoricalCase.category == t.category)).all()
    return {**ticket_out(t, users, teams, runs.get(t.id, "not_started"), assets),
            "related_cases": [{"display_id": c.display_id, "title": c.title, "resolution": c.resolution} for c in related]}


def next_display_id(session: Session, ws_id: str) -> str:
    ids = session.scalars(select(m.Ticket.display_id).where(m.Ticket.workspace_id == ws_id)).all()
    return f"FO-{max((int(i.split('-')[1]) for i in ids), default=1000) + 1}"


def create_ticket(session: Session, user: m.User, data: dict) -> m.Ticket:
    ws = session.get(m.Workspace, user.workspace_id)
    if ws.mode != "demo":
        raise AppError("POLICY_BLOCKED", "Synthetic ticket creation is only available in demo workspaces.", 403)
    team = session.scalar(select(m.Team).where(m.Team.workspace_id == user.workspace_id, m.Team.name == {
        "connectivity": "Network Ops", "access": "Identity & Access", "device": "Device Support", "application": "App Support"}.get(data["category"], "Service Desk")))
    asset_id = None
    if data.get("asset_tag"):
        a = session.scalar(select(m.Asset).where(m.Asset.workspace_id == user.workspace_id, m.Asset.asset_tag == data["asset_tag"]))
        if not a:
            a = m.Asset(workspace_id=user.workspace_id, asset_tag=data["asset_tag"], asset_type="unknown", warranty_state="synthetic")
            session.add(a)
            session.flush()
        asset_id = a.id
    sla_h = {"low": 48, "medium": 24, "high": 8, "critical": 4}[data["priority"]]
    t = m.Ticket(workspace_id=user.workspace_id, display_id=next_display_id(session, user.workspace_id), title=data["title"].strip(), description=data["description"].strip(),
                 category=data["category"], priority=data["priority"], status="new", team_id=team.id if team else None, customer_alias=data.get("customer_alias"),
                 asset_id=asset_id, sla_due_at=utcnow() + timedelta(hours=sla_h))
    session.add(t)
    session.flush()
    add_event(session, t, user, "ticket_created", {"title": t.title})
    audit.record(session, user.workspace_id, "ticket_created", "ticket", t.display_id, user=user, reason="Synthetic ticket created.")
    return t


def add_event(session: Session, t: m.Ticket, user: m.User | None, event_type: str, payload: dict) -> None:
    session.add(m.TicketEvent(workspace_id=t.workspace_id, ticket_id=t.id, actor_id=user.id if user else None, event_type=event_type, payload_json=payload,
                              correlation_id=correlation_id.get()))


def add_note(session: Session, user: m.User, ident: str, text: str) -> None:
    t = get_ticket(session, user, ident)
    add_event(session, t, user, "note_added", {"text": redact(text.strip())})
    t.updated_at = utcnow()
    audit.record(session, user.workspace_id, "note_added", "ticket", t.display_id, user=user, reason="Human note added.")


def assign_direct(session: Session, user: m.User, ident: str, assignee_id: str | None) -> m.Ticket:
    t = get_ticket(session, user, ident)
    if assignee_id:
        a = session.scalar(select(m.User).where(m.User.id == assignee_id, m.User.workspace_id == user.workspace_id, m.User.active.is_(True)))
        if not a or a.role == Role.readonly:
            raise AppError("VALIDATION_ERROR", "Assignee must be an active, non-read-only user in this workspace.", 422)
    before = t.assignee_id
    t.assignee_id, t.version, t.updated_at = assignee_id, t.version + 1, utcnow()
    add_event(session, t, user, "assigned", {"from": before, "to": assignee_id})
    audit.record(session, user.workspace_id, "ticket_assigned", "ticket", t.display_id, user=user, before={"assignee_id": before}, after={"assignee_id": assignee_id},
                 reason="Manual assignment (local record).")
    return t


def events(session: Session, user: m.User, ident: str) -> list[dict]:
    t = get_ticket(session, user, ident)
    users, _ = directory(session, user.workspace_id)
    rows = session.scalars(select(m.TicketEvent).where(m.TicketEvent.ticket_id == t.id).order_by(m.TicketEvent.created_at.desc())).all()
    return [{"id": e.id, "event_type": e.event_type, "actor_id": e.actor_id, "actor_name": users[e.actor_id].display_name if e.actor_id in users else "AI-approved action",
             "payload": e.payload_json, "created_at": e.created_at} for e in rows]
