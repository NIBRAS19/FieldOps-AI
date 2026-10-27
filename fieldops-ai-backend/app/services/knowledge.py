import hashlib

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai.retrieval import ChunkRef, search
from app.core.errors import AppError
from app.db import models as m
from app.db.types import utcnow
from app.domain.policy import INJECTION
from app.services import audit


def _roles(src: m.KnowledgeSource) -> list[str]:
    return list((src.visibility_scope or {}).get("roles", []))


def eligible_chunks(session: Session, ws_id: str, role: str) -> tuple[list[ChunkRef], int, int]:
    """Access and status filters are applied BEFORE any content reaches retrieval or a model (FR-043)."""
    sources = session.scalars(select(m.KnowledgeSource).where(m.KnowledgeSource.workspace_id == ws_id)).all()
    ok = {s.id: s for s in sources if s.status == "active" and role in _roles(s)}
    if not ok:
        return [], 0, len(sources)
    rows = session.scalars(select(m.KnowledgeChunk).where(m.KnowledgeChunk.workspace_id == ws_id, m.KnowledgeChunk.source_id.in_(list(ok)))
                           .order_by(m.KnowledgeChunk.key)).all()
    refs = [ChunkRef(key=c.key, source_key=ok[c.source_id].key, source_title=ok[c.source_id].title, source_version=ok[c.source_id].version,
                     source_owner=ok[c.source_id].owner_label, section=c.section_title, text=c.text_content,
                     keywords=c.metadata_json.get("keywords", ""), tags=tuple(c.metadata_json.get("tags", [])),
                     conflicts_with=c.metadata_json.get("conflicts_with")) for c in rows]
    return refs, len(ok), len(sources) - len(ok)


def _visible(user: m.User, s: m.KnowledgeSource) -> bool:
    return user.role == "admin" or user.role in _roles(s)


def list_sources(session: Session, user: m.User) -> list[dict]:
    counts = dict(session.execute(select(m.KnowledgeChunk.source_id, func.count()).where(m.KnowledgeChunk.workspace_id == user.workspace_id)
                                  .group_by(m.KnowledgeChunk.source_id)).all())
    rows = session.scalars(select(m.KnowledgeSource).where(m.KnowledgeSource.workspace_id == user.workspace_id).order_by(m.KnowledgeSource.key)).all()
    return [source_out(s, counts.get(s.id, 0)) for s in rows if _visible(user, s)]


def source_out(s: m.KnowledgeSource, chunk_count: int) -> dict:
    return {"id": s.id, "key": s.key, "title": s.title, "source_type": s.source_type, "owner_label": s.owner_label, "version": s.version, "status": s.status,
            "visibility_roles": _roles(s), "chunk_count": chunk_count, "updated_at": s.updated_at}


def get_source(session: Session, user: m.User, ident: str) -> m.KnowledgeSource:
    s = session.scalar(select(m.KnowledgeSource).where(m.KnowledgeSource.workspace_id == user.workspace_id,
                                                         (m.KnowledgeSource.id == ident) | (m.KnowledgeSource.key == ident)))
    if not s or not _visible(user, s):
        raise AppError("NOT_FOUND", "Knowledge source not found.", 404)
    return s


def source_detail(session: Session, user: m.User, ident: str) -> dict:
    s = get_source(session, user, ident)
    chunks = session.scalars(select(m.KnowledgeChunk).where(m.KnowledgeChunk.source_id == s.id).order_by(m.KnowledgeChunk.chunk_index)).all()
    cited = session.scalar(select(func.count()).select_from(m.InvestigationRun).where(m.InvestigationRun.workspace_id == user.workspace_id,
                           m.InvestigationRun.output_json.is_not(None))) or 0
    refs = sum(1 for r in session.scalars(select(m.InvestigationRun).where(m.InvestigationRun.workspace_id == user.workspace_id,
               m.InvestigationRun.output_json.is_not(None))) if any(e.get("source_id") == s.key for e in r.output_json.get("evidence", [])))
    del cited
    return {**source_out(s, len(chunks)), "cited_in_runs": refs, "chunks": [
        {"key": c.key, "section": c.section_title, "text": c.text_content, "tags": c.metadata_json.get("tags", []),
         "conflicts_with": c.metadata_json.get("conflicts_with"), "flagged_untrusted": bool(INJECTION.search(c.text_content))} for c in chunks]}


