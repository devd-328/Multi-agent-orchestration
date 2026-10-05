import io
import json
import logging
from collections.abc import Iterator

import pytest

from orchestration.core.logging import JsonFormatter, RunIdFilter, configure_logging, run_id_var


def _record(message: str = "event") -> logging.LogRecord:
    return logging.LogRecord(
        name="orchestration.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_run_id_filter_adds_the_current_run_id() -> None:
    record = _record()
    token = run_id_var.set("run-123")
    try:
        assert RunIdFilter().filter(record) is True
    finally:
        run_id_var.reset(token)

    assert record.run_id == "run-123"


def test_run_id_filter_adds_nothing_outside_a_run() -> None:
    record = _record()

    assert RunIdFilter().filter(record) is True
    assert not hasattr(record, "run_id")


def test_run_id_filter_keeps_an_explicit_run_id() -> None:
    record = _record()
    record.run_id = "explicit"
    token = run_id_var.set("from-context")
    try:
        RunIdFilter().filter(record)
    finally:
        run_id_var.reset(token)

    assert record.run_id == "explicit"


def test_configure_logging_writes_run_id_to_the_given_stream(
    restore_root_logger: None,
) -> None:
    stream = io.StringIO()
    configure_logging(stream)
    token = run_id_var.set("run-456")
    try:
        logging.getLogger("orchestration.test").info("hello")
    finally:
        run_id_var.reset(token)
    logging.getLogger("orchestration.test").info("outside")

    inside, outside = (json.loads(line) for line in stream.getvalue().splitlines())
    assert inside["extra"]["run_id"] == "run-456"
    assert "extra" not in outside


def test_structured_log_redacts_secret_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="orchestration.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="api_started",
        args=(),
        exc_info=None,
    )
    record.api_key = "super-secret-value"
    record.agent_id = "supervisor"

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "orchestration.test"
    assert payload["message"] == "api_started"
    assert payload["extra"]["api_key"] == "[REDACTED]"
    assert payload["extra"]["agent_id"] == "supervisor"
    assert "super-secret-value" not in json.dumps(payload)
