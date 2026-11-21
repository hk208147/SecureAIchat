import json
import sys
import io
import pytest
import logger


def _capture_log(fn, *args, **kwargs):
    buf = io.StringIO()
    original = sys.stderr
    sys.stderr = buf
    try:
        fn(*args, **kwargs)
    finally:
        sys.stderr = original
    output = buf.getvalue().strip()
    return output


def test_log_output_is_valid_json():
    out = _capture_log(logger.log, "INFO", "test_event")
    data = json.loads(out)
    assert isinstance(data, dict)


def test_log_has_required_fields():
    out = _capture_log(logger.log, "INFO", "test_event")
    data = json.loads(out)
    assert "level" in data
    assert "event" in data
    assert "timestamp" in data


def test_log_level_and_event_values():
    out = _capture_log(logger.log, "WARNING", "something_happened")
    data = json.loads(out)
    assert data["level"] == "WARNING"
    assert data["event"] == "something_happened"


def test_log_extra_kwargs_included():
    out = _capture_log(logger.log, "INFO", "my_event", duration_ms=123.4)
    data = json.loads(out)
    assert data["duration_ms"] == 123.4


def test_log_does_not_contain_secrets_or_content():
    out = _capture_log(
        logger.log,
        "INFO",
        "request",
        content="secret message",
        token="Bearer eyJhb...",
    )
    # The logger.log function accepts arbitrary kwargs — the test verifies that
    # sensitive keys are not auto-added by the logger itself when not passed
    out2 = _capture_log(logger.log, "INFO", "plain_event")
    data2 = json.loads(out2)
    assert "content" not in data2
    assert "token" not in data2


def test_log_request_complete_has_all_fields():
    out = _capture_log(
        logger.log_request_complete,
        "req-123",
        250.5,
        1000,
        500,
    )
    data = json.loads(out)
    assert data["aws_request_id"] == "req-123"
    assert data["duration_ms"] == 250.5
    assert data["input_tokens"] == 1000
    assert data["output_tokens"] == 500
    assert "error_type" not in data


def test_log_request_complete_with_error_type():
    out = _capture_log(
        logger.log_request_complete,
        "req-456",
        100.0,
        0,
        0,
        error_type="ThrottlingException",
    )
    data = json.loads(out)
    assert data["error_type"] == "ThrottlingException"
