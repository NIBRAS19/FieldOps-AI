import os

os.environ.update({"SECRET_KEY": "test-secret-key-0123456789abcdef", "RUN_STEP_DELAY_MS": "0", "DEMO_MODE": "true", "DEMO_AUTH_ENABLED": "true",
                   "DATABASE_URL": "sqlite://", "INVESTIGATIONS_PER_MINUTE": "50"})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.seed import seed_workspace  # noqa: E402
from app.db.session import init_db, session_factory  # noqa: E402


@pytest.fixture()
def env():
    get_settings.cache_clear()
    eng = init_db("sqlite://")
    Base.metadata.create_all(eng)
    with session_factory()() as s:
        seed_workspace(s)
        s.commit()
    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


class Auth:
    def __init__(self, client: TestClient):
        self.c = client
        self.users = {u["role"] + ("2" if u["display_name"].startswith("Dana") else ""): u["id"] for u in client.get("/api/v1/auth/demo-users").json()["users"]}

    def as_(self, key: str) -> dict:
        r = self.c.post("/api/v1/auth/demo-login", json={"user_id": self.users[key]})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth(env):
    return Auth(env)


def investigate(client: TestClient, headers: dict, display_id: str) -> dict:
    r = client.post(f"/api/v1/tickets/{display_id}/investigations", json={}, headers=headers)
    assert r.status_code == 202, r.text
    run = client.get(f"/api/v1/investigations/{r.json()['id']}", headers=headers).json()  # background task already ran
    return run


def proposals(client: TestClient, headers: dict, run_id: str) -> dict:
    items = client.get("/api/v1/action-proposals", params={"status": None}, headers=headers).json()["items"]
    return {p["action_type"] + (":" + p["payload"].get("to", "") if p["action_type"] == "change_local_status" else ""): p for p in items if p["run_id"] == run_id}