def search_knowledge(session: Session, user: m.User, query: str, top_k: int | None = None) -> list[dict]:
    chunks, _, _ = eligible_chunks(session, user.workspace_id, user.role)
    ws = session.get(m.Workspace, user.workspace_id)
    hits, _ = search(query[:300], chunks, top_k or int(ws.settings_json.get("top_k", 4)))
    return [{"chunk_id": c.key, "source_id": c.source_key, "title": c.source_title, "version": c.source_version, "section": c.section, "snippet": c.text,
             "score": score, "flagged_untrusted": bool(INJECTION.search(c.text))} for c, score in hits]


def set_status(session: Session, user: m.User, ident: str, status: str) -> m.KnowledgeSource:
    if status not in ("active", "inactive"):
        raise AppError("VALIDATION_ERROR", "status must be active or inactive.", 422)
    s = get_source(session, user, ident)
    before = s.status
    s.status, s.updated_at = status, utcnow()
    audit.record(session, user.workspace_id, "kb_activated" if status == "active" else "kb_deactivated", "knowledge_source", s.key, user=user,
                 before={"status": before}, after={"status": status}, reason="Citation history from earlier runs is unchanged.")
    return s


def reindex(session: Session, user: m.User, ident: str) -> m.KnowledgeSource:
    s = get_source(session, user, ident)
    texts = session.scalars(select(m.KnowledgeChunk.text_content).where(m.KnowledgeChunk.source_id == s.id).order_by(m.KnowledgeChunk.chunk_index)).all()
    s.content_hash = hashlib.sha256("\n".join(texts).encode()).hexdigest()
    s.updated_at = utcnow()
    audit.record(session, user.workspace_id, "kb_reindexed", "knowledge_source", s.key, user=user, after={"chunks": len(texts)})
    return s


def _chunks_from_text(text: str) -> list[str]:
    parts = [p.strip() for p in text.split("\n\n") if p.strip()][:12]
    if not parts:
        raise AppError("VALIDATION_ERROR", "Text produced no chunks.", 422)
    return parts


def create_manual_source(session: Session, user: m.User, title: str, text: str) -> m.KnowledgeSource:
    n = (session.scalar(select(func.count()).select_from(m.KnowledgeSource).where(m.KnowledgeSource.workspace_id == user.workspace_id,
                        m.KnowledgeSource.key.like("kb-manual-%"))) or 0) + 1
    s = m.KnowledgeSource(workspace_id=user.workspace_id, key=f"kb-manual-{n:03d}", title=title, source_type="Manual text", owner_label=user.display_name,
                          content_hash=hashlib.sha256(text.encode()).hexdigest())
    session.add(s)
    session.flush()
    _add_chunks(session, s, _chunks_from_text(text))
    audit.record(session, user.workspace_id, "kb_added", "knowledge_source", s.key, user=user,
                 reason="Content is treated as data, never as instructions.")
    return s


def _add_chunks(session: Session, s: m.KnowledgeSource, parts: list[str]) -> None:
    for i, part in enumerate(parts, 1):
        session.add(m.KnowledgeChunk(workspace_id=s.workspace_id, source_id=s.id, key=f"{s.key}-v{s.version}-c{i:02d}" if s.version > 1 else f"{s.key}-c{i:02d}",
                                     chunk_index=i, section_title=f"Section {i}", text_content=part, metadata_json={"keywords": "", "tags": []}))


def new_version(session: Session, user: m.User, ident: str, text: str) -> m.KnowledgeSource:
    """Replace content with a new version. Earlier runs keep their own evidence snapshots (FR-045)."""
    s = get_source(session, user, ident)
    before = s.version
    session.execute(delete(m.KnowledgeChunk).where(m.KnowledgeChunk.source_id == s.id))
    s.version += 1
    s.content_hash = hashlib.sha256(text.encode()).hexdigest()
    s.updated_at = utcnow()
    session.flush()
    _add_chunks(session, s, _chunks_from_text(text))
    audit.record(session, user.workspace_id, "kb_version_created", "knowledge_source", s.key, user=user, before={"version": before}, after={"version": s.version})
    return s
