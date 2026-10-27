import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import models as m
from app.db.seed_data import ASSETS, CASES, CATEGORY_TEAM, KB, TEAMS, TICKETS, USERS
from app.db.types import utcnow

NS = uuid.UUID("6f1c2b1e-4c1a-4a53-9a3e-0f1e5d7a9b10")
EVAL_FILE = Path(__file__).resolve().parents[2] / "data" / "evals" / "synthetic-eval-v1.json"
DEMO_DOMAIN = "demo.fieldops.example"


def sid(ws_id: str, key: str) -> str:
    return str(uuid.uuid5(NS, f"{ws_id}:{key}"))


def default_settings(dataset_version: int = 1) -> dict:
    s = get_settings()
    return {"dataset_version": dataset_version, "top_k": s.retrieval_top_k, "max_retries": s.max_retries,
            "approval_expiry_minutes": s.approval_expiry_minutes, "fault": "none"}


def seed_workspace(session: Session, name: str = "Demo Workspace", mode: str = "demo") -> m.Workspace:
    ws = m.Workspace(name=name, mode=mode, settings_json=default_settings())
    session.add(ws)
    session.flush()
    for t in TEAMS:
        session.add(m.Team(id=sid(ws.id, f"team:{t}"), workspace_id=ws.id, name=t))
    session.flush()
    for key, dn, role, team in USERS:
        session.add(m.User(id=sid(ws.id, f"user:{key}"), workspace_id=ws.id, display_name=dn, email=f"{key}@{DEMO_DOMAIN}", role=role,
                           team_id=sid(ws.id, f"team:{team}") if team else None))
    session.flush()
    seed_domain(session, ws)
    session.flush()
    return ws


def seed_domain(session: Session, ws: m.Workspace) -> None:
    now = utcnow()
    for tag, typ, loc in ASSETS:
        session.add(m.Asset(id=sid(ws.id, f"asset:{tag}"), workspace_id=ws.id, asset_tag=tag, asset_type=typ, location_alias=loc, warranty_state="synthetic"))
    session.flush()
    for n, title, desc, cat, prio, status, assignee, age, sla, cust, asset in TICKETS:
        session.add(m.Ticket(
            id=sid(ws.id, f"ticket:{n}"), workspace_id=ws.id, display_id=f"FO-{1000 + n}", title=title, description=desc, category=cat, priority=prio,
            status=status, assignee_id=sid(ws.id, f"user:{assignee}") if assignee else None, team_id=sid(ws.id, f"team:{CATEGORY_TEAM[cat]}"),
            customer_alias=cust, asset_id=sid(ws.id, f"asset:{asset}") if asset else None, sla_due_at=now + timedelta(hours=sla),
            created_at=now - timedelta(hours=age), updated_at=now - timedelta(hours=age / 2)))
    for did, title, cat, res in CASES:
        session.add(m.HistoricalCase(id=sid(ws.id, f"case:{did}"), workspace_id=ws.id, display_id=did, title=title, category=cat, resolution=res))
    for key, title, typ, ver, owner, roles, status, chunks in KB:
        src = m.KnowledgeSource(id=sid(ws.id, f"src:{key}"), workspace_id=ws.id, key=key, title=title, source_type=typ, owner_label=owner, version=ver,
                                status=status, visibility_scope={"roles": roles}, content_hash=hashlib.sha256("\n".join(c[1] for c in chunks).encode()).hexdigest())
        session.add(src)
        session.flush()
        for i, (section, text, kw, tags, conflicts) in enumerate(chunks, 1):
            ck = f"{key}-c{i:02d}"
            session.add(m.KnowledgeChunk(id=sid(ws.id, f"chunk:{ck}"), workspace_id=ws.id, source_id=src.id, key=ck, chunk_index=i, section_title=section,
                                         text_content=text, metadata_json={"keywords": kw, "tags": tags, "conflicts_with": conflicts}))
    session.flush()
    seed_eval_dataset(session, ws)


def seed_eval_dataset(session: Session, ws: m.Workspace) -> None:
    data = json.loads(EVAL_FILE.read_text())
    ds = m.EvaluationDataset(id=sid(ws.id, f"dataset:{data['name']}:{data['version']}"), workspace_id=ws.id, name=data["name"], version=data["version"],
                             description=data["description"])
    session.add(ds)
    session.flush()
    for c in data["cases"]:
        session.add(m.EvaluationCase(id=sid(ws.id, f"case:{ds.id}:{c['case_key']}"), workspace_id=ws.id, dataset_id=ds.id, case_key=c["case_key"],
                                     category=c["category"], name=c["name"], definition_json=c))


DOMAIN_TABLES = [m.EvaluationResult, m.EvaluationRun, m.EvaluationCase, m.EvaluationDataset, m.ToolExecution, m.ApprovalDecision, m.ActionProposal,
                 m.RunEvent, m.InvestigationRun, m.TicketEvent, m.Ticket, m.HistoricalCase, m.KnowledgeChunk, m.KnowledgeSource, m.Asset]


def reset_domain(session: Session, ws: m.Workspace) -> int:
    """Delete synthetic domain data and re-seed. audit_events are intentionally preserved (append-only)."""
    for t in DOMAIN_TABLES:
        session.execute(delete(t).where(t.workspace_id == ws.id))
    for key, _dn, role, team in USERS:  # restore seeded roles and activation
        u = session.get(m.User, sid(ws.id, f"user:{key}"))
        if u:
            u.role, u.active = role, True
    ver = int(ws.settings_json.get("dataset_version", 1)) + 1
    ws.settings_json = default_settings(ver)
    seed_domain(session, ws)
    session.flush()
    return ver


def ensure_demo_workspace(session: Session) -> m.Workspace:
    ws = session.scalar(select(m.Workspace).where(m.Workspace.mode == "demo").limit(1))
    if ws:
        return ws
    ws = seed_workspace(session)
    session.commit()
    return ws
