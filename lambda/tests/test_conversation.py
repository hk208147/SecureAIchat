import time
import pytest
import boto3
from boto3.dynamodb.conditions import Key
from moto import mock_aws

import conversation
import config


@pytest.fixture
def ddb_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        client.create_table(
            TableName="test-table",
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        resource = boto3.resource("dynamodb", region_name="ap-southeast-2")
        yield resource.Table("test-table")


def test_history_empty_on_new_session(ddb_table):
    result = conversation.get_history(ddb_table, "sub1", "sess1")
    assert result == []


def test_history_chronological_order(ddb_table):
    conversation.save_message(ddb_table, "sub1", "sess1", "user", "first")
    time.sleep(0.01)
    conversation.save_message(ddb_table, "sub1", "sess1", "assistant", "second")
    time.sleep(0.01)
    conversation.save_message(ddb_table, "sub1", "sess1", "user", "third")

    history = conversation.get_history(ddb_table, "sub1", "sess1")
    assert len(history) == 3
    assert history[0]["content"] == "first"
    assert history[1]["content"] == "second"
    assert history[2]["content"] == "third"
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_history_limit_returns_newest(ddb_table):
    for i in range(15):
        conversation.save_message(ddb_table, "sub1", "sess2", "user", f"msg{i}")
        time.sleep(0.01)  # ensure distinct ISO timestamps on Windows

    history = conversation.get_history(ddb_table, "sub1", "sess2", limit=10)
    assert len(history) == 10
    assert history[-1]["content"] == "msg14"


def test_pk_isolation_between_users(ddb_table):
    conversation.save_message(ddb_table, "sub1", "sess1", "user", "user1 message")
    history_sub2 = conversation.get_history(ddb_table, "sub2", "sess1")
    assert history_sub2 == []


def test_pk_isolation_between_sessions(ddb_table):
    conversation.save_message(ddb_table, "sub1", "sessA", "user", "session A")
    history_b = conversation.get_history(ddb_table, "sub1", "sessB")
    assert history_b == []


def test_sk_uniqueness_same_millisecond(ddb_table):
    # Save two messages without sleep; uuid suffix prevents collision
    conversation.save_message(ddb_table, "sub1", "sess3", "user", "msg_a")
    conversation.save_message(ddb_table, "sub1", "sess3", "assistant", "msg_b")

    history = conversation.get_history(ddb_table, "sub1", "sess3", limit=10)
    assert len(history) == 2


def test_ttl_is_set(ddb_table):
    conversation.save_message(ddb_table, "sub1", "sess4", "user", "hello")
    now = int(time.time())
    pk = f"USER#sub1#SESSION#sess4"
    resp = ddb_table.query(
        KeyConditionExpression=Key("pk").eq(pk)
        & Key("sk").begins_with("MSG#"),
    )
    item = resp["Items"][0]
    assert "ttl" in item
    expected_min = now + (config.TTL_DAYS - 1) * 86400
    assert int(item["ttl"]) > expected_min


def test_save_session_if_new_idempotent(ddb_table):
    conversation.save_session_if_new(ddb_table, "sub1", "sess5", "hello world")
    pk = "USER#sub1"
    resp = ddb_table.query(
        KeyConditionExpression=Key("pk").eq(pk)
        & Key("sk").begins_with("SESSION#sess5"),
    )
    assert len(resp["Items"]) >= 1
    assert resp["Items"][0]["firstMessage"] == "hello world"


def test_first_message_truncated_to_100_chars(ddb_table):
    long_msg = "x" * 200
    conversation.save_session_if_new(ddb_table, "sub1", "sess6", long_msg)
    pk = "USER#sub1"
    resp = ddb_table.query(
        KeyConditionExpression=Key("pk").eq(pk)
        & Key("sk").begins_with("SESSION#sess6"),
    )
    assert len(resp["Items"][0]["firstMessage"]) == 100


def test_get_sessions_returns_records(ddb_table):
    conversation.save_session_if_new(ddb_table, "sub1", "sessX", "first message")
    sessions = conversation.get_sessions(ddb_table, "sub1")
    assert any(s["session_id"] == "sessX" for s in sessions)


# --- R09: session idempotency regression ---

def test_save_session_if_new_truly_idempotent(ddb_table):
    """Calling twice with same session_id creates exactly 1 record."""
    conversation.save_session_if_new(ddb_table, "sub1", "sess-idem", "first call")
    conversation.save_session_if_new(ddb_table, "sub1", "sess-idem", "second call")
    pk = "USER#sub1"
    resp = ddb_table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").eq("SESSION#sess-idem"),
    )
    assert len(resp["Items"]) == 1
    assert resp["Items"][0]["firstMessage"] == "first call"


