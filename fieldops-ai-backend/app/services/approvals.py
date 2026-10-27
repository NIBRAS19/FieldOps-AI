"""Approval gateway. The server, not the model and not the browser, enforces who may approve what, once, and when."""
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models as m
from app.db.types import utcnow
from app.domain.enums import Decision
from app.domain.policy import EDITABLE, can_decide, payload_hash, risk_for, validate_payload
from app.integrations.base import AdapterError
from app.integrations.mock.ticketing import get_action_adapter
from app.services import audit, tickets
from app.services.refs import check_refs

REJECT_REASONS = {"unsupported", "unsafe", "incorrect", "unnecessary", "other"}


def expire_due(session: Session, ws_id: str) -> None:
    for p in session.scalars(select(m.ActionProposal).where(m.ActionProposal.workspace_id == ws_id, m.ActionProposal.status == "pending",
                                                            m.ActionProposal.expires_at <= utcnow())):
        p.status, p.updated_at = "expired", utcnow()
        audit.record(session, ws_id, "proposal_expired", "action_proposal", p.id, actor="system", run_id=p.run_id, reason="Approval window elapsed. Proposal cannot execute.")
    session.commit()


def get_proposal(session: Session, user: m.User, pid: str) -> m.ActionProposal:
    p = session.scalar(select(m.ActionProposal).where(m.ActionProposal.id == pid, m.ActionProposal.workspace_id == user.workspace_id))
    if not p:
        raise AppError("NOT_FOUND", "Proposal not found.", 404)
    tickets.get_ticket(session, user, p.ticket_id)  # scope through the ticket
    return p


def list_proposals(session: Session, user: m.User, *, status=None, risk=None, proposed_by=None, ticket_id=None) -> list[m.ActionProposal]:
    expire_due(session, user.workspace_id)
    stmt = select(m.ActionProposal).where(m.ActionProposal.workspace_id == user.workspace_id).order_by(m.ActionProposal.created_at.desc())
    if status:
        stmt = stmt.where(m.ActionProposal.status.in_(["approved", "executing", "simulated_success"]) if status == "approved" else m.ActionProposal.status == status)
    if risk:
        stmt = stmt.where(m.ActionProposal.risk_class == risk)
    if proposed_by:
        stmt = stmt.where(m.ActionProposal.proposed_by == proposed_by)
    if ticket_id:
        stmt = stmt.where(m.ActionProposal.ticket_id == tickets.get_ticket(session, user, ticket_id).id)
    visible = set(session.scalars(select(m.Ticket.id).where(*tickets.visibility(user))))
    return [p for p in session.scalars(stmt) if p.ticket_id in visible]


def _deny(session: Session, user: m.User, p: m.ActionProposal, code: str, message: str, status: int, event: str) -> None:
    audit.record(session, user.workspace_id, event, "action_proposal", p.id, user=user, result="denied", run_id=p.run_id, reason=message)
    session.commit()
    raise AppError(code, message, status)


def _diagnose(session: Session, user: m.User, p: m.ActionProposal, expected_hash: str) -> None:
    session.refresh(p)
    if p.status != "pending":
        _deny(session, user, p, "PROPOSAL_NOT_PENDING", f"Proposal is no longer pending ({p.status}). Duplicate decision blocked.", 409, "duplicate_decision_blocked")
    if p.expires_at <= utcnow():
        p.status, p.updated_at = "expired", utcnow()
        _deny(session, user, p, "PROPOSAL_EXPIRED", "Proposal has expired and cannot be decided.", 409, "proposal_expired")
    if p.payload_hash != expected_hash:
        _deny(session, user, p, "PAYLOAD_HASH_MISMATCH", "Proposal changed since it was displayed. Review the current version.", 409, "hash_mismatch_blocked")
    _deny(session, user, p, "CONFLICT", "Proposal could not be updated; retry after reloading.", 409, "decision_conflict")


