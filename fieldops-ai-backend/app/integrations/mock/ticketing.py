"""Mock ticketing adapter. Touches ONLY local synthetic records. Never sends anything externally."""
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.types import utcnow
from app.domain.enums import ActionType
from app.domain.policy import TRANSITIONS
from app.integrations.base import AdapterError
from app.observability.logging import correlation_id


class MockTicketingAdapter:
    name = "mock_ticketing"
    simulated = True
    idempotent = True  # guarded by the unique idempotency key on tool_executions

    def _event(self, session: Session, t: m.Ticket, etype: str, payload: dict) -> None:
        session.add(m.TicketEvent(workspace_id=t.workspace_id, ticket_id=t.id, actor_id=None, event_type=etype, payload_json=payload, correlation_id=correlation_id.get()))

    def execute(self, session: Session, proposal: m.ActionProposal, ticket: m.Ticket, actor_id: str | None) -> dict:
        p, now = proposal.payload_json, utcnow()
        values: dict = {}
        if proposal.action_type == ActionType.assign_ticket:
            values = {"team_id": p["team_id"], "assignee_id": p.get("assignee_id", ticket.assignee_id)}
            result = {"summary": "Assigned in the local record.", "team_id": p["team_id"], "assignee_id": values["assignee_id"]}
            self._event(session, ticket, "ai_assigned", {"team_id": p["team_id"], "assignee_id": values["assignee_id"], "proposal_id": proposal.id})
        elif proposal.action_type == ActionType.add_internal_note:
            self._event(session, ticket, "ai_note", {"text": p["text"], "proposal_id": proposal.id})
            result = {"summary": "Internal note added."}
        elif proposal.action_type == ActionType.draft_customer_reply:
            self._event(session, ticket, "reply_draft", {"text": p["text"], "proposal_id": proposal.id, "sent": False})
            result = {"summary": "Reply draft stored locally. Not sent."}
        elif proposal.action_type == ActionType.request_more_information:
            if "awaiting_information" not in TRANSITIONS.get(ticket.status, set()):
                raise AdapterError("transition_not_allowed", f"Ticket status {ticket.status} cannot move to awaiting_information.")
            values = {"status": "awaiting_information"}
            self._event(session, ticket, "info_request", {"text": p["text"], "proposal_id": proposal.id, "sent": False})
            result = {"summary": "Information request stored locally; ticket set to awaiting_information. Not sent."}
        elif proposal.action_type == ActionType.change_local_status:
            if p["to"] not in TRANSITIONS.get(ticket.status, set()):
                raise AdapterError("transition_not_allowed", f"Transition {ticket.status} -> {p['to']} is not allowed.")
            values = {"status": p["to"]}
            if p["to"] == "closed":
                values["closed_at"] = now
            self._event(session, ticket, "status_changed", {"from": ticket.status, "to": p["to"], "proposal_id": proposal.id})
            result = {"summary": f"Status {ticket.status} -> {p['to']}."}
        else:
            raise AdapterError("unsupported_action", "Action is not supported by this adapter.")
        # optimistic concurrency: only apply if nobody changed the ticket since we read it
        res = session.execute(update(m.Ticket).where(m.Ticket.id == ticket.id, m.Ticket.version == ticket.version)
                              .values(version=ticket.version + 1, updated_at=now, **values))
        if res.rowcount != 1:
            raise AdapterError("stale_ticket", "Ticket changed since the proposal was reviewed.")
        return result


def get_action_adapter(workspace: m.Workspace) -> MockTicketingAdapter:
    """The SERVER decides mock vs live. The MVP only has mock; a client `simulated` flag is never trusted."""
    return MockTicketingAdapter()