def test_session_sk_is_stable(ddb_table):
    """Session SK must not contain a timestamp (ensures ConditionExpression fires)."""
    conversation.save_session_if_new(ddb_table, "sub2", "sess-stable", "hello")
    pk = "USER#sub2"
    resp = ddb_table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("SESSION#"),
    )
    assert len(resp["Items"]) == 1
    assert resp["Items"][0]["sk"] == "SESSION#sess-stable"


# --- R06: expired-item TTL filtering ---

def test_history_excludes_expired_messages(ddb_table):
    now_ts = int(time.time())
    # Insert expired message
    ddb_table.put_item(Item={
        "pk": "USER#sub-ttl#SESSION#sess-ttl",
        "sk": "MSG#2020-01-01T00:00:00+00:00#aabbccdd",
        "role": "user",
        "content": "expired message",
        "ttl": now_ts - 1,
    })
    # Insert valid message
    ddb_table.put_item(Item={
        "pk": "USER#sub-ttl#SESSION#sess-ttl",
        "sk": "MSG#2020-01-02T00:00:00+00:00#aabbccde",
        "role": "assistant",
        "content": "valid message",
        "ttl": now_ts + 86400,
    })
    history = conversation.get_history(ddb_table, "sub-ttl", "sess-ttl", limit=10)
    assert len(history) == 1
    assert history[0]["content"] == "valid message"


def test_sessions_excludes_expired(ddb_table):
    now_ts = int(time.time())
    # Insert expired session
    ddb_table.put_item(Item={
        "pk": "USER#sub-sess-ttl",
        "sk": "SESSION#old-session",
        "session_id": "old-session",
        "firstMessage": "old",
        "created_at": "2020-01-01T00:00:00+00:00",
        "ttl": now_ts - 1,
    })
    # Insert valid session
    ddb_table.put_item(Item={
        "pk": "USER#sub-sess-ttl",
        "sk": "SESSION#new-session",
        "session_id": "new-session",
        "firstMessage": "new",
        "created_at": "2020-01-02T00:00:00+00:00",
        "ttl": now_ts + 86400,
    })
    sessions = conversation.get_sessions(ddb_table, "sub-sess-ttl")
    ids = [s["session_id"] for s in sessions]
    assert "new-session" in ids
    assert "old-session" not in ids


def test_display_messages_excludes_expired(ddb_table):
    now_ts = int(time.time())
    ddb_table.put_item(Item={
        "pk": "USER#sub-dm#SESSION#sess-dm",
        "sk": "MSG#2020-01-01T00:00:00+00:00#aabbccdd",
        "role": "user",
        "content": "expired",
        "ttl": now_ts - 1,
    })
    ddb_table.put_item(Item={
        "pk": "USER#sub-dm#SESSION#sess-dm",
        "sk": "MSG#2020-01-02T00:00:00+00:00#aabbccde",
        "role": "assistant",
        "content": "valid",
        "ttl": now_ts + 86400,
    })
    msgs = conversation.get_display_messages(ddb_table, "sub-dm", "sess-dm")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "valid"
    assert "timestamp" in msgs[0]


def test_display_messages_includes_timestamp(ddb_table):
    conversation.save_message(ddb_table, "sub1", "sess-ts", "user", "hello")
    msgs = conversation.get_display_messages(ddb_table, "sub1", "sess-ts")
    assert len(msgs) == 1
    assert msgs[0]["timestamp"] != ""
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"


# --- N06: get_sessions returns newest sessions even when total exceeds limit ---

