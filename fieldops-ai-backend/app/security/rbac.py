from enum import StrEnum

from app.domain.enums import Role


class Perm(StrEnum):
    tickets_read = "tickets:read"
    tickets_write = "tickets:write"
    investigate = "investigations:start"
    investigations_read = "investigations:read"
    label_runs = "investigations:label"
    proposals_read = "proposals:read"
    proposals_decide = "proposals:decide"
    kb_read = "kb:read"
    kb_reindex = "kb:reindex"
    kb_manage = "kb:manage"
    eval_read = "eval:read"
    eval_run = "eval:run"
    audit_read = "audit:read"
    audit_read_all = "audit:read_all"
    config_manage = "config:manage"
    users_manage = "users:manage"
    demo_reset = "admin:demo_reset"


_READ = {Perm.tickets_read, Perm.investigations_read, Perm.proposals_read, Perm.kb_read, Perm.eval_read, Perm.audit_read}
_WORK = {Perm.tickets_write, Perm.investigate, Perm.proposals_decide}
MATRIX: dict[str, set[Perm]] = {
    Role.readonly: set(_READ),
    Role.agent: _READ | _WORK,
    Role.lead: _READ | _WORK | {Perm.label_runs, Perm.kb_reindex, Perm.eval_run, Perm.audit_read_all},
    Role.admin: _READ | _WORK | {Perm.label_runs, Perm.kb_reindex, Perm.kb_manage, Perm.eval_run, Perm.audit_read_all,
                                 Perm.config_manage, Perm.users_manage, Perm.demo_reset},
}


def has(role: str, perm: Perm) -> bool:
    return perm in MATRIX.get(role, set())
