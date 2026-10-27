from enum import StrEnum


class Role(StrEnum):
    admin = "admin"
    lead = "lead"
    agent = "agent"
    readonly = "readonly"


class TicketStatus(StrEnum):
    new = "new"
    triaged = "triaged"
    in_progress = "in_progress"
    awaiting_information = "awaiting_information"
    resolved = "resolved"
    closed = "closed"


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Category(StrEnum):
    access = "access"
    connectivity = "connectivity"
    device = "device"
    application = "application"
    request = "request"
    other = "other"


class ActionType(StrEnum):
    assign_ticket = "assign_ticket"
    add_internal_note = "add_internal_note"
    draft_customer_reply = "draft_customer_reply"
    request_more_information = "request_more_information"
    change_local_status = "change_local_status"


class RiskClass(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    blocked = "blocked"


class ProposalStatus(StrEnum):
    draft = "draft"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    executing = "executing"
    simulated_success = "simulated_success"
    simulated_failure = "simulated_failure"
    cancelled = "cancelled"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    awaiting_review = "awaiting_review"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Decision(StrEnum):
    approve = "approve"
    edit_approve = "edit_approve"
    reject = "reject"
