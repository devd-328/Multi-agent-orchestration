import json
import logging

from orchestration.core.logging import JsonFormatter


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