def decide(session: Session, user: m.User, pid: str, decision: str, *, expected_hash: str, edited_payload: dict | None = None,
           reason_code: str | None = None, comment: str | None = None) -> m.ActionProposal:
    p = get_proposal(session, user, pid)
    ok, why = can_decide(user.role, user.id, p.risk_class, p.proposed_by)
    if not ok:
        _deny(session, user, p, "FORBIDDEN_ACTION", why or "Not permitted.", 403, "approval_denied")
    now = utcnow()
    where = (m.ActionProposal.id == p.id, m.ActionProposal.workspace_id == user.workspace_id, m.ActionProposal.status == "pending",
             m.ActionProposal.payload_hash == expected_hash, m.ActionProposal.expires_at > now)
    original_hash = expected_hash
    if decision == Decision.reject:
        if reason_code not in REJECT_REASONS:
            raise AppError("VALIDATION_ERROR", f"reason_code must be one of {sorted(REJECT_REASONS)}.", 422)
        res = session.execute(update(m.ActionProposal).where(*where).values(status="rejected", updated_at=now))
        if res.rowcount != 1:
            _diagnose(session, user, p, expected_hash)
        session.add(m.ApprovalDecision(workspace_id=user.workspace_id, proposal_id=p.id, reviewer_id=user.id, decision=decision, original_payload_hash=original_hash,
                                       reason_code=reason_code, comment=(comment or "")[:500] or None))
        audit.record(session, user.workspace_id, "proposal_rejected", "action_proposal", p.id, user=user, run_id=p.run_id, before={"status": "pending"},
                     after={"status": "rejected"}, reason=f"{reason_code}{': ' + comment[:200] if comment else ''}")
        session.commit()
        session.refresh(p)
        return p

    values: dict = {"status": "approved", "updated_at": now}
    edited_clean = None
    if decision == Decision.edit_approve:
        if not edited_payload:
            raise AppError("VALIDATION_ERROR", "edited_payload is required for edit-approve.", 422)
        bad = set(edited_payload) - EDITABLE[p.action_type]
        if bad:
            raise AppError("VALIDATION_ERROR", f"Fields not editable for {p.action_type}: {sorted(bad)}.", 422)
        edited_clean, errs = validate_payload(p.action_type, {**p.payload_json, **edited_payload})
        if not errs:
            errs = check_refs(session, user.workspace_id, p.action_type, edited_clean)
        if errs:
            raise AppError("POLICY_BLOCKED", " ".join(errs), 422)
        risk, why = risk_for(p.action_type, edited_clean)
        if risk == "high":  # an edit must not launder a high-risk change past the self-approval rule
            ok2, why2 = can_decide(user.role, user.id, risk, p.proposed_by)
            if not ok2:
                _deny(session, user, p, "FORBIDDEN_ACTION", why2 or "Not permitted.", 403, "approval_denied")
        values.update(payload_json=edited_clean, payload_hash=payload_hash(p.action_type, p.ticket_id, edited_clean, p.version + 1),
                      version=p.version + 1, risk_class=risk, risk_reason=why)
    res = session.execute(update(m.ActionProposal).where(*where).values(**values))  # atomic compare-and-set
    if res.rowcount != 1:
        _diagnose(session, user, p, expected_hash)
    session.refresh(p)
    session.add(m.ApprovalDecision(workspace_id=user.workspace_id, proposal_id=p.id, reviewer_id=user.id, decision=decision, original_payload_hash=original_hash,
                                   approved_payload_hash=p.payload_hash, edited_payload_json=edited_clean, comment=(comment or "")[:500] or None))
    if edited_clean is not None:
        audit.record(session, user.workspace_id, "proposal_edited", "action_proposal", p.id, user=user, run_id=p.run_id, before=p.original_payload_json,
                     after=edited_clean, reason=f"Edited to v{p.version}; revalidated; new hash {p.payload_hash[:12]}.")
    audit.record(session, user.workspace_id, "proposal_approved", "action_proposal", p.id, user=user, run_id=p.run_id, after={"version": p.version, "hash": p.payload_hash})
    session.commit()  # the decision is durable BEFORE execution starts
    return execute(session, user, p.id)


