import json
import pytest
from unittest.mock import MagicMock, patch


def _make_event(method="POST", path="/chat", body=None, sub="test-sub-123"):
    event = {
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": f"/{path.lstrip('/')}",
        "body": json.dumps(body) if body is not None else None,
    }
    return event


def _make_context():
    ctx = MagicMock()
    ctx.aws_request_id = "req-test-123"
    ctx.function_name = "test-function"
    return ctx


def _mock_bedrock_result():
    return {
        "content": "AI response",
        "input_tokens": 100,
        "output_tokens": 50,
        "stop_reason": "end_turn",
        "model_used": "au.anthropic.claude-sonnet-4-6",
    }


def _patched_handler():
    """Return chat_handler with module-level AWS clients mocked."""
    import chat_handler
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_bedrock = MagicMock()
    return chat_handler, mock_table, mock_bedrock


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_missing_auth_returns_401(mock_invoke, mock_table):
    import chat_handler
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "rawPath": "/chat",
        "body": json.dumps({"message": "hello", "session_id": "s1"}),
    }
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 401


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_wrong_sub_returns_403(mock_invoke, mock_table):
    import chat_handler
    event = _make_event(body={"message": "hello", "session_id": "s1"}, sub="wrong-sub")
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 403


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_correct_sub_passes_auth(mock_invoke, mock_table):
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = _mock_bedrock_result()
    event = _make_event(body={"message": "hello", "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_unsupported_model_id_returns_400(mock_invoke, mock_table):
    import chat_handler
    event = _make_event(body={"message": "hello", "session_id": "s1", "model_id": "anthropic.claude-3-haiku"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400
    mock_invoke.assert_not_called()


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_invalid_thinking_level_returns_400(mock_invoke, mock_table):
    import chat_handler
    event = _make_event(body={
        "message": "hello", "session_id": "s1",
        "model_id": "au.anthropic.claude-sonnet-4-6", "thinking_level": "ultra",
    })
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400
    mock_invoke.assert_not_called()


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_model_switch_to_sonnet55_accepted(mock_invoke, mock_table):
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = {**_mock_bedrock_result(), "model_used": "au.anthropic.claude-opus-4-6-v1"}
    event = _make_event(body={
        "message": "hello", "session_id": "s1",
        "model_id": "au.anthropic.claude-opus-4-6-v1", "thinking_level": "low",
    })
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    _, kwargs = mock_invoke.call_args
    assert kwargs["model_id"] == "au.anthropic.claude-opus-4-6-v1"
    assert kwargs["thinking_level"] == "low"


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_legacy_no_model_no_thinking_passes_none(mock_invoke, mock_table):
    """Existing clients that omit model_id/thinking_level use the legacy path."""
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = _mock_bedrock_result()
    event = _make_event(body={"message": "hello", "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    _, kwargs = mock_invoke.call_args
    assert kwargs.get("model_id") is None
    assert kwargs.get("thinking_level") is None


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_response_includes_model_metadata(mock_invoke, mock_table):
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = {**_mock_bedrock_result(), "model_used": "au.anthropic.claude-sonnet-4-6"}
    event = _make_event(body={
        "message": "hello", "session_id": "s1",
        "model_id": "au.anthropic.claude-sonnet-4-6", "thinking_level": "medium",
    })
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["model_used"] == "au.anthropic.claude-sonnet-4-6"
    assert body["thinking_level"] == "medium"
    assert "response_time_ms" in body


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_model_cannot_be_overridden_by_client(mock_invoke, mock_table):
    """Random model IDs not in the allowlist are rejected."""
    import chat_handler
    event = _make_event(body={
        "message": "hello",
        "session_id": "s1",
        "model_id": "gpt-4",
    })
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400
    mock_invoke.assert_not_called()


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_thinking_level_without_model_defaults_sonnet(mock_invoke, mock_table):
    """thinking_level alone (no model_id) selects the default model."""
    import chat_handler
    import config
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = {**_mock_bedrock_result(), "model_used": config.DEFAULT_MODEL_ID}
    event = _make_event(body={"message": "hello", "session_id": "s1", "thinking_level": "high"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    _, kwargs = mock_invoke.call_args
    assert kwargs["model_id"] == config.DEFAULT_MODEL_ID
    assert kwargs["thinking_level"] == "high"


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_missing_message_field_returns_400(mock_invoke, mock_table):
    import chat_handler
    event = _make_event(body={"session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_empty_message_returns_400(mock_invoke, mock_table):
    import chat_handler
    event = _make_event(body={"message": "   ", "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_long_message_above_3000_sent_in_full(mock_invoke, mock_table):
    """Messages longer than 3000 characters are sent to Bedrock without truncation."""
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = _mock_bedrock_result()
    # 4000 Japanese characters (~12,000 UTF-8 bytes) — well above the old limit
    long_msg = "あ" * 4000
    event = _make_event(body={"message": long_msg, "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    call_args = mock_invoke.call_args[0]
    passed_message = call_args[2]
    assert len(passed_message) == 4000


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_message_exceeding_byte_limit_rejected_before_bedrock(mock_invoke, mock_table):
    """Message exceeding DynamoDB item size limit returns 413 without calling Bedrock."""
    import chat_handler
    import config
    large_msg = "a" * (config.MAX_INPUT_BYTES + 1)
    event = _make_event(body={"message": large_msg, "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 413
    mock_invoke.assert_not_called()


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_options_returns_200(mock_invoke, mock_table):
    import chat_handler
    event = {
        "requestContext": {"http": {"method": "OPTIONS"}},
        "rawPath": "/chat",
        "body": None,
    }
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_response_contains_no_stop_mechanism(mock_invoke, mock_table):
    """Verify no cost-stop or daily-limit logic blocks the response."""
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = _mock_bedrock_result()
    event = _make_event(body={"message": "hello", "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert "error" not in body
    assert "daily_limit" not in body
    assert "stopped" not in body


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_get_sessions_route(mock_invoke, mock_table):
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    event = _make_event(method="GET", path="/sessions")
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert "sessions" in body


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_history_save_failure_does_not_affect_response(mock_invoke, mock_table):
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_invoke.return_value = _mock_bedrock_result()
    with patch("chat_handler.conversation.save_chat_turn", side_effect=Exception("DynamoDB error")):
        event = _make_event(body={"message": "hello", "session_id": "s1"})
        result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200


# --- R10: input type validation ---

@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_non_dict_body_returns_400(mock_invoke, mock_table):
    """Body that is a JSON array (not object) must return 400."""
    import chat_handler
    event = _make_event()
    event["body"] = json.dumps(["hello"])
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_message_as_number_returns_400(mock_invoke, mock_table):
    """message field that is a number (not string) must return 400."""
    import chat_handler
    event = _make_event(body={"message": 42, "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_message_as_null_returns_400(mock_invoke, mock_table):
    """message field that is null (not string) must return 400."""
    import chat_handler
    event = _make_event(body={"message": None, "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_invalid_session_id_chars_returns_400(mock_invoke, mock_table):
    """session_id with path-traversal chars must return 400."""
    import chat_handler
    event = _make_event(body={"message": "hello", "session_id": "../etc/passwd"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_session_id_too_long_returns_400(mock_invoke, mock_table):
    """session_id longer than 128 chars must return 400."""
    import chat_handler
    event = _make_event(body={"message": "hello", "session_id": "a" * 129})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_valid_session_id_accepted(mock_invoke, mock_table):
    """session_id with alphanumeric and dash/underscore chars must be accepted."""
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = _mock_bedrock_result()
    event = _make_event(body={"message": "hello", "session_id": "My-Session_01"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200


# --- R08: Bedrock SDK timeout → 502 ---

@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_bedrock_read_timeout_returns_502(mock_invoke, mock_table):
    """ReadTimeoutError from Bedrock SDK must return 502, not crash Lambda."""
    import chat_handler
    from botocore.exceptions import ReadTimeoutError
    mock_table.query.return_value = {"Items": []}
    mock_invoke.side_effect = ReadTimeoutError(endpoint_url="https://bedrock.ap-southeast-2.amazonaws.com")
    event = _make_event(body={"message": "hello", "session_id": "s1"})
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 502


# --- R03: GET /messages route ---

@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_get_messages_route_returns_200(mock_invoke, mock_table):
    import chat_handler
    mock_table.query.return_value = {"Items": []}
    event = _make_event(method="GET", path="/messages")
    event["queryStringParameters"] = {"session_id": "s1"}
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert "messages" in body


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_get_messages_missing_session_id_returns_400(mock_invoke, mock_table):
    import chat_handler
    event = _make_event(method="GET", path="/messages")
    event["queryStringParameters"] = {}
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


# --- N05: invalid JSON body must return 400 (not 502) ---

@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_invalid_json_body_returns_400(mock_invoke, mock_table):
    """Malformed JSON body must return 400 without calling Bedrock."""
    import chat_handler
    event = _make_event()
    event["body"] = "{"  # intentionally broken JSON
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400
    mock_invoke.assert_not_called()


# --- N04: save_session_if_new called even when history exists ---

@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_save_session_called_when_history_exists(mock_invoke, mock_table):
    """Session record creation is attempted regardless of whether history is empty."""
    import chat_handler
    import conversation
    # Simulate non-empty history (second message in existing session)
    existing_msg = {
        "pk": "USER#test-sub-123#SESSION#s1",
        "sk": "MSG#2026-01-01T00:00:00+00:00#aabbccdd",
        "role": "user",
        "content": "first message",
        "ttl": 9999999999,
    }
    mock_table.query.return_value = {"Items": [existing_msg]}
    mock_table.put_item.return_value = {}
    mock_invoke.return_value = _mock_bedrock_result()
    event = _make_event(body={"message": "second message", "session_id": "s1"})
    with patch.object(conversation, "save_session_if_new") as mock_save_session:
        chat_handler.lambda_handler(event, _make_context())
        mock_save_session.assert_called_once()


# --- GET /messages Decimal → 200 regression ---

@patch("chat_handler._table", new_callable=MagicMock)
def test_get_messages_decimal_values_return_200(mock_table):
    """GET /messages must return 200 when DynamoDB items contain Decimal (not TypeError→502)."""
    from decimal import Decimal
    import chat_handler
    import time as _time
    future_ttl = Decimal(str(int(_time.time()) + 86400))
    mock_table.query.return_value = {
        "Items": [
            {
                "pk": "USER#test-sub-123#SESSION#sess1",
                "sk": "MSG#2026-01-01T00:00:00+00:00#abc12345",
                "role": "user",
                "content": "hello",
                "in_tok": Decimal("100"),
                "out_tok": Decimal("0"),
                "ttl": future_ttl,
            },
            {
                "pk": "USER#test-sub-123#SESSION#sess1",
                "sk": "MSG#2026-01-01T00:00:00.000001+00:00#def67890",
                "role": "assistant",
                "content": "world",
                "in_tok": Decimal("0"),
                "out_tok": Decimal("50"),
                "response_time_ms": Decimal("1234"),
                "model_used": "au.anthropic.claude-sonnet-4-6",
                "ttl": future_ttl,
            },
        ]
    }
    event = _make_event(method="GET", path="/messages")
    event["queryStringParameters"] = {"session_id": "sess1"}
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    msgs = body["messages"]
    assert len(msgs) == 2
    asst = next(m for m in msgs if m["role"] == "assistant")
    assert asst["out_tok"] == 50
    assert asst["response_time_ms"] == 1234


@patch("chat_handler._table", new_callable=MagicMock)
def test_get_messages_research_conversation_return_200(mock_table):
    """GET /messages with research_context and citations must serialize to 200."""
    from decimal import Decimal
    import chat_handler
    import time as _time
    future_ttl = Decimal(str(int(_time.time()) + 86400))
    citation = {
        "id": "src-1",
        "kind": "knowledge",
        "title": "Doc",
        "excerpt": "text",
        "personaId": "default",
        "documentId": "doc-abc",
    }
    research_ctx = {"persona_id": "default", "mode": "general", "chat_type": "RAG"}
    mock_table.query.return_value = {
        "Items": [
            {
                "pk": "USER#test-sub-123#SESSION#sess-rag",
                "sk": "MSG#2026-01-01T00:00:00+00:00#aaa",
                "role": "user",
                "content": "query",
                "in_tok": Decimal("0"),
                "out_tok": Decimal("0"),
                "research_context": research_ctx,
                "ttl": future_ttl,
            },
            {
                "pk": "USER#test-sub-123#SESSION#sess-rag",
                "sk": "MSG#2026-01-01T00:00:00.000001+00:00#bbb",
                "role": "assistant",
                "content": "answer",
                "in_tok": Decimal("0"),
                "out_tok": Decimal("80"),
                "response_time_ms": Decimal("2500"),
                "model_used": "au.anthropic.claude-sonnet-4-6",
                "research_context": research_ctx,
                "citations": [citation],
                "ttl": future_ttl,
            },
        ]
    }
    event = _make_event(method="GET", path="/messages")
    event["queryStringParameters"] = {"session_id": "sess-rag"}
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    msgs = body["messages"]
    asst = next(m for m in msgs if m["role"] == "assistant")
    assert asst["out_tok"] == 80
    assert asst["research_context"]["chat_type"] == "RAG"
    assert asst["citations"][0]["id"] == "src-1"


def test_bedrock_503_is_not_automatically_retried(monkeypatch):
    """Exercise botocore retry handling without contacting AWS."""
    import io
    import chat_handler
    from botocore.awsrequest import AWSResponse
    from botocore.exceptions import ClientError

    class ErrorBody(io.BytesIO):
        def stream(self, amt=None, decode_content=False):
            yield self.getvalue()

    calls = []

    def fail_request(request):
        calls.append(request)
        return AWSResponse(
            request.url,
            503,
            {"content-type": "application/json", "x-amzn-errortype": "ServiceUnavailableException"},
            ErrorBody(b'{"message":"temporary failure"}'),
        )

    monkeypatch.setattr(chat_handler._bedrock._endpoint.http_session, "send", fail_request)
    with pytest.raises(ClientError):
        chat_handler._bedrock.converse(
            modelId="au.anthropic.claude-sonnet-4-6",
            messages=[{"role": "user", "content": [{"text": "test"}]}],
        )
    assert len(calls) == 1


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
def test_missing_session_record_is_retried_with_existing_history(mock_invoke, mock_table):
    """A failed metadata write on turn one must be repaired on a later turn."""
    import chat_handler
    mock_invoke.return_value = _mock_bedrock_result()
    with patch("chat_handler.conversation.get_history", return_value=[
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]), patch("chat_handler.conversation.save_chat_turn", return_value=True), patch(
        "chat_handler.conversation.save_session_if_new", side_effect=[RuntimeError("temporary"), None]
    ) as save_session:
        event = _make_event(body={"message": "hello", "session_id": "s1"})
        # First call: save_session_if_new raises, exception caught, 200 still returned
        assert chat_handler.lambda_handler(event, _make_context())["statusCode"] == 200
        # Second call: save_session_if_new succeeds (repair), save_chat_turn also runs
        assert chat_handler.lambda_handler(event, _make_context())["statusCode"] == 200
        assert save_session.call_count == 2


# --- bedrock_error log structure tests ---

@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
@patch("chat_handler.logger.log")
def test_bedrock_error_log_has_no_raw_message(mock_log, mock_invoke, mock_table):
    """bedrock_error log must contain deny_reason classification but not the raw Error.Message."""
    import chat_handler
    from botocore.exceptions import ClientError
    raw_message = "User is not authorized to perform: bedrock:InvokeModel on resource"
    err_response = {
        "Error": {"Code": "AccessDeniedException", "Message": raw_message},
        "ResponseMetadata": {"RequestId": "req-abc-123", "HTTPStatusCode": 403},
    }
    mock_invoke.side_effect = ClientError(err_response, "Converse")
    mock_table.query.return_value = {"Items": []}
    event = _make_event(body={
        "message": "hello", "session_id": "s1",
        "model_id": "au.anthropic.claude-sonnet-4-6", "thinking_level": "medium",
    })
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 502
    error_calls = [c for c in mock_log.call_args_list if len(c.args) >= 2 and c.args[1] == "bedrock_error"]
    assert len(error_calls) == 1
    kw = error_calls[0].kwargs
    assert kw.get("deny_reason") == "iam_deny"
    assert kw.get("aws_error_code") == "AccessDeniedException"
    assert raw_message not in str(kw)


@patch("chat_handler._table", new_callable=MagicMock)
@patch("chat_handler.bedrock_client.invoke_chat")
@patch("chat_handler.logger.log")
def test_bedrock_error_log_unknown_when_no_message(mock_log, mock_invoke, mock_table):
    """deny_reason is 'unknown' when Error.Message is absent."""
    import chat_handler
    from botocore.exceptions import ClientError
    err_response = {
        "Error": {"Code": "AccessDeniedException"},
        "ResponseMetadata": {"RequestId": "req-xyz-456", "HTTPStatusCode": 403},
    }
    mock_invoke.side_effect = ClientError(err_response, "Converse")
    mock_table.query.return_value = {"Items": []}
    event = _make_event(body={
        "message": "hello", "session_id": "s1",
        "model_id": "au.anthropic.claude-sonnet-4-6", "thinking_level": "medium",
    })
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 502
    error_calls = [c for c in mock_log.call_args_list if len(c.args) >= 2 and c.args[1] == "bedrock_error"]
    assert len(error_calls) == 1
    kw = error_calls[0].kwargs
    assert kw.get("deny_reason") == "unknown"


# --- DELETE /sessions tests ---

@patch("chat_handler._table", new_callable=MagicMock)
def test_delete_session_returns_200(mock_table):
    import chat_handler
    with patch("chat_handler.conversation.delete_session") as mock_delete:
        event = _make_event(method="DELETE", path="/sessions")
        event["queryStringParameters"] = {"session_id": "sess-to-delete"}
        result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body.get("deleted") is True
    mock_delete.assert_called_once_with(mock_table, "test-sub-123", "sess-to-delete")


@patch("chat_handler._table", new_callable=MagicMock)
def test_delete_session_missing_session_id_returns_400(mock_table):
    import chat_handler
    event = _make_event(method="DELETE", path="/sessions")
    event["queryStringParameters"] = {}
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
def test_delete_session_invalid_session_id_returns_400(mock_table):
    import chat_handler
    event = _make_event(method="DELETE", path="/sessions")
    event["queryStringParameters"] = {"session_id": "../evil"}
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 400


@patch("chat_handler._table", new_callable=MagicMock)
def test_delete_session_dynamo_error_returns_502(mock_table):
    import chat_handler
    with patch("chat_handler.conversation.delete_session", side_effect=Exception("DynamoDB error")):
        event = _make_event(method="DELETE", path="/sessions")
        event["queryStringParameters"] = {"session_id": "sess1"}
        result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 502


@patch("chat_handler._table", new_callable=MagicMock)
def test_delete_session_requires_auth(mock_table):
    import chat_handler
    event = {
        "requestContext": {"http": {"method": "DELETE"}},
        "rawPath": "/sessions",
        "queryStringParameters": {"session_id": "sess1"},
        "body": None,
    }
    result = chat_handler.lambda_handler(event, _make_context())
    assert result["statusCode"] == 401


@patch("chat_handler._table", new_callable=MagicMock)
def test_delete_session_cors_includes_delete(mock_table):
    """CORS Allow-Methods header must include DELETE."""
    import chat_handler
    with patch("chat_handler.conversation.delete_session"):
        event = _make_event(method="DELETE", path="/sessions")
        event["queryStringParameters"] = {"session_id": "sess1"}
        result = chat_handler.lambda_handler(event, _make_context())
    assert "DELETE" in result["headers"]["Access-Control-Allow-Methods"]
