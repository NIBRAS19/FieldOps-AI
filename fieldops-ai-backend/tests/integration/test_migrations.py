import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect

from app.db.models import Base


def test_migration_matches_models_and_is_reversible(tmp_path):
    url = f"sqlite:///{tmp_path}/m.db"
    env = {**os.environ, "DATABASE_URL": url}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], env=env, capture_output=True, text=True)  # noqa: E731
    up = run("upgrade", "head")
    assert up.returncode == 0, up.stderr
    tables = set(inspect(create_engine(url)).get_table_names())
    assert set(Base.metadata.tables) <= tables
    assert run("check").returncode == 0  # no drift between models and migration
    assert run("downgrade", "base").returncode == 0
