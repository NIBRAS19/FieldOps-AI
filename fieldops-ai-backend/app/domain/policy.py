"""Deterministic policy. The model never decides permissions, risk, or approval requirements."""
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.enums import ActionType, RiskClass, Role, TicketStatus

S = TicketStatus
TRANSITIONS: dict[str, set[str]] = {
    S.new: {S.triaged, S.in_progress, S.awaiting_information},
    S.triaged: {S.in_progress, S.awaiting_information},
    S.in_progress: {S.awaiting_information, S.resolved},
    S.awaiting_information: {S.in_progress, S.resolved},
    S.resolved: {S.closed, S.in_progress},
    S.closed: set(),
}

FORBIDDEN_INTENT = re.compile(
    r"(refund|delete (all |the )?(audit )?(records|tickets|logs)|drop table|rm -rf|run (a )?shell|"
    r"(reset|reveal|share) .{0,20}(admin )?password|send (an )?email to all)", re.I)
INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior) instructions|disregard .{0,30}(polic|rules)|system prompt|"
    r"you are now|reveal .{0,25}(secret|key|password)", re.I)


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignPayload(_P):
    team_id: str = Field(min_length=1, max_length=36)
    assignee_id: str | None = Field(default=None, max_length=36)


class TextPayload(_P):
    text: str = Field(min_length=5, max_length=1500)


class StatusPayload(_P):
    to: Literal["triaged", "in_progress", "awaiting_information", "resolved", "closed"]


SCHEMAS: dict[str, type[BaseModel]] = {
    ActionType.assign_ticket: AssignPayload,
    ActionType.add_internal_note: TextPayload,
    ActionType.draft_customer_reply: TextPayload,
    ActionType.request_more_information: TextPayload,
    ActionType.change_local_status: StatusPayload,
}
EDITABLE: dict[str, set[str]] = {
    ActionType.assign_ticket: {"team_id", "assignee_id"},
    ActionType.add_internal_note: {"text"},
    ActionType.draft_customer_reply: {"text"},
    ActionType.request_more_information: {"text"},
    ActionType.change_local_status: {"to"},
}
LABELS = {
    ActionType.assign_ticket: "Assign ticket",
    ActionType.add_internal_note: "Add internal note",
    ActionType.draft_customer_reply: "Draft customer reply",
    ActionType.request_more_information: "Request more information",
    ActionType.change_local_status: "Change ticket status",
}


def validate_payload(action_type: str, payload: dict) -> tuple[dict, list[str]]:
    """Return (clean_payload, errors). Unknown action types and extra fields are rejected."""
    schema = SCHEMAS.get(action_type)
    if schema is None:
        return {}, ["Action type is not on the allowlist."]
    try:
        clean = schema.model_validate(payload).model_dump(exclude_none=True)
    except ValidationError as e:
        return {}, [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
    if "text" in clean and INJECTION.search(clean["text"]):
        return {}, ["Text contains instruction-override patterns and was rejected."]
    return clean, []


def risk_for(action_type: str, payload: dict) -> tuple[str, str]:
    if action_type == ActionType.change_local_status and payload.get("to") in ("resolved", "closed"):
        return RiskClass.high, "Closing out a ticket removes it from active queues and ends SLA tracking."
    if action_type in (ActionType.assign_ticket, ActionType.change_local_status, ActionType.request_more_information):
        return RiskClass.medium, "Changes ticket ownership or workflow state in the local record."
    return RiskClass.low, "Adds text only; no ownership or status change."


def payload_hash(action_type: str, ticket_id: str, payload: dict, version: int) -> str:
    canon = json.dumps([action_type, ticket_id, payload, version], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def can_decide(role: str, user_id: str, risk: str, proposed_by: str | None) -> tuple[bool, str | None]:
    if role == Role.readonly:
        return False, "Read-only role cannot approve or reject."
    if role == Role.agent and risk == RiskClass.high and proposed_by == user_id:
        return False, "You cannot approve your own high-risk proposal."
    if risk == RiskClass.blocked:
        return False, "Blocked proposals cannot be approved."
    return True, None
