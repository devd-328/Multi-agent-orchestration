import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TextIO

run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
"""Id of the workflow run in progress. The workflow sets it, the log filter reads it."""

_REDACTED = "[REDACTED]"
_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _REDACTED if _is_secret_key(str(key)) else _redact(item)
            for key, item in value.items()
        }
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per log line. Secret-like extra fields are redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _LOG_RECORD_FIELDS
        }
        if extra:
            payload["extra"] = _redact(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RunIdFilter(logging.Filter):
    """Add the current run id to every record, so one run can be followed in the logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        run_id = run_id_var.get()
        if run_id is not None and not hasattr(record, "run_id"):
            record.run_id = run_id
        return True


def configure_logging(stream: TextIO | None = None) -> None:
    """Send structured logs to stdout, or to `stream`. Does not log environment values."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RunIdFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
