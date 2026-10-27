from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        kw: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kw["poolclass"] = StaticPool
        eng = create_engine(url, **kw)

        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):  # enforce foreign keys on SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return eng
    return create_engine(url, pool_pre_ping=True)


def init_db(url: str | None = None) -> Engine:
    global engine, SessionLocal
    engine = make_engine(url or get_settings().database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine


def session_factory() -> sessionmaker[Session]:
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    return SessionLocal


def get_session() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()
