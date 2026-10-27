import contextvars
import json
import logging
import re
import sys
import time

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s-]{8,}\d")
_SECRET = re.compile(r"(?i)(bearer\s+[\w.-]+|api[_-]?key\s*[=:]\s*\S+|secret\s*[=:]\s*\S+)")


def redact(text: str) -> str:
    """Remove emails, phone numbers and token-like strings before text reaches logs or stored events."""
    return _SECRET.sub("[secret]", _PHONE.sub("[phone]", _EMAIL.sub("[email]", text)))


def redact_json(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_json(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "correlation_id": correlation_id.get(),
        }
        for k in ("event", "run_id", "step", "status", "path", "method", "duration_ms"):
            if hasattr(record, k):
                data[k] = getattr(record, k)
        return json.dumps(data)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
