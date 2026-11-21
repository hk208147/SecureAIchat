import json
import os
import re
import time

import boto3
from botocore.config import Config

import bedrock_client
import config
import conversation
import logger
import metrics

_dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
_bedrock = boto3.client(
    "bedrock-runtime",
    region_name=config.BEDROCK_REGION,
    config=Config(
        connect_timeout=5,
        # Socket-read timeout, not an end-to-end deadline. HTTP API can still
        # time out before Lambda completes; callers must not auto-resubmit.
        read_timeout=config.BEDROCK_READ_TIMEOUT,
        # Include the initial call: one total attempt, no automatic retries.
        retries={"mode": "standard", "total_max_attempts": 1},
    ),
)
_table = _dynamodb.Table(config.DYNAMODB_TABLE) if config.DYNAMODB_TABLE else None

_SESSION_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,128}$')


# Ordered patterns used to classify Error.Message without storing the raw text.
# First match wins. Add new labels only after verifying the keyword is unambiguous.
_DENY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("iam_deny",                 ("not authorized",)),
    ("model_not_available",      ("not available",)),
    ("model_access_not_enabled", ("model access",)),
    ("service_quota",            ("quota", "throttl")),
    ("agreement_required",       ("agreement", "subscription")),
)


def _classify_deny_reason(message: object) -> str:
    """Return a classification label from Error.Message; never stores the message."""
    if not isinstance(message, str) or not message:
        return "unknown"
    lower = message.lower()
    for label, keywords in _DENY_PATTERNS:
        if any(kw in lower for kw in keywords):
            return label
    return "unknown"


def _log_bedrock_error(exc: Exception, error_type: str, model_id: str) -> None:
    """Log structured Bedrock error details without sensitive content."""
    fields: dict = {
        "error_type": error_type,
        "model_id": model_id,
        "bedrock_region": config.BEDROCK_REGION,
    }
    err_resp = getattr(exc, "response", None)
    if isinstance(err_resp, dict):
        error_info = err_resp.get("Error", {})
        fields["aws_error_code"] = error_info.get("Code")
        meta = err_resp.get("ResponseMetadata", {})
        fields["bedrock_request_id"] = meta.get("RequestId")
        fields["http_status"] = meta.get("HTTPStatusCode")
        raw_msg = error_info.get("Message") or error_info.get("message")
        fields["deny_reason"] = _classify_deny_reason(raw_msg)
    logger.log("ERROR", "bedrock_error", **fields)


def _validate_model_params(
    raw_model_id: object, raw_thinking_level: object
) -> tuple[str | None, str | None, dict | None]:
    """Returns (model_id, thinking_level, error_response_or_None).

    Both None → legacy path: no thinking, original model.
    model_id specified → validated against allowed list; thinking defaults to medium.
    """
    if raw_model_id is None and raw_thinking_level is None:
        return None, None, None

    if raw_model_id is not None and not isinstance(raw_model_id, str):
        return None, None, _response(400, {"error": "model_id must be a string"})
    if raw_thinking_level is not None and not isinstance(raw_thinking_level, str):
        return None, None, _response(400, {"error": "thinking_level must be a string"})

    model_id: str = raw_model_id if isinstance(raw_model_id, str) else config.DEFAULT_MODEL_ID

    if model_id not in config.ALLOWED_MODEL_CONFIGS:
        return None, None, _response(400, {"error": f"Unsupported model: {model_id}"})

    thinking_level: str = raw_thinking_level if isinstance(raw_thinking_level, str) else "medium"
    allowed = config.ALLOWED_MODEL_CONFIGS[model_id]["thinking_levels"]
    if thinking_level not in allowed:
        return None, None, _response(
            400, {"error": f"Invalid thinking_level '{thinking_level}'. Allowed: {', '.join(allowed)}"}
        )

    return model_id, thinking_level, None


def _cors_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": config.ALLOWED_ORIGIN,
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "POST,GET,DELETE,OPTIONS",
    }


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": _cors_headers(),
        "body": json.dumps(body, ensure_ascii=False),
    }


def _get_sub(event: dict) -> str | None:
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _authorize(event: dict) -> tuple[str | None, dict | None]:
    sub = _get_sub(event)
    if sub is None:
        return None, _response(401, {"error": "Authentication required"})
    allowed = config.ALLOWED_SUB
    if not allowed or sub != allowed:
        return None, _response(403, {"error": "Forbidden"})
    return sub, None