def test_get_sessions_newest_returned_when_over_limit(ddb_table):
    """With 25 sessions (> default limit of 20), the newest one must appear in results."""
    now_ts = int(time.time())
    # Create 25 sessions; session IDs sorted lexicographically would put s24 last
    # but it has the most recent created_at, so it must be in the top 20 by recency.
    for i in range(25):
        created = f"2026-01-{i + 1:02d}T00:00:00+00:00"
        ddb_table.put_item(Item={
            "pk": "USER#sub-n06",
            "sk": f"SESSION#s{i:02d}",
            "session_id": f"s{i:02d}",
            "firstMessage": f"message {i}",
            "created_at": created,
            "ttl": now_ts + 86400,
        })
    sessions = conversation.get_sessions(ddb_table, "sub-n06", limit=20)
    ids = [s["session_id"] for s in sessions]
    assert "s24" in ids, f"newest session s24 not in results: {ids}"
    assert "s00" not in ids, f"oldest session s00 should not be in top 20: {ids}"
    assert len(sessions) == 20


# --- delete_session tests ---

def test_delete_session_removes_session_record(ddb_table):
    conversation.save_session_if_new(ddb_table, "sub1", "sess-del", "to be deleted")
    conversation.delete_session(ddb_table, "sub1", "sess-del")
    sessions = conversation.get_sessions(ddb_table, "sub1")
    assert not any(s["session_id"] == "sess-del" for s in sessions)


def test_delete_session_removes_messages(ddb_table):
    conversation.save_message(ddb_table, "sub1", "sess-del2", "user", "msg1")
    time.sleep(0.01)
    conversation.save_message(ddb_table, "sub1", "sess-del2", "assistant", "msg2")
    conversation.delete_session(ddb_table, "sub1", "sess-del2")
    history = conversation.get_history(ddb_table, "sub1", "sess-del2")
    assert history == []


def test_delete_session_leaves_other_sessions_intact(ddb_table):
    conversation.save_session_if_new(ddb_table, "sub1", "keep-me", "keep")
    conversation.save_message(ddb_table, "sub1", "keep-me", "user", "hi")
    conversation.save_session_if_new(ddb_table, "sub1", "del-me", "delete")
    conversation.save_message(ddb_table, "sub1", "del-me", "user", "bye")
    conversation.delete_session(ddb_table, "sub1", "del-me")
    sessions = conversation.get_sessions(ddb_table, "sub1")
    ids = [s["session_id"] for s in sessions]
    assert "keep-me" in ids
    assert "del-me" not in ids
    history = conversation.get_history(ddb_table, "sub1", "keep-me")
    assert len(history) == 1


def test_delete_session_idempotent(ddb_table):
    """Deleting a session that doesn't exist should not raise."""
    conversation.delete_session(ddb_table, "sub1", "nonexistent-sess")


def test_delete_session_isolated_between_users(ddb_table):
    conversation.save_session_if_new(ddb_table, "sub1", "shared-id", "sub1 session")
    conversation.save_session_if_new(ddb_table, "sub2", "shared-id", "sub2 session")
    conversation.delete_session(ddb_table, "sub1", "shared-id")
    sessions_sub2 = conversation.get_sessions(ddb_table, "sub2")
    assert any(s["session_id"] == "shared-id" for s in sessions_sub2)


def test_delete_session_deletes_many_messages(ddb_table):
    """50 messages (>1 BatchWriteItem batch of 25) must all be deleted."""
    for i in range(50):
        conversation.save_message(ddb_table, "sub1", "sess-many", "user", f"msg{i}")
    conversation.save_session_if_new(ddb_table, "sub1", "sess-many", "first")
    conversation.delete_session(ddb_table, "sub1", "sess-many")
    assert conversation.get_history(ddb_table, "sub1", "sess-many", limit=100) == []
    assert not any(s["session_id"] == "sess-many" for s in conversation.get_sessions(ddb_table, "sub1"))


def test_delete_session_follows_last_evaluated_key(ddb_table):
    """When Query returns LastEvaluatedKey, delete_session must follow it and delete all pages."""
    from unittest.mock import patch, MagicMock

    call_num = [0]

    def mock_query(**kwargs):
        call_num[0] += 1
        if call_num[0] == 1:
            return {
                "Items": [{"pk": "USER#s1#SESSION#sess-page", "sk": "MSG#t1#aa"}],
                "LastEvaluatedKey": {"pk": "USER#s1#SESSION#sess-page", "sk": "MSG#t1#aa"},
            }
        return {"Items": [{"pk": "USER#s1#SESSION#sess-page", "sk": "MSG#t2#bb"}]}

    mock_batch = MagicMock()
    mock_bw_ctx = MagicMock()
    mock_bw_ctx.__enter__ = MagicMock(return_value=mock_batch)
    mock_bw_ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(ddb_table, "query", side_effect=mock_query), \
         patch.object(ddb_table, "batch_writer", return_value=mock_bw_ctx):
        conversation.delete_session(ddb_table, "s1", "sess-page")

    assert call_num[0] == 2
    assert mock_batch.delete_item.call_count == 2


