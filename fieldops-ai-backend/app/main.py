import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import router
from app.core.config import get_settings
from app.core.errors import install_handlers
from app.db.seed import ensure_demo_workspace
from app.db.session import session_factory
from app.observability.logging import correlation_id, setup_logging
from app.services.investigations import recover_stale_runs

log = logging.getLogger("app")
_CID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    s.validate_safety()
    setup_logging(s.log_level)
    with session_factory()() as session:
        n = recover_stale_runs(session)
        if n:
            log.warning("recovered %d interrupted run(s)", n)
        if s.demo_mode:
            ensure_demo_workspace(session)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="1.0.0", lifespan=lifespan,
                  description="FieldOps AI backend. Proposed portfolio MVP: synthetic data, simulated integrations, human-approved actions only.")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()], allow_methods=["GET", "POST", "PUT"],
                       allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"], expose_headers=["X-Correlation-ID"])

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        incoming = request.headers.get("x-correlation-id", "")
        cid = incoming if _CID.match(incoming) else uuid.uuid4().hex
        token = correlation_id.set(cid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            log.info("request", extra={"event": "http", "path": request.url.path, "method": request.method, "duration_ms": round((time.perf_counter() - t0) * 1000)})
            correlation_id.reset(token)
        response.headers["X-Correlation-ID"] = cid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    install_handlers(app)
    app.include_router(router)
    return app


app = create_app()
