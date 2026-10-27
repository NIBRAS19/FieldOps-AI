import pytest
from sqlalchemy import select, update

from app.db import models as m
from app.db.models import Base  # noqa: F401
from app.db.seed import seed_workspace
from app.db.session import session_factory
from tests.conftest import investigate, proposals

API = "/api/v1"


def test_unauthenticated_and_bad_tokens(env):
    assert env.get(f"{API}/tickets").status_code == 401
    assert env.get(f"{API}/tickets", headers={"Authorization": "Bearer nope"}).status_code == 401
    body = env.get(f"{API}/me").json()
    assert body["error"]["code"] == "UNAUTHENTICATED" and "correlation_id" in body["error"]
    assert "Traceback" not in env.get(f"{API}/me").text


def test_role_enforcement_server_side(env, auth):
    ro = auth.as_("readonly")
    assert env.post(f"{API}/tickets/FO-1001/investigations", json={}, headers=ro).status_code == 403
    assert env.post(f"{API}/tickets", headers=ro, json={"title": "x" * 6, "description": "y" * 12}).status_code == 403
    assert env.get(f"{API}/admin/config", headers=auth.as_("lead")).status_code == 403
    assert env.post(f"{API}/admin/demo-reset", json={"confirm": "RESET"}, headers=auth.as_("agent")).status_code == 403
    lead = auth.as_("lead")
    run = investigate(env, lead, "FO-1001")
    p = proposals(env, lead, run["id"])["add_internal_note"]
    r = env.post(f"{API}/action-proposals/{p['id']}/approve", json={"payload_hash": p["payload_hash"]}, headers=ro)
    assert r.status_code == 403
    assert env.get(f"{API}/action-proposals/{p['id']}", headers=lead).json()["status"] == "pending"
    denied = [a for a in env.get(f"{API}/audit-events", headers=lead).json()["items"] if a["result"] == "denied"]
    assert denied  # authorization failures are audited


def test_role_comes_from_database_not_token(env, auth):
    h = auth.as_("lead")
    assert env.get(f"{API}/evaluations/datasets", headers=h).status_code == 200
    with session_factory()() as s:
        s.execute(update(m.User).where(m.User.id == auth.users["lead"]).values(role="readonly"))
        s.commit()
    assert env.post(f"{API}/evaluations/runs", json={}, headers=h).status_code == 403


