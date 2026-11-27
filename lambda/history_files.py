"""Keep the bytes sent in each message for that message's lifetime."""

import os
import re
import time
from urllib.parse import quote
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

import chat_files
import logger
import research

_QUEUE = "CHAT_FILE_RETENTION"
_TURN_ID = re.compile(r"[0-9]{12}#[0-9a-f]{32}")
_PENDING_SECONDS = 900


def _queue_key(due, archive_id):
    return {"pk": _QUEUE, "sk": f"{due:012d}#{archive_id}"}


def _object_key(archive_id, index):
    return f"history/{archive_id}/{index}"


def archive(table, owner, session_id, expires_at, names, documents, *, temporary_keys=()):
    archive_id = uuid4().hex
    pending_key = _queue_key(int(time.time()) + _PENDING_SECONDS, archive_id + "#pending")
    manifest = {
        **_queue_key(expires_at, archive_id),
        "archive_id": archive_id, "owner": owner, "session_id": session_id,
        "expires_at": expires_at, "files": names,
        "temporary_keys": list(temporary_keys),
    }
    # Record cleanup before touching S3, including for an interrupted upload.
    table.put_item(Item={**manifest, **pending_key})
    client = research.aws("s3")
    bucket = chat_files.bucket()
    for index, block in enumerate(documents):
        document = block["document"]
        client.put_object(
            Bucket=bucket, Key=_object_key(archive_id, index),
            Body=document["source"]["bytes"],
            ContentType=research.CONTENT_TYPES["." + document["format"]],
        )
    return manifest, pending_key


def public(manifest):
    return {"id": manifest["sk"], "files": manifest["files"]}


def download(table, owner, session_id, turn_id, raw_index):
    if not isinstance(turn_id, str) or not _TURN_ID.fullmatch(turn_id):
        raise research.ResearchError(400, "添付資料の指定が無効です。")
    if not isinstance(raw_index, str) or raw_index not in ("0", "1", "2", "3", "4"):
        raise research.ResearchError(400, "添付資料の指定が無効です。")
    index = int(raw_index)
    record = table.get_item(Key={"pk": _QUEUE, "sk": turn_id}, ConsistentRead=True).get("Item")
    remaining = int(record["expires_at"]) - int(time.time()) if record else 0
    if (not record or remaining <= 0 or record["owner"] != owner
            or record["session_id"] != session_id or index >= len(record["files"])):
        raise research.ResearchError(404, "添付資料の履歴が見つかりません。")
    client = research.aws("s3", regional_endpoint=True)
    bucket = chat_files.bucket()
    key = _object_key(record["archive_id"], index)
    name = record["files"][index]
    return {"url": client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key, "ResponseCacheControl": "private, no-store",
                "ResponseContentDisposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}"},
        ExpiresIn=min(chat_files.EXPIRES_IN, remaining),
    )}


def _remove(table, record, *, include_temporary=False):
    keys = [_object_key(record["archive_id"], index) for index in range(len(record["files"]))]
    if include_temporary:
        keys.extend(record.get("temporary_keys", []))
    result = research.aws("s3").delete_objects(
        Bucket=chat_files.bucket(), Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
    )
    if result.get("Errors"):
        raise RuntimeError("Attachment cleanup did not delete every object")
    if "original_sk" in record:
        table.delete_item(Key={"pk": record["pk"], "sk": record["original_sk"]})
    table.delete_item(Key={"pk": record["pk"], "sk": record["sk"]})


def remove_turn(table, turn_id):
    record = table.get_item(Key={"pk": _QUEUE, "sk": turn_id}, ConsistentRead=True).get("Item")
    if record:
        try:
            _remove(table, record, include_temporary=True)
        except (ClientError, RuntimeError):
            retry_key = _queue_key(int(time.time()), record["archive_id"] + "#delete")
            table.put_item(Item={**record, **retry_key, "original_sk": record["sk"]})
            raise


def sweep(table, limit=50):
    now = int(time.time())
    page = table.query(
        KeyConditionExpression=Key("pk").eq(_QUEUE) & Key("sk").lt(f"{now + 1:012d}#"),
        Limit=limit, ConsistentRead=True,
    )
    failed = 0
    for record in page.get("Items", []):
        try:
            _remove(table, record, include_temporary="original_sk" in record)
        except (ClientError, RuntimeError) as exc:
            failed += 1
            logger.log("ERROR", "history_attachment_cleanup_failed", error_type=type(exc).__name__)
    if failed:
        raise RuntimeError(f"Attachment cleanup failed for {failed} records")
    return len(page.get("Items", []))


def scheduled_cleanup(event, context):
    table = boto3.resource("dynamodb").Table(os.environ["DYNAMODB_TABLE"])
    return {"removed": sweep(table)}
