from sqlalchemy.orm import Session

from app.db import models as m
from app.observability.logging import correlation_id, redact_json


def record(session: Session, ws_id: str, event_type: str, target_type: str, target_id: str, *, user: m.User | None = None, actor: str | None = None,
           result: str = "success", before: dict | None = None, after: dict | None = None, reason: str | None = None, run_id: str | None = None) -> m.AuditEvent:
    """Append an audit event. Payloads are redacted. Never pass secrets or full sensitive content."""
    actor_type = "user" if user else (actor or "system")
    e = m.AuditEvent(workspace_id=ws_id, actor_type=actor_type, actor_id=user.id if user else None, event_type=event_type, target_type=target_type,
                     target_id=str(target_id), result=result, before_json=redact_json(before) if before else None, after_json=redact_json(after) if after else None,
                     reason=redact_json(reason) if reason else None, run_id=run_id, correlation_id=correlation_id.get())
    session.add(e)
    return e
