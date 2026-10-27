"""Provider adapter boundary. Fixture mode is mandatory; live/local providers plug in here later.
Model output is untrusted: the pipeline validates schema and citations regardless of provider."""
from typing import Protocol

from app.core.errors import AppError


class ProviderTimeout(Exception):
    pass


class ModelAdapter(Protocol):
    provider: str
    model: str

    def generate_plan(self, *, title: str, customer: str, evidence: list[dict], attempt: int) -> dict: ...


class FixtureModel:
    """Deterministic stand-in for a language model, with optional fault injection for tests/demos."""

    provider = "fixture"
    model = "fixture-v1"

    def __init__(self, fault: str = "none"):
        self.fault = fault

    def generate_plan(self, *, title: str, customer: str, evidence: list[dict], attempt: int) -> dict:
        if self.fault == "timeout":
            raise ProviderTimeout("simulated provider timeout")
        if self.fault == "malformed" and attempt == 1:
            return {"summary": "", "steps": [{"n": 1, "instruction": "x", "evidence_ids": ["kb-fake-999-c01"], "requires_human_action": True}], "draft": ""}
        steps = [{"n": i + 1, "instruction": e["snippet"], "evidence_ids": [e["chunk_id"]], "requires_human_action": True} for i, e in enumerate(evidence)]
        if not steps:
            draft = (f"Hi {customer},\n\nThanks for contacting IT. To help we need a few details:\n1. What were you trying to do when the problem started?\n"
                     "2. Any error message or code shown?\n3. Which device or asset tag is affected, and since when?\n\n— Operations team (draft, not sent)")
            return {"summary": f"{title}: not enough information or evidence to recommend steps.", "steps": [], "draft": draft}
        body = "\n".join(f"{s['n']}. {s['instruction']}" for s in steps)
        draft = (f'Hi {customer},\n\nThanks for contacting IT about "{title}". Here is what we suggest:\n{body}\n\n'
                 "If this does not help, reply on the ticket and we will escalate.\n\n— Operations team (draft, not sent)")
        return {"summary": f"{title}: {len(steps)} recommended step(s) from {len(evidence)} supporting source section(s).", "steps": steps, "draft": draft}


def get_adapter(mode: str, fault: str = "none") -> ModelAdapter:
    if mode == "fixture":
        return FixtureModel(fault)
    raise AppError("MODEL_MODE_UNAVAILABLE", f"Model mode '{mode}' is not implemented in this build. Use fixture mode.", 503)
