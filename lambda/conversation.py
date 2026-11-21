import time
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

import config

_serializer = TypeSerializer()


def _serialize_item(item: dict) -> dict:
    return {k: _serializer.serialize(v) for k, v in item.items()}


def _ttl() -> int:
    return int(time.time()) + config.TTL_DAYS * 86400


def _now() -> int:
    return int(time.time())


def _msg_pk(user_sub: str, session_id: str) -> str:
    return f"USER#{user_sub}#SESSION#{session_id}"


def _session_pk(user_sub: str) -> str:
    return f"USER#{user_sub}"


def get_history(
    table, user_sub: str, session_id: str, limit: int = config.MAX_CONTEXT_MESSAGES
) -> list[dict]:
    pk = _msg_pk(user_sub, session_id)
    now = _now()
    valid: list[dict] = []
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("MSG#"),
        "FilterExpression": Attr("ttl").gt(now),
        "ScanIndexForward": False,
        "Limit": limit * 3,
    }
    while len(valid) < limit:
        resp = table.query(**kwargs)
        valid.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    valid = valid[:limit]
    valid.reverse()
    return [{"role": item["role"], "content": item["content"]} for item in valid]


def get_display_messages(
    table, user_sub: str, session_id: str, limit: int = config.MESSAGES_DISPLAY_LIMIT
) -> list[dict]:
    pk = _msg_pk(user_sub, session_id)
    now = _now()
    valid: list[dict] = []
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("MSG#"),
        "FilterExpression": Attr("ttl").gt(now),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    while len(valid) < limit:
        resp = table.query(**kwargs)
        valid.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    valid = valid[:limit]
    valid.reverse()
    result = []
    for item in valid:
        sk = item.get("sk", "")
        parts = sk.split("#", 2)
        ts = parts[1] if len(parts) >= 2 else ""
        result.append({
            "role": item["role"],
            "content": item["content"],
            "timestamp": ts,
            "in_tok": item.get("in_tok", 0),
            "out_tok": item.get("out_tok", 0),
            "model_used": item.get("model_used"),
            "thinking_level": item.get("thinking_level"),
            "response_time_ms": item.get("response_time_ms"),
        })
    return result