def _handle_chat(event: dict, context, sub: str) -> dict:
    start = time.monotonic()
    input_tokens = 0
    output_tokens = 0
    error_type: str | None = None

    try:
        try:
            raw_body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return _response(400, {"error": "Request body must be valid JSON"})
        if not isinstance(raw_body, dict):
            return _response(400, {"error": "Request body must be a JSON object"})
        body: dict = raw_body

        raw_message = body.get("message", "")
        if not isinstance(raw_message, str):
            return _response(400, {"error": "message must be a string"})
        user_message: str = raw_message.strip()

        raw_session_id = body.get("session_id", "default")
        if not isinstance(raw_session_id, str):
            return _response(400, {"error": "session_id must be a string"})
        session_id: str = raw_session_id
        if not _SESSION_ID_RE.match(session_id):
            return _response(400, {"error": "session_id contains invalid characters"})

        if not user_message:
            return _response(400, {"error": "message is required"})

        if len(user_message.encode('utf-8')) > config.MAX_INPUT_BYTES:
            return _response(413, {"error": "Message too large: exceeds storage limit"})

        raw_model_id = body.get("model_id")
        raw_thinking_level = body.get("thinking_level")
        model_id, thinking_level, validation_error = _validate_model_params(
            raw_model_id, raw_thinking_level
        )
        if validation_error is not None:
            return validation_error

        history: list[dict] = []
        if _table is not None:
            try:
                history = conversation.get_history(_table, sub, session_id)
            except Exception as exc:
                logger.log("WARNING", "history_read_failed", error_type=type(exc).__name__)

        bedrock_start = time.monotonic()
        try:
            result = bedrock_client.invoke_chat(
                _bedrock, history, user_message,
                model_id=model_id,
                thinking_level=thinking_level,
            )
        except Exception as exc:
            error_type = type(exc).__name__
            _log_bedrock_error(exc, error_type, model_id or config.MODEL_ID)
            raise
        bedrock_duration_ms = int((time.monotonic() - bedrock_start) * 1000)

        input_tokens = result["input_tokens"]
        output_tokens = result["output_tokens"]
        model_used: str = result.get("model_used", config.DEFAULT_MODEL_ID)

        if _table is not None:
            try:
                # Create the session record first so the ConditionCheck in
                # save_chat_turn always evaluates against an existing item.
                # Idempotent — also repairs a missing record on later turns.
                conversation.save_session_if_new(_table, sub, session_id, user_message)
                saved = conversation.save_chat_turn(
                    _table, sub, session_id,
                    user_message=user_message,
                    assistant_content=result["content"],
                    in_tok=input_tokens,
                    out_tok=output_tokens,
                    model_used=model_used,
                    thinking_level=thinking_level,
                    response_time_ms=bedrock_duration_ms,
                )
                if not saved:
                    logger.log("WARNING", "chat_not_saved_session_deleted", session_id=session_id)
            except Exception as exc:
                logger.log("WARNING", "history_save_failed", error_type=type(exc).__name__)

        duration_ms = (time.monotonic() - start) * 1000
        logger.log_request_complete(
            getattr(context, "aws_request_id", "local"),
            duration_ms,
            input_tokens,
            output_tokens,
        )
        function_name = getattr(context, "function_name", "local")
        metrics.emit_request_metrics(function_name, input_tokens, output_tokens)

        return _response(200, {
            "response": result["content"],
            "session_id": session_id,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "model_used": model_used,
            "thinking_level": thinking_level,
            "response_time_ms": bedrock_duration_ms,
        })

    except Exception as exc:
        if error_type is None:
            error_type = type(exc).__name__
        duration_ms = (time.monotonic() - start) * 1000
        logger.log_request_complete(
            getattr(context, "aws_request_id", "local"),
            duration_ms,
            input_tokens,
            output_tokens,
            error_type=error_type,
        )
        return _response(502, {"error": "Service temporarily unavailable"})


def _handle_delete_session(event: dict, sub: str) -> dict:
    if _table is None:
        return _response(404, {"error": "Not found"})
    params = event.get("queryStringParameters") or {}
    session_id = params.get("session_id", "")
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return _response(400, {"error": "session_id query parameter is required and must be valid"})
    try:
        conversation.delete_session(_table, sub, session_id)
        return _response(200, {"deleted": True})
    except Exception as exc:
        logger.log("ERROR", "session_delete_failed", error_type=type(exc).__name__)
        return _response(502, {"error": "Service temporarily unavailable"})


def _handle_sessions(event: dict, sub: str) -> dict:
    if _table is None:
        return _response(200, {"sessions": []})
    try:
        sessions = conversation.get_sessions(_table, sub)
        return _response(200, {"sessions": sessions})
    except Exception as exc:
        logger.log("ERROR", "sessions_read_failed", error_type=type(exc).__name__)
        return _response(502, {"error": "Service temporarily unavailable"})


def _handle_messages(event: dict, sub: str) -> dict:
    if _table is None:
        return _response(200, {"messages": []})
    params = event.get("queryStringParameters") or {}
    session_id = params.get("session_id", "")
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return _response(400, {"error": "session_id query parameter is required and must be valid"})
    try:
        messages = conversation.get_display_messages(_table, sub, session_id)
        return _response(200, {"messages": messages})
    except Exception as exc:
        logger.log("ERROR", "messages_read_failed", error_type=type(exc).__name__)
        return _response(502, {"error": "Service temporarily unavailable"})


def lambda_handler(event: dict, context) -> dict:
    method: str = event.get("requestContext", {}).get("http", {}).get("method", "").upper()
    path: str = event.get("rawPath", event.get("path", ""))

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": _cors_headers(), "body": ""}

    sub, auth_error = _authorize(event)
    if auth_error is not None:
        return auth_error

    if method == "POST" and path.endswith("/chat"):
        return _handle_chat(event, context, sub)

    if method == "GET" and path.endswith("/sessions"):
        return _handle_sessions(event, sub)

    if method == "GET" and path.endswith("/messages"):
        return _handle_messages(event, sub)

    if method == "DELETE" and path.endswith("/sessions"):
        return _handle_delete_session(event, sub)

    return _response(404, {"error": "Not found"})