def test_delete_session_partial_failure_allows_retry(ddb_table):
    """Tombstone is written first; if batch_writer then fails, messages still exist for retry."""
    conversation.save_message(ddb_table, "sub1", "sess-fail", "user", "msg1")
    conversation.save_session_if_new(ddb_table, "sub1", "sess-fail", "first")

    # First attempt: tombstone is written, then batch_writer raises
    from unittest.mock import patch
    with pytest.raises(Exception):
        with patch.object(ddb_table, "batch_writer", side_effect=Exception("DynamoDB error")):
            conversation.delete_session(ddb_table, "sub1", "sess-fail")

    # Tombstone prevents the session from appearing in get_sessions (correct behavior)
    assert not any(s["session_id"] == "sess-fail" for s in conversation.get_sessions(ddb_table, "sub1"))
    # Messages still exist in DynamoDB — retry can clean them up
    assert len(conversation.get_history(ddb_table, "sub1", "sess-fail", limit=100)) == 1

    # Second attempt (retry): succeeds — messages must be gone
    conversation.delete_session(ddb_table, "sub1", "sess-fail")
    assert conversation.get_history(ddb_table, "sub1", "sess-fail") == []


# --- Race condition / tombstone tests ---

def test_save_chat_turn_saves_messages(ddb_table):
    """save_chat_turn writes both user and assistant messages for a new session."""
    # Production flow: save_session_if_new is called first so the ConditionCheck
    # in save_chat_turn evaluates against an existing (non-tombstoned) item.
    conversation.save_session_if_new(ddb_table, "sub1", "sess-tx-new", "hello")
    result = conversation.save_chat_turn(
        ddb_table, "sub1", "sess-tx-new",
        user_message="hello",
        assistant_content="hi",
        in_tok=100,
        out_tok=50,
        model_used="au.anthropic.claude-sonnet-4-6",
        thinking_level="medium",
        response_time_ms=1500,
    )
    assert result is True
    history = conversation.get_history(ddb_table, "sub1", "sess-tx-new", limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "hi"


def test_save_chat_turn_blocked_by_tombstone_existing_session(ddb_table):
    """After delete_session, save_chat_turn must return False and write no messages."""
    conversation.save_message(ddb_table, "sub1", "sess-tx-del", "user", "original msg")
    conversation.save_session_if_new(ddb_table, "sub1", "sess-tx-del", "original msg")
    conversation.delete_session(ddb_table, "sub1", "sess-tx-del")

    # Simulate Tab A finishing Bedrock call after Tab B already deleted the session
    result = conversation.save_chat_turn(
        ddb_table, "sub1", "sess-tx-del",
        user_message="new question",
        assistant_content="new answer",
    )

    assert result is False
    assert conversation.get_history(ddb_table, "sub1", "sess-tx-del") == []
    assert not any(s["session_id"] == "sess-tx-del" for s in conversation.get_sessions(ddb_table, "sub1"))


def test_save_chat_turn_blocked_by_tombstone_new_session(ddb_table):
    """An old tab with a never-persisted session ID is also blocked once a tombstone exists."""
    # delete_session on a session that never had messages creates a tombstone only
    conversation.delete_session(ddb_table, "sub1", "sess-tx-never")

    result = conversation.save_chat_turn(
        ddb_table, "sub1", "sess-tx-never",
        user_message="hello",
        assistant_content="hi",
    )

    assert result is False
    assert conversation.get_history(ddb_table, "sub1", "sess-tx-never") == []


def test_save_session_if_new_blocked_by_tombstone(ddb_table):
    """save_session_if_new must not create a session record when tombstone exists."""
    conversation.delete_session(ddb_table, "sub1", "sess-tomb-block")
    # Even calling save_session_if_new directly should be a no-op (ConditionalCheckFailed ignored)
    conversation.save_session_if_new(ddb_table, "sub1", "sess-tomb-block", "hello")
    assert not any(
        s["session_id"] == "sess-tomb-block"
        for s in conversation.get_sessions(ddb_table, "sub1")
    )


def test_long_message_stored_and_retrieved_in_full(ddb_table):
    """Messages longer than 3000 chars are stored without truncation and retrieved intact."""
    long_msg = "あ" * 4000  # 4000 Japanese characters (~12,000 UTF-8 bytes)
    conversation.save_session_if_new(ddb_table, "sub1", "sess-long", long_msg)
    result = conversation.save_chat_turn(
        ddb_table, "sub1", "sess-long",
        user_message=long_msg,
        assistant_content="ok",
    )
    assert result is True
    history = conversation.get_history(ddb_table, "sub1", "sess-long", limit=10)
    user_msgs = [m for m in history if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == long_msg


# --- Decimal serialization (DynamoDB Number → Python Decimal) ---

def test_get_display_messages_numeric_fields_are_json_serializable(ddb_table):
    """boto3 high-level API returns numbers as Decimal; get_display_messages must convert to int."""
    import json
    conversation.save_session_if_new(ddb_table, "sub1", "sess-dec", "hi")
    result = conversation.save_chat_turn(
        ddb_table, "sub1", "sess-dec",
        user_message="hi",
        assistant_content="hello",
        in_tok=100,
        out_tok=50,
        model_used="au.anthropic.claude-sonnet-4-6",
        response_time_ms=1234,
    )
    assert result is True
    msgs = conversation.get_display_messages(ddb_table, "sub1", "sess-dec")
    assert len(msgs) == 2
    # Must not raise TypeError: Object of type Decimal is not JSON serializable
    body = json.dumps(msgs)
    parsed = json.loads(body)
    asst = next(m for m in parsed if m["role"] == "assistant")
    assert asst["out_tok"] == 50
    assert asst["response_time_ms"] == 1234
    user_msg = next(m for m in parsed if m["role"] == "user")
    assert user_msg["in_tok"] == 100


def test_get_display_messages_missing_response_time_is_none(ddb_table):
    """response_time_ms absent from old messages must remain None (not raise)."""
    import json
    now_ts = int(time.time())
    ddb_table.put_item(Item={
        "pk": "USER#sub-legacy#SESSION#sess-legacy",
        "sk": "MSG#2026-01-01T00:00:00+00:00#abc12345",
        "role": "assistant",
        "content": "legacy reply",
        "in_tok": 0,
        "out_tok": 30,
        "ttl": now_ts + 86400,
    })
    msgs = conversation.get_display_messages(ddb_table, "sub-legacy", "sess-legacy")
    assert len(msgs) == 1
    assert msgs[0]["response_time_ms"] is None
    json.dumps(msgs)


def test_get_display_messages_research_conversation_serializable(ddb_table):
    """Research conversations with citations and research_context must serialize to JSON."""
    import json
    now_ts = int(time.time())
    citation = {
        "id": "src-1",
        "kind": "knowledge",
        "title": "Test Doc",
        "excerpt": "some text",
        "personaId": "default",
        "documentId": "doc-abc",
    }
    research_ctx = {"persona_id": "default", "mode": "general", "chat_type": "RAG"}
    ddb_table.put_item(Item={
        "pk": "USER#sub-res#SESSION#sess-res",
        "sk": "MSG#2026-01-01T00:00:00+00:00#aabbccdd",
        "role": "assistant",
        "content": "RAG answer",
        "in_tok": 200,
        "out_tok": 80,
        "response_time_ms": 2500,
        "model_used": "au.anthropic.claude-sonnet-4-6",
        "research_context": research_ctx,
        "citations": [citation],
        "ttl": now_ts + 86400,
    })
    msgs = conversation.get_display_messages(ddb_table, "sub-res", "sess-res")
    assert len(msgs) == 1
    assert msgs[0]["research_context"] == research_ctx
    assert msgs[0]["citations"][0]["id"] == "src-1"
    body = json.dumps(msgs)
    parsed = json.loads(body)
    assert parsed[0]["out_tok"] == 80
    assert parsed[0]["response_time_ms"] == 2500