def execute(session: Session, user: m.User | None, pid: str) -> m.ActionProposal:
    p = session.get(m.ActionProposal, pid)
    res = session.execute(update(m.ActionProposal).where(m.ActionProposal.id == pid, m.ActionProposal.status == "approved").values(status="executing", updated_at=utcnow()))
    if res.rowcount != 1:
        session.commit()
        return p  # someone else is executing or it already ran: never execute twice
    session.refresh(p)
    ws = session.get(m.Workspace, p.workspace_id)
    adapter = get_action_adapter(ws)
    attempt = (session.scalar(select(func.count()).select_from(m.ToolExecution).where(m.ToolExecution.proposal_id == pid)) or 0) + 1
    key = f"{pid}:{p.payload_hash}:{attempt}"
    ex = m.ToolExecution(workspace_id=p.workspace_id, proposal_id=pid, adapter_name=adapter.name, operation_name=p.action_type, simulated=adapter.simulated,
                         request_summary_json={"ticket_id": p.ticket_id, "hash": p.payload_hash[:12], "attempt": attempt}, idempotency_key=key)
    session.add(ex)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return session.get(m.ActionProposal, pid)
    actor = user.id if user else None

    def fail(code: str, msg: str) -> m.ActionProposal:
        session.rollback()
        p2 = session.get(m.ActionProposal, pid)
        p2.status, p2.result_summary, p2.updated_at = "simulated_failure", msg[:300], utcnow()
        session.add(m.ToolExecution(workspace_id=p2.workspace_id, proposal_id=pid, adapter_name=adapter.name, operation_name=p2.action_type, simulated=True,
                                    request_summary_json={"attempt": attempt}, result_summary_json={"error": msg[:200]}, status="failed", idempotency_key=f"{key}:failed",
                                    error_code=code, finished_at=utcnow()))
        audit.record(session, p2.workspace_id, "simulated_execution", "action_proposal", pid, result="failure", run_id=p2.run_id, actor="system",
                     reason=f"SIMULATED failure: {msg[:200]} Approval metadata preserved.")
        session.commit()
        return p2

    ticket = session.get(m.Ticket, p.ticket_id)
    if payload_hash(p.action_type, p.ticket_id, p.payload_json, p.version) != p.payload_hash:
        return fail("hash_mismatch", "Payload hash differs from approved content.")
    clean, errs = validate_payload(p.action_type, p.payload_json)
    errs += check_refs(session, p.workspace_id, p.action_type, clean)
    if errs:
        return fail("revalidation_failed", " ".join(errs))
    try:
        result = adapter.execute(session, p, ticket, actor)
    except AdapterError as e:
        return fail(e.code, str(e))
    p.status, p.result_summary, p.updated_at = "simulated_success", result["summary"], utcnow()
    ex.status, ex.result_summary_json, ex.finished_at = "success", result, utcnow()
    audit.record(session, p.workspace_id, "simulated_execution", "action_proposal", pid, user=user, run_id=p.run_id, after=result,
                 reason=f"SIMULATED LOCAL ACTION on {ticket.display_id}. No external system touched.")
    session.commit()
    return p


def retry_execution(session: Session, user: m.User, pid: str) -> m.ActionProposal:
    """Safe retry of a failed simulated execution. Only the idempotent mock adapter exists; a prior success blocks retry."""
    p = get_proposal(session, user, pid)
    ok, why = can_decide(user.role, user.id, p.risk_class, p.proposed_by)
    if not ok:
        _deny(session, user, p, "FORBIDDEN_ACTION", why or "Not permitted.", 403, "approval_denied")
    done = session.scalar(select(func.count()).select_from(m.ToolExecution).where(m.ToolExecution.proposal_id == pid, m.ToolExecution.status == "success"))
    res = session.execute(update(m.ActionProposal).where(m.ActionProposal.id == pid, m.ActionProposal.status == "simulated_failure").values(status="approved"))
    if done or res.rowcount != 1:
        session.rollback()
        raise AppError("INVALID_STATE", "Only a failed, never-succeeded execution can be retried.", 409)
    audit.record(session, user.workspace_id, "execution_retry", "action_proposal", pid, user=user, run_id=p.run_id)
    session.commit()
    return execute(session, user, pid)


def proposal_out(session: Session, p: m.ActionProposal, users: dict) -> dict:
    decisions = session.scalars(select(m.ApprovalDecision).where(m.ApprovalDecision.proposal_id == p.id).order_by(m.ApprovalDecision.created_at)).all()
    return {"id": p.id, "ticket_id": p.ticket_id, "run_id": p.run_id, "action_type": p.action_type, "summary": p.summary, "rationale": p.rationale,
            "risk_class": p.risk_class, "risk_reason": p.risk_reason, "payload": p.payload_json, "original_payload": p.original_payload_json, "payload_hash": p.payload_hash,
            "version": p.version, "status": p.status, "expected_effect": p.expected_effect, "rollback_note": p.rollback_note, "evidence_ids": p.evidence_ids,
            "proposed_by": p.proposed_by, "proposed_by_name": users[p.proposed_by].display_name if p.proposed_by in users else None, "expires_at": p.expires_at,
            "result_summary": p.result_summary, "simulated": True, "created_at": p.created_at, "updated_at": p.updated_at,
            "decisions": [{"decision": d.decision, "reviewer_id": d.reviewer_id, "reviewer_name": users[d.reviewer_id].display_name if d.reviewer_id in users else None,
                           "reason_code": d.reason_code, "comment": d.comment, "original_payload_hash": d.original_payload_hash,
                           "approved_payload_hash": d.approved_payload_hash, "created_at": d.created_at} for d in decisions]}
