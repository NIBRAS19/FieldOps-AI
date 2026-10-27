import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.evaluation.runner import METRIC_DEFINITIONS, run_case, summarize
from app.core.config import get_settings
from app.core.errors import AppError
from app.db import models as m
from app.db.types import utcnow
from app.services import audit

_sem = threading.Semaphore(get_settings().eval_max_concurrency)


def list_datasets(session: Session, user: m.User) -> list[dict]:
    out = []
    for d in session.scalars(select(m.EvaluationDataset).where(m.EvaluationDataset.workspace_id == user.workspace_id)):
        cases = session.scalars(select(m.EvaluationCase).where(m.EvaluationCase.dataset_id == d.id).order_by(m.EvaluationCase.case_key)).all()
        out.append({"id": d.id, "name": d.name, "version": d.version, "description": d.description,
                    "cases": [{"case_key": c.case_key, "category": c.category, "name": c.name, "expected": c.definition_json.get("expected")} for c in cases]})
    return out


def start_run(session: Session, user: m.User, dataset_id: str | None) -> m.EvaluationRun:
    if not _sem.acquire(blocking=False):  # cap concurrency
        raise AppError("RATE_LIMITED", "An evaluation run is already in progress.", 429)
    try:
        q = select(m.EvaluationDataset).where(m.EvaluationDataset.workspace_id == user.workspace_id)
        ds = session.scalar(q.where(m.EvaluationDataset.id == dataset_id) if dataset_id else q.order_by(m.EvaluationDataset.version.desc()))
        if not ds:
            raise AppError("NOT_FOUND", "Evaluation dataset not found.", 404)
        ws = session.get(m.Workspace, user.workspace_id)
        cfg = {"model": "fixture-v1", "prompt_version": "prompt-2026.10", "workflow_version": "wf-1.0.0", "retrieval": "lexical",
               "top_k": ws.settings_json.get("top_k", 4), "max_retries": ws.settings_json.get("max_retries", 2), "dataset": f"{ds.name}@v{ds.version}"}
        run = m.EvaluationRun(workspace_id=user.workspace_id, dataset_id=ds.id, started_by=user.id, config_json=cfg)
        session.add(run)
        session.flush()
        results = []
        for c in session.scalars(select(m.EvaluationCase).where(m.EvaluationCase.dataset_id == ds.id).order_by(m.EvaluationCase.case_key)):
            out = run_case(session, ws, c.definition_json, cfg)
            results.append({**out, "case_key": c.case_key})
            session.add(m.EvaluationResult(workspace_id=user.workspace_id, run_id=run.id, case_key=c.case_key, category=c.category, name=c.name,
                                           expected=c.definition_json.get("expected", ""), actual=out["actual"][:300], checks_json=[{"name": n, "pass": ok} for n, ok in out["checks"]],
                                           passed=out["passed"], metrics_json=out["metrics"], latency_ms=out["latency_ms"]))
        run.summary_json, run.status, run.finished_at = summarize(results), "completed", utcnow()
        audit.record(session, user.workspace_id, "evaluation_run", "evaluation_run", run.id, user=user, after=run.summary_json, reason=f"{len(results)} cases on {cfg['dataset']}.")
        session.commit()
        return run
    finally:
        _sem.release()


def run_out(session: Session, run: m.EvaluationRun, include_results: bool = True) -> dict:
    out = {"id": run.id, "dataset_id": run.dataset_id, "status": run.status, "config": run.config_json, "summary": run.summary_json, "started_by": run.started_by,
           "started_at": run.started_at, "finished_at": run.finished_at, "metric_definitions": METRIC_DEFINITIONS}
    if include_results:
        rows = session.scalars(select(m.EvaluationResult).where(m.EvaluationResult.run_id == run.id).order_by(m.EvaluationResult.case_key)).all()
        out["results"] = [{"case_key": r.case_key, "category": r.category, "name": r.name, "expected": r.expected, "actual": r.actual, "checks": r.checks_json,
                           "passed": r.passed, "metrics": r.metrics_json, "latency_ms": r.latency_ms} for r in rows]
    return out


def get_run(session: Session, user: m.User, run_id: str) -> m.EvaluationRun:
    r = session.scalar(select(m.EvaluationRun).where(m.EvaluationRun.id == run_id, m.EvaluationRun.workspace_id == user.workspace_id))
    if not r:
        raise AppError("NOT_FOUND", "Evaluation run not found.", 404)
    return r


def list_runs(session: Session, user: m.User) -> list[m.EvaluationRun]:
    return list(session.scalars(select(m.EvaluationRun).where(m.EvaluationRun.workspace_id == user.workspace_id).order_by(m.EvaluationRun.started_at.desc())))
