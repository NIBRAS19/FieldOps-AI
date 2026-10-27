import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability.logging import correlation_id

log = logging.getLogger("app.errors")


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _body(code: str, message: str, extra: dict | None = None) -> dict:
    err = {"code": code, "message": message, "correlation_id": correlation_id.get()}
    if extra:
        err.update(extra)
    return {"error": err}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "issue": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "Request validation failed.", {"details": details}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        log.exception("unhandled error")  # stack trace goes to logs only, never to the client
        return JSONResponse(_body("INTERNAL_ERROR", "An internal error occurred."), status_code=500)
