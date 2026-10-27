from tests.conftest import investigate, proposals

API = "/api/v1"


def test_end_to_end_investigate_review_approve_audit(env, auth):
    h = auth.as_("lead")
    run = investigate(env, h, "FO-1001")
    assert run["status"] == "awaiting_review" and run["disposition"] == "awaiting_approval"
    ev = env.get(f"{API}/investigations/{run['id']}/events", headers=h).json()["items"]
    assert [e["step"] for e in ev][:3] == ["input_validation", "classification", "retrieval"] and len(ev) == 9
    cited = {e["chunk_id"] for e in run["output"]["evidence"]}
    assert cited == {"kb-vpn-001-c02", "kb-vpn-001-c03", "kb-vpn-001-c04"}  # community tip quarantined
    assert any("Untrusted" in x for x in run["output"]["limitations"])

    props = proposals(env, h, run["id"])
    note = props["add_internal_note"]
    assert note["status"] == "pending" and note["simulated"] is True
    t_before = env.get(f"{API}/tickets/FO-1001", headers=h).json()
    assert t_before["status"] == "new"  # nothing changed before approval

    r = env.post(f"{API}/action-proposals/{note['id']}/approve", json={"payload_hash": note["payload_hash"]}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "simulated_success"
    kinds = [e["event_type"] for e in env.get(f"{API}/tickets/FO-1001/events", headers=h).json()["items"]]
    assert "ai_note" in kinds
    audit = {a["event_type"] for a in env.get(f"{API}/audit-events", headers=h).json()["items"]}
    assert {"investigation_started", "proposal_created", "proposal_approved", "simulated_execution"} <= audit

    dup = env.post(f"{API}/action-proposals/{note['id']}/approve", json={"payload_hash": note["payload_hash"]}, headers=h)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "PROPOSAL_NOT_PENDING"
    assert [e["event_type"] for e in env.get(f"{API}/tickets/FO-1001/events", headers=h).json()["items"]].count("ai_note") == 1


def test_edit_approve_creates_new_version_and_executes_edited_payload(env, auth):
    h = auth.as_("lead")
    run = investigate(env, h, "FO-1001")
    note = proposals(env, h, run["id"])["add_internal_note"]
    r = env.post(f"{API}/action-proposals/{note['id']}/edit-approve", headers=h,
                 json={"payload_hash": note["payload_hash"], "edited_payload": {"text": "Reviewer-edited note about VPN sync delay."}})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "simulated_success" and body["version"] == 2
    assert body["payload_hash"] != note["payload_hash"] and body["original_payload"] == note["payload"]
    texts = [e["payload"].get("text") for e in env.get(f"{API}/tickets/FO-1001/events", headers=h).json()["items"] if e["event_type"] == "ai_note"]
    assert texts == ["Reviewer-edited note about VPN sync delay."]
    bad = proposals(env, h, run["id"])["draft_customer_reply"]
    r2 = env.post(f"{API}/action-proposals/{bad['id']}/edit-approve", headers=h, json={"payload_hash": bad["payload_hash"], "edited_payload": {"to": "closed"}})
    assert r2.status_code == 422  # non-editable field


def test_reject_requires_reason_and_never_executes(env, auth):
    h = auth.as_("lead")
    run = investigate(env, h, "FO-1001")
    p = proposals(env, h, run["id"])["add_internal_note"]
    assert env.post(f"{API}/action-proposals/{p['id']}/reject", json={"payload_hash": p["payload_hash"]}, headers=h).status_code == 422
    r = env.post(f"{API}/action-proposals/{p['id']}/reject", json={"payload_hash": p["payload_hash"], "reason_code": "unsafe"}, headers=h)
    assert r.json()["status"] == "rejected"
    assert env.post(f"{API}/action-proposals/{p['id']}/approve", json={"payload_hash": p["payload_hash"]}, headers=h).status_code == 409
    assert "ai_note" not in [e["event_type"] for e in env.get(f"{API}/tickets/FO-1001/events", headers=h).json()["items"]]


def test_policy_blocked_and_insufficient_evidence(env, auth):
    h = auth.as_("lead")
    blocked = investigate(env, h, "FO-1008")
    assert blocked["status"] == "completed" and blocked["disposition"] == "blocked" and blocked["output"]["action_proposals"] == []
    vague = investigate(env, h, "FO-1009")
    assert vague["disposition"] == "insufficient_evidence" and vague["output"]["evidence"] == []
    assert "request_more_information" in proposals(env, h, vague["id"])


def test_failure_modes_and_safe_retry(env, auth):
    a = auth.as_("admin")
    h = auth.as_("lead")
    assert env.put(f"{API}/admin/config", json={"fault": "timeout"}, headers=a).status_code == 200
    run = investigate(env, h, "FO-1003")
    assert run["status"] == "failed" and run["error_code"] == "provider_timeout" and run["output"] is None
    ev = env.get(f"{API}/investigations/{run['id']}/events", headers=h).json()["items"]
    assert sum(1 for e in ev if e["step"] == "plan_generation") == 3  # capped retries recorded
    assert env.put(f"{API}/admin/config", json={"fault": "none"}, headers=a).status_code == 200
    r = env.post(f"{API}/investigations/{run['id']}/retry", headers=h)
    assert r.status_code == 202
    assert env.get(f"{API}/investigations/{r.json()['id']}", headers=h).json()["status"] == "awaiting_review"

    env.put(f"{API}/admin/config", json={"fault": "malformed"}, headers=a)
    repaired = investigate(env, h, "FO-1004")
    assert repaired["status"] == "awaiting_review"
    steps = env.get(f"{API}/investigations/{repaired['id']}/events", headers=h).json()["items"]
    assert any(e["step"] == "schema_validation" and e["status"] == "warn" for e in steps)

    env.put(f"{API}/admin/config", json={"fault": "retrieval"}, headers=a)
    nr = investigate(env, h, "FO-1010")
    assert nr["status"] == "failed" and nr["error_code"] == "retrieval_unavailable"


def test_cancel_only_active_runs(env, auth):
    h = auth.as_("lead")
    run = investigate(env, h, "FO-1001")
    r = env.post(f"{API}/investigations/{run['id']}/cancel", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_ticket_list_filters_and_demo_ticket_creation(env, auth):
    h = auth.as_("lead")
    lst = env.get(f"{API}/tickets", params={"priority": "high", "category": "connectivity"}, headers=h).json()
    assert {t["display_id"] for t in lst["items"]} == {"FO-1001", "FO-1010"}
    assert env.get(f"{API}/tickets", params={"q": "lt-4412"}, headers=h).json()["total"] == 1
    r = env.post(f"{API}/tickets", headers=h, json={"title": "New synthetic ticket", "description": "A long enough description here.", "category": "device", "priority": "low"})
    assert r.status_code == 201 and r.json()["display_id"] == "FO-1011" and r.json()["synthetic"] is True


def test_overview_and_knowledge_and_search(env, auth):
    h = auth.as_("lead")
    ov = env.get(f"{API}/overview", headers=h).json()
    assert ov["open_tickets"] == 10 and ov["awaiting_review"] == 0
    hits = env.post(f"{API}/knowledge/search", json={"query": "vpn password rejected after change"}, headers=h).json()["items"]
    assert hits and any(x["flagged_untrusted"] for x in hits)
    srcs = {s["key"]: s for s in env.get(f"{API}/knowledge/sources", headers=h).json()["items"]}
    assert srcs["kb-printer-001"]["status"] == "inactive" and "kb-sec-001" in srcs
    ag = {s["key"] for s in env.get(f"{API}/knowledge/sources", headers=auth.as_("agent")).json()["items"]}
    assert "kb-sec-001" not in ag  # restricted source invisible to agents
    assert env.get(f"{API}/knowledge/sources/kb-sec-001", headers=auth.as_("agent")).status_code == 404


def test_evaluation_suite_passes_and_is_persisted(env, auth):
    h = auth.as_("lead")
    r = env.post(f"{API}/evaluations/runs", json={}, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    failed = [x["case_key"] for x in body["results"] if not x["passed"]]
    assert failed == [] and body["summary"]["cases"] == 23 and body["summary"]["passed"] == 23
    assert env.get(f"{API}/evaluations/runs/{body['id']}", headers=h).json()["summary"] == body["summary"]
    assert env.post(f"{API}/evaluations/runs", json={}, headers=auth.as_("agent")).status_code == 403


def test_demo_reset_requires_confirmation_and_keeps_audit(env, auth):
    a = auth.as_("admin")
    investigate(env, a, "FO-1001")
    assert env.post(f"{API}/admin/demo-reset", json={"confirm": "no"}, headers=a).status_code == 400
    r = env.post(f"{API}/admin/demo-reset", json={"confirm": "RESET"}, headers=a)
    assert r.status_code == 200 and r.json()["dataset_version"] == 2
    assert env.get(f"{API}/investigations", headers=a).json()["items"] == []
    events = {e["event_type"] for e in env.get(f"{API}/audit-events", params={"page_size": 200}, headers=a).json()["items"]}
    assert {"investigation_started", "demo_reset"} <= events  # history retained, reset recorded
