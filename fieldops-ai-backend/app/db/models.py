from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import JSONType, UTCDateTime, new_id, utcnow


class Base(DeclarativeBase):
    pass


def _fk(target: str, nullable: bool = False):
    return mapped_column(String(36), ForeignKey(target), nullable=nullable, index=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(20), default="demo")  # demo | pilot | production
    settings_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("workspace_id", "email"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    display_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    team_id: Mapped[str | None] = _fk("teams.id", True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    asset_tag: Mapped[str] = mapped_column(String(60))
    asset_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="in_service")
    location_alias: Mapped[str] = mapped_column(String(120), default="")
    warranty_state: Mapped[str] = mapped_column(String(30), default="unknown")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("workspace_id", "display_id"), Index("ix_tickets_ws_status", "workspace_id", "status"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    display_id: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="other")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="new")
    assignee_id: Mapped[str | None] = _fk("users.id", True)
    team_id: Mapped[str | None] = _fk("teams.id", True)
    customer_alias: Mapped[str | None] = mapped_column(String(120), nullable=True)
    asset_id: Mapped[str | None] = _fk("assets.id", True)
    sla_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    ticket_id: Mapped[str] = _fk("tickets.id")
    actor_id: Mapped[str | None] = _fk("users.id", True)
    event_type: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class HistoricalCase(Base):
    __tablename__ = "historical_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    display_id: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(30))
    resolution: Mapped[str] = mapped_column(Text)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    key: Mapped[str] = mapped_column(String(80))  # stable human-readable ID used in citations
    title: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(60))
    owner_label: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|inactive|indexing|failed
    visibility_scope: Mapped[dict] = mapped_column(JSONType, default=lambda: {"roles": ["admin", "lead", "agent", "readonly"]})
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    source_id: Mapped[str] = _fk("knowledge_sources.id")
    key: Mapped[str] = mapped_column(String(100))
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_title: Mapped[str] = mapped_column(String(200))
    text_content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict)  # keywords, tags, conflicts_with
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    ticket_id: Mapped[str] = _fk("tickets.id")
    started_by: Mapped[str] = _fk("users.id")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    disposition: Mapped[str | None] = mapped_column(String(30), nullable=True)  # awaiting_approval|suggestion_only|blocked|insufficient_evidence
    model_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(40))
    workflow_version: Mapped[str] = mapped_column(String(40))
    retrieval_config: Mapped[dict] = mapped_column(JSONType, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    output_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    label: Mapped[str | None] = mapped_column(String(30), nullable=True)
    label_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    eval_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    run_id: Mapped[str] = _fk("investigation_runs.id")
    sequence_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40), default="step")
    step_name: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    output_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    source_ids: Mapped[list] = mapped_column(JSONType, default=list)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ActionProposal(Base):
    __tablename__ = "action_proposals"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"), Index("ix_prop_ws_status", "workspace_id", "status"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    ticket_id: Mapped[str] = _fk("tickets.id")
    run_id: Mapped[str] = _fk("investigation_runs.id")
    proposed_by: Mapped[str | None] = _fk("users.id", True)  # the human who started the run
    action_type: Mapped[str] = mapped_column(String(40))
    risk_class: Mapped[str] = mapped_column(String(10))
    risk_reason: Mapped[str] = mapped_column(String(300), default="")
    payload_json: Mapped[dict] = mapped_column(JSONType)
    original_payload_json: Mapped[dict] = mapped_column(JSONType)
    payload_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text, default="")
    expected_effect: Mapped[str] = mapped_column(String(300), default="")
    rollback_note: Mapped[str] = mapped_column(String(300), default="")
    evidence_ids: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    result_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    proposal_id: Mapped[str] = _fk("action_proposals.id")
    reviewer_id: Mapped[str] = _fk("users.id")
    decision: Mapped[str] = mapped_column(String(20))
    original_payload_hash: Mapped[str] = mapped_column(String(64))
    approved_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edited_payload_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    proposal_id: Mapped[str] = _fk("action_proposals.id")
    adapter_name: Mapped[str] = mapped_column(String(60))
    operation_name: Mapped[str] = mapped_column(String(60))
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    request_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    result_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="started")
    idempotency_key: Mapped[str] = mapped_column(String(140))
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_ws_created", "workspace_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    actor_type: Mapped[str] = mapped_column(String(10))  # user|system|agent
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(80), index=True)
    result: Mapped[str] = mapped_column(String(10), default="success")  # success|denied|failure|info
    before_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


@event.listens_for(AuditEvent, "before_update")
@event.listens_for(AuditEvent, "before_delete")
def _audit_append_only(*_):
    raise RuntimeError("audit_events is append-only; record a new correcting event instead.")


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (UniqueConstraint("workspace_id", "name", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (UniqueConstraint("dataset_id", "case_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str] = _fk("evaluation_datasets.id")
    case_key: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    definition_json: Mapped[dict] = mapped_column(JSONType)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str] = _fk("evaluation_datasets.id")
    started_by: Mapped[str] = _fk("users.id")
    status: Mapped[str] = mapped_column(String(20), default="running")
    config_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    summary_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    run_id: Mapped[str] = _fk("evaluation_runs.id")
    case_key: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    expected: Mapped[str] = mapped_column(String(300))
    actual: Mapped[str] = mapped_column(String(300))
    checks_json: Mapped[list] = mapped_column(JSONType, default=list)
    passed: Mapped[bool] = mapped_column(Boolean)
    metrics_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    reviewer_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
