from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")  # clients can never smuggle workspace_id, tool lists, prompts, or credentials


class DemoLogin(In):
    user_id: str = Field(max_length=36)


class TicketCreate(In):
    title: str = Field(min_length=5, max_length=300)
    description: str = Field(min_length=10, max_length=4000)
    category: Literal["access", "connectivity", "device", "application", "request", "other"] = "other"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    asset_tag: str | None = Field(default=None, max_length=60)
    customer_alias: str | None = Field(default=None, max_length=120)


class NoteIn(In):
    text: str = Field(min_length=3, max_length=2000)


class AssignIn(In):
    assignee_id: str | None = Field(default=None, max_length=36)


class StartInvestigation(In):
    mode: Literal["fixture"] = "fixture"
    include_related_cases: bool = True
    retrieval_profile: Literal["lexical_v1"] = "lexical_v1"


class LabelIn(In):
    label: Literal["helpful", "partially_helpful", "unhelpful"]
    reason: str = Field(default="", max_length=300)


class ApproveIn(In):
    payload_hash: str = Field(min_length=8, max_length=64)
    comment: str | None = Field(default=None, max_length=500)


class EditApproveIn(ApproveIn):
    edited_payload: dict


class RejectIn(In):
    payload_hash: str = Field(min_length=1, max_length=64)
    reason_code: Literal["unsupported", "unsafe", "incorrect", "unnecessary", "other"]
    comment: str | None = Field(default=None, max_length=500)


class SearchIn(In):
    query: str = Field(min_length=2, max_length=300)
    top_k: int | None = Field(default=None, ge=1, le=8)


class SourceCreate(In):
    title: str = Field(min_length=3, max_length=300)
    text: str = Field(min_length=20, max_length=20000)


class SourceVersion(In):
    text: str = Field(min_length=20, max_length=20000)


class SourceStatus(In):
    status: Literal["active", "inactive"]


class EvalStart(In):
    dataset_id: str | None = Field(default=None, max_length=36)


class ConfigPatch(In):
    top_k: int | None = None
    max_retries: int | None = None
    approval_expiry_minutes: int | None = None
    fault: str | None = None


class RoleIn(In):
    role: Literal["admin", "lead", "agent", "readonly"]


class ResetIn(In):
    confirm: str = Field(max_length=20)