def save_message(
    table,
    user_sub: str,
    session_id: str,
    role: str,
    content: str,
    in_tok: int = 0,
    out_tok: int = 0,
    model_used: str | None = None,
    thinking_level: str | None = None,
    response_time_ms: int | None = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    uid = uuid.uuid4().hex[:8]
    sk = f"MSG#{ts}#{uid}"
    item: dict = {
        "pk": _msg_pk(user_sub, session_id),
        "sk": sk,
        "role": role,
        "content": content,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "ttl": _ttl(),
    }
    if model_used is not None:
        item["model_used"] = model_used
    if thinking_level is not None:
        item["thinking_level"] = thinking_level
    if response_time_ms is not None:
        item["response_time_ms"] = response_time_ms
    table.put_item(Item=item)


def save_session_if_new(
    table, user_sub: str, session_id: str, first_message: str
) -> None:
    sk = f"SESSION#{session_id}"
    ts = datetime.now(timezone.utc).isoformat()
    try:
        table.put_item(
            Item={
                "pk": _session_pk(user_sub),
                "sk": sk,
                "session_id": session_id,
                "firstMessage": first_message[:100],
                "created_at": ts,
                "ttl": _ttl(),
            },
            ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return
        raise


def save_chat_turn(
    table,
    user_sub: str,
    session_id: str,
    user_message: str,
    assistant_content: str,
    in_tok: int = 0,
    out_tok: int = 0,
    model_used: str | None = None,
    thinking_level: str | None = None,
    response_time_ms: int | None = None,
) -> bool:
    """Write user+assistant messages transactionally, blocked by session tombstone.

    Uses TransactWriteItems with a ConditionCheck on the session record.
    Returns True if saved, False if the session tombstone blocked the write.
    """
    table_name: str = table.name
    region = table.meta.client.meta.region_name
    client = boto3.client("dynamodb", region_name=region)
    msg_pk = _msg_pk(user_sub, session_id)
    base_ts = datetime.now(timezone.utc)

    user_uid = uuid.uuid4().hex[:8]
    asst_uid = uuid.uuid4().hex[:8]
    user_ts = base_ts
    asst_ts = base_ts + timedelta(microseconds=1)

    user_item: dict = {
        "pk": msg_pk,
        "sk": f"MSG#{user_ts.isoformat()}#{user_uid}",
        "role": "user",
        "content": user_message,
        "in_tok": in_tok,
        "out_tok": 0,
        "ttl": _ttl(),
    }
    asst_item: dict = {
        "pk": msg_pk,
        "sk": f"MSG#{asst_ts.isoformat()}#{asst_uid}",
        "role": "assistant",
        "content": assistant_content,
        "in_tok": 0,
        "out_tok": out_tok,
        "ttl": _ttl(),
    }
    for attr, val in (
        ("model_used", model_used),
        ("thinking_level", thinking_level),
        ("response_time_ms", response_time_ms),
    ):
        if val is not None:
            asst_item[attr] = val

    try:
        client.transact_write_items(TransactItems=[
            {
                "ConditionCheck": {
                    "TableName": table_name,
                    "Key": {
                        "pk": {"S": _session_pk(user_sub)},
                        "sk": {"S": f"SESSION#{session_id}"},
                    },
                    # Passes for non-existent session records (new session) and
                    # existing sessions without a tombstone. Fails only when
                    # deleted=True was written by delete_session.
                    "ConditionExpression": "attribute_not_exists(#d)",
                    "ExpressionAttributeNames": {"#d": "deleted"},
                }
            },
            {"Put": {"TableName": table_name, "Item": _serialize_item(user_item)}},
            {"Put": {"TableName": table_name, "Item": _serialize_item(asst_item)}},
        ])
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            return False
        raise


def delete_session(table, user_sub: str, session_id: str) -> None:
    """Delete a session: writes tombstone first (prevents resurrection), then batch-deletes messages.

    Tombstone-first ordering means that even if the message cleanup fails partway
    through, any in-flight save_chat_turn or save_session_if_new will be blocked
    on retry and the session will not reappear in get_sessions.
    """
    # 1. Write tombstone — atomically prevents save_chat_turn and save_session_if_new
    #    from recreating this session. TTL auto-expires the record after 30 days.
    table.put_item(Item={
        "pk": _session_pk(user_sub),
        "sk": f"SESSION#{session_id}",
        "deleted": True,
        "ttl": _ttl(),
    })

    # 2. Query all message keys (projection only, follow pagination)
    pk_msg = _msg_pk(user_sub, session_id)
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(pk_msg) & Key("sk").begins_with("MSG#"),
        "ProjectionExpression": "pk, sk",
    }
    keys: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            keys.append({"pk": item["pk"], "sk": item["sk"]})
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # 3. Batch-delete messages
    with table.batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key=key)


def get_sessions(table, user_sub: str, limit: int = 20) -> list[dict]:
    pk = _session_pk(user_sub)
    now = _now()
    # Fetch ALL session records (no Limit), filter expired ones, then pick the newest `limit`.
    # A DynamoDB Limit on a query with FilterExpression scans that many items before filtering,
    # which could exclude the newest sessions when total sessions exceed Limit.
    # For personal use (~90 sessions with 30-day TTL) this scan is at most a few KB.
    all_items: list[dict] = []
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("SESSION#"),
        "FilterExpression": Attr("ttl").gt(now) & Attr("deleted").not_exists(),
    }
    while True:
        resp = table.query(**kwargs)
        all_items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    all_items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    top = all_items[:limit]
    return [
        {"session_id": item["session_id"], "firstMessage": item.get("firstMessage", "")}
        for item in top
    ]
