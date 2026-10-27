"""Idempotent: creates the demo workspace if none exists. Run after migrations."""
from app.core.config import get_settings
from app.db.seed import ensure_demo_workspace
from app.db.session import session_factory

if __name__ == "__main__":
    if get_settings().demo_mode:
        with session_factory()() as s:
            ws = ensure_demo_workspace(s)
            print(f"demo workspace ready: {ws.id}")
