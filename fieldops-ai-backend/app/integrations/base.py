from typing import Protocol

from sqlalchemy.orm import Session

from app.db import models as m


class AdapterError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ActionAdapter(Protocol):
    name: str
    simulated: bool
    idempotent: bool

    def execute(self, session: Session, proposal: m.ActionProposal, ticket: m.Ticket, actor_id: str | None) -> dict: ...
