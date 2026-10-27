"""Referential checks for proposal payloads. Re-run at creation, edit, and execution time."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m


def check_refs(session: Session, ws_id: str, action_type: str, payload: dict) -> list[str]:
    errs: list[str] = []
    if action_type == "assign_ticket":
        if not session.scalar(select(m.Team.id).where(m.Team.id == payload.get("team_id"), m.Team.workspace_id == ws_id)):
            errs.append("team_id does not exist in this workspace.")
        a = payload.get("assignee_id")
        if a:
            u = session.scalar(select(m.User).where(m.User.id == a, m.User.workspace_id == ws_id, m.User.active.is_(True)))
            if not u or u.role == "readonly":
                errs.append("assignee_id must be an active, non-read-only user in this workspace.")
    return errs