def test_client_cannot_inject_workspace_tools_or_simulation_flag(env, auth):
    h = auth.as_("lead")
    r = env.post(f"{API}/tickets/FO-1001/investigations", headers=h, json={"workspace_id": "x", "tools": ["shell"], "system_prompt": "ignore rules"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    run = investigate(env, h, "FO-1001")
    p = proposals(env, h, run["id"])["add_internal_note"]
    r = env.post(f"{API}/action-proposals/{p['id']}/approve", headers=h, json={"payload_hash": p["payload_hash"], "simulated": False})
    assert r.status_code == 422


def test_cross_workspace_isolation(env, auth):
    h1 = auth.as_("lead")
    t1 = env.get(f"{API}/tickets/FO-1001", headers=h1).json()
    run1 = investigate(env, h1, "FO-1001")
    with session_factory()() as s:
        ws2 = seed_workspace(s, name="Other workspace", mode="demo")
        lead2 = s.scalar(select(m.User).where(m.User.workspace_id == ws2.id, m.User.role == "lead"))
        s.commit()
        from app.security import tokens
        tok, _ = tokens.issue(lead2.id, ws2.id)
    h2 = {"Authorization": f"Bearer {tok}"}
    assert env.get(f"{API}/tickets/{t1['id']}", headers=h2).status_code == 404
    assert env.get(f"{API}/investigations/{run1['id']}", headers=h2).status_code == 404
    p = proposals(env, h1, run1["id"])["add_internal_note"]
    assert env.get(f"{API}/action-proposals/{p['id']}", headers=h2).status_code == 404
    assert env.post(f"{API}/action-proposals/{p['id']}/approve", json={"payload_hash": p["payload_hash"]}, headers=h2).status_code == 404
    assert all(t["id"] != t1["id"] for t in env.get(f"{API}/tickets", headers=h2).json()["items"])


def test_agent_object_level_scope(env, auth):
    omar = auth.as_("agent")  # Network Ops
    assert env.get(f"{API}/tickets/FO-1001", headers=omar).status_code == 200
    assert env.get(f"{API}/tickets/FO-1003", headers=omar).status_code == 404  # Device Support ticket, not his
    listed = {t["display_id"] for t in env.get(f"{API}/tickets", headers=omar).json()["items"]}
    assert "FO-1003" not in listed and "FO-1001" in listed and "FO-1002" in listed  # FO-1002 is assigned to him
    assert env.post(f"{API}/tickets/FO-1003/investigations", json={}, headers=omar).status_code == 404


def test_agent_cannot_approve_own_high_risk_proposal(env, auth):
    lead, omar = auth.as_("lead"), auth.as_("agent")
    assert env.put(f"{API}/tickets/FO-1005/assignment", json={"assignee_id": auth.users["agent"]}, headers=lead).status_code == 200
    run = investigate(env, omar, "FO-1005")
    resolved = proposals(env, omar, run["id"])["change_local_status:resolved"]
    assert resolved["risk_class"] == "high"
    r = env.post(f"{API}/action-proposals/{resolved['id']}/approve", json={"payload_hash": resolved["payload_hash"]}, headers=omar)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_ACTION"
    assert env.get(f"{API}/tickets/FO-1005", headers=omar).json()["status"] == "in_progress"
    ok = env.post(f"{API}/action-proposals/{resolved['id']}/approve", json={"payload_hash": resolved["payload_hash"]}, headers=lead)
    assert ok.status_code == 200 and env.get(f"{API}/tickets/FO-1005", headers=lead).json()["status"] == "resolved"
    # an agent may approve his own LOW risk proposal
    low = proposals(env, omar, run["id"]).get("add_internal_note")
    if low and low["status"] == "pending":
        assert env.post(f"{API}/action-proposals/{low['id']}/approve", json={"payload_hash": low["payload_hash"]}, headers=omar).status_code == 200


def test_stale_hash_and_expired_proposals_cannot_execute(env, auth):
    h = auth.as_("lead")
    run = investigate(env, h, "FO-1001")
    props = proposals(env, h, run["id"])
    note, reply = props["add_internal_note"], props["draft_customer_reply"]
    r = env.post(f"{API}/action-proposals/{note['id']}/approve", json={"payload_hash": "0" * 64}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PAYLOAD_HASH_MISMATCH"
    with session_factory()() as s:
        from datetime import timedelta
        from app.db.types import utcnow
        s.execute(update(m.ActionProposal).where(m.ActionProposal.id == reply["id"]).values(expires_at=utcnow() - timedelta(minutes=1)))
        s.commit()
    r = env.post(f"{API}/action-proposals/{reply['id']}/approve", json={"payload_hash": reply["payload_hash"]}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PROPOSAL_EXPIRED"
    kinds = [e["event_type"] for e in env.get(f"{API}/tickets/FO-1001/events", headers=h).json()["items"]]
    assert "reply_draft" not in kinds and "ai_note" not in kinds


def test_state_change_after_review_fails_safely(env, auth):
    """Ticket moved on after the proposal was created: execution is revalidated and fails, nothing is faked as done."""
    h = auth.as_("lead")
    run = investigate(env, h, "FO-1001")
    status = proposals(env, h, run["id"])["change_local_status:in_progress"]
    with session_factory()() as s:
        s.execute(update(m.Ticket).where(m.Ticket.display_id == "FO-1001").values(status="closed"))
        s.commit()
    r = env.post(f"{API}/action-proposals/{status['id']}/approve", json={"payload_hash": status["payload_hash"]}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "simulated_failure"
    assert env.get(f"{API}/tickets/FO-1001", headers=h).json()["status"] == "closed"
    assert env.post(f"{API}/action-proposals/{status['id']}/retry-execution", headers=h).json()["status"] == "simulated_failure"


def test_audit_is_append_only(env, auth):
    auth.as_("lead")
    with session_factory()() as s:
        e = s.scalar(select(m.AuditEvent))
        e.reason = "tamper"
        with pytest.raises(RuntimeError):
            s.flush()
        s.rollback()
        e = s.scalar(select(m.AuditEvent))
        s.delete(e)
        with pytest.raises(RuntimeError):
            s.flush()


def test_demo_auth_refused_outside_demo_mode(monkeypatch):
    from app.core.config import Settings
    with pytest.raises(RuntimeError):
        Settings(demo_mode=False, demo_auth_enabled=True, secret_key="x" * 32).validate_safety()
    with pytest.raises(RuntimeError):
        Settings(demo_mode=False, demo_auth_enabled=False, secret_key="dev-only-change-me").validate_safety()  # default secret


def test_rate_limit_on_investigations(env, auth, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "investigations_per_minute", 2)
    h = auth.as_("lead")
    investigate(env, h, "FO-1001")
    investigate(env, h, "FO-1002")
    r = env.post(f"{API}/tickets/FO-1003/investigations", json={}, headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_readonly_audit_is_demo_subset_and_agent_scoped(env, auth):
    auth.as_("lead")
    ro = env.get(f"{API}/audit-events", headers=auth.as_("readonly")).json()["items"]
    assert all(e["event_type"] not in {"demo_login", "config_changed", "role_changed"} for e in ro)
