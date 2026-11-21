import json
import sys
from datetime import datetime, timezone


def log(level: str, event: str, **kwargs) -> None:
    record: dict = {
        "level": level,
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    record.update(kwargs)
    sys.stderr.write(json.dumps(record, default=str) + "\n")
    sys.stderr.flush()


def log_request_complete(
    aws_request_id: str,
    duration_ms: float,
    input_tokens: int,
    output_tokens: int,
    error_type: str | None = None,
) -> None:
    fields: dict = {
        "aws_request_id": aws_request_id,
        "duration_ms": round(duration_ms, 1),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if error_type is not None:
        fields["error_type"] = error_type
    log("INFO", "request_complete", **fields)
