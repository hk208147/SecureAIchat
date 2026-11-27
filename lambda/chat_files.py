"""Owner-scoped saved files and session-scoped temporary attachments."""

import hashlib
import json
import os
import re
from contextlib import closing
from urllib.parse import quote, unquote
from uuid import uuid4

from botocore.exceptions import ClientError

import logger
import research

MAX_FILE_BYTES = 10_000_000
MAX_FILES = 5
# 20 MB of serialized Converse request data allows at most 15 MB before Base64.
MAX_MODEL_BYTES = 15_000_000
MAX_CONVERSE_BYTES = 20_000_000
STANDARD_DOCUMENT_BYTES = 4_500_000
LARGE_PDF_MODELS = {
    "au.anthropic.claude-sonnet-4-6",
    "au.anthropic.claude-opus-4-6-v1",
}
EXPIRES_IN = 300
SESSION_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}")


def bucket():
    bucket = os.environ.get("CHAT_FILES_BUCKET")
    if not bucket:
        raise research.ResearchError(503, "資料の保存先が利用できません。")
    return bucket


def _name(value):
    name = research.bounded_text(value, 180, "File name")
    extension = os.path.splitext(name)[1].lower()
    if (
        extension not in research.CONTENT_TYPES
        or not name.isprintable()
        or "/" in name
        or "\\" in name
        or len(quote(name, safe="")) > 700
    ):
        raise research.ResearchError(400, "PDF、DOCX、TXT、Markdownを選んでください。")
    return name, extension


def _reference(value):
    if not isinstance(value, str) or len(value) > 737:
        raise research.ResearchError(400, "資料IDが無効です。")
    identifier, _, encoded_name = value.partition("/")
    research.checked_id(identifier)
    name, extension = _name(unquote(encoded_name))
    if quote(name, safe="") != encoded_name:
        raise research.ResearchError(400, "資料IDが無効です。")
    return name, extension


def _prefix(sub, scope, session_id):
    owner = hashlib.sha256(sub.encode("utf-8")).hexdigest()
    if scope == "saved":
        return f"saved/{owner}/"
    if scope == "temporary" and isinstance(session_id, str) and SESSION_ID.fullmatch(session_id):
        return f"temporary/{owner}/{session_id}/"
    raise research.ResearchError(400, "資料の保存先が無効です。")


def upload_policy(sub, request):
    name, extension = _name(request.get("name"))
    size = request.get("size")
    if type(size) is not int or not 1 <= size <= MAX_FILE_BYTES:
        raise research.ResearchError(413, "ファイルは空でない10 MB以下のものを選んでください。")
    reference = f"{uuid4()}/{quote(name, safe='')}"
    key = "staging/" + _prefix(sub, request.get("scope"), request.get("session_id")) + reference
    content_type = research.CONTENT_TYPES[extension]
    upload = research.aws("s3", regional_endpoint=True).generate_presigned_post(
        Bucket=bucket(), Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}, ["content-length-range", size, size]],
        ExpiresIn=EXPIRES_IN,
    )
    return {"id": reference, **upload}


def _s3_object(client, bucket, key, *, head=False):
    try:
        method = client.head_object if head else client.get_object
        return method(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        # Without ListBucket on all object prefixes S3 can also return 403.
        if exc.response["Error"]["Code"] in ("403", "AccessDenied"):
            return None
        raise


def _read(obj, extension):
    with closing(obj["Body"]) as stream:
        if not 1 <= obj["ContentLength"] <= MAX_FILE_BYTES:
            raise research.ResearchError(413, "ファイルサイズが上限を超えています。")
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) != obj["ContentLength"]:
        raise research.ResearchError(409, "資料を再度アップロードしてください。")
    research.validate_document_bytes(extension, data)
    return data


def complete_upload(sub, request):
    reference = request.get("id")
    name, extension = _reference(reference)
    key = _prefix(sub, request.get("scope"), request.get("session_id")) + reference
    storage_bucket = bucket()
    client = research.aws("s3")
    existing = _s3_object(client, storage_bucket, key, head=True)
    if existing:
        return {"id": reference, "name": name, "size": existing["ContentLength"]}
    staged = _s3_object(client, storage_bucket, "staging/" + key)
    if staged is None:
        raise research.ResearchError(409, "アップロード済みのファイルが見つかりません。再度添付してください。")
    data = _read(staged, extension)
    try:
        client.put_object(
            Bucket=storage_bucket, Key=key, Body=data,
            ContentType=research.CONTENT_TYPES[extension], IfNoneMatch="*",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("PreconditionFailed", "412"):
            raise
        existing = _s3_object(client, storage_bucket, key, head=True)
        if existing is None:
            raise research.ResearchError(409, "資料の状態が変わりました。再度添付してください。") from exc
        return {"id": reference, "name": name, "size": existing["ContentLength"]}
    try:
        client.delete_object(Bucket=storage_bucket, Key="staging/" + key)
    except ClientError as exc:
        # S3 lifecycle also expires staging if the cleanup request fails.
        logger.log("WARNING", "chat_file_staging_cleanup_failed", error_type=type(exc).__name__)
    return {"id": reference, "name": name, "size": len(data)}


def list_saved(sub, cursor):
    prefix = _prefix(sub, "saved", None)
    client = research.aws("s3")
    args = {"Bucket": bucket(), "Prefix": prefix, "MaxKeys": 50}
    if cursor:
        args["ContinuationToken"] = research.bounded_text(cursor, 2048, "Continuation token")
    try:
        page = client.list_objects_v2(**args)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "InvalidArgument":
            raise research.ResearchError(400, "資料一覧を最初から読み込んでください。") from exc
        raise
    documents = []
    for item in page.get("Contents", []):
        reference = item["Key"][len(prefix):]
        documents.append({
            "id": reference, "name": _reference(reference)[0], "size": item["Size"],
        })
    return {"documents": documents, "nextCursor": page.get("NextContinuationToken")}


def delete_saved(sub, reference):
    _reference(reference)
    research.aws("s3").delete_object(Bucket=bucket(), Key=_prefix(sub, "saved", None) + reference)
    return {"deleted": True}


def sent_temporary_keys(sub, session_id, entries):
    prefix = _prefix(sub, "temporary", session_id)
    return [prefix + entry["id"] for entry in entries if entry.get("scope") == "temporary"]


def import_saved(sub, destination, reference):
    name, extension = _reference(reference)
    storage_bucket = bucket()
    client = research.aws("s3")
    target = _prefix(destination, "saved", None) + reference
    existing = _s3_object(client, storage_bucket, target, head=True)
    if existing:
        return {"id": reference, "name": name, "size": existing["ContentLength"]}
    source = _s3_object(client, storage_bucket, _prefix(sub, "saved", None) + reference)
    if source is None:
        raise research.ResearchError(404, "共通の保存済み資料が見つかりません。")
    data = _read(source, extension)
    try:
        client.put_object(Bucket=storage_bucket, Key=target, Body=data,
                          ContentType=research.CONTENT_TYPES[extension], IfNoneMatch="*")
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("PreconditionFailed", "412"):
            raise
    return {"id": reference, "name": name, "size": len(data)}


def model_documents(sub, session_id, entries, model_id, *, names=None):
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise research.ResearchError(400, "1チャットに添付できる資料は5件までです。")
    if not entries:
        return []
    client = research.aws("s3")
    storage_bucket = bucket()
    selected = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise research.ResearchError(400, "資料の指定が無効です。")
        reference = entry.get("id")
        name, extension = _reference(reference)
        key = _prefix(sub, entry.get("scope"), session_id) + reference
        if key in seen:
            raise research.ResearchError(400, "同じ資料が複数選択されています。")
        seen.add(key)
        head = _s3_object(client, storage_bucket, key, head=True)
        if head is None:
            raise research.ResearchError(404, f"「{name}」は削除されたか、有効期限が切れました。選び直してください。")
        maximum = MAX_FILE_BYTES if extension == ".pdf" and model_id in LARGE_PDF_MODELS else STANDARD_DOCUMENT_BYTES
        size = head["ContentLength"]
        if size > maximum:
            raise research.ResearchError(413, f"「{name}」は選択中のモデルで送信できる1文書の上限を超えています。")
        selected.append((key, name, extension, size))
    if sum(size for _, _, _, size in selected) > MAX_MODEL_BYTES:
        raise research.ResearchError(413, "1回の送信では資料の合計を15 MB以下に減らしてください。")
    documents = []
    for index, (key, name, extension, size) in enumerate(selected, 1):
        obj = _s3_object(client, storage_bucket, key)
        if obj is None or obj["ContentLength"] != size:
            if obj:
                obj["Body"].close()
            raise research.ResearchError(409, f"「{name}」を選び直してください。")
        # Reuse SABRC's full-byte Converse document blocks via the Phase 1B adapter.
        documents.append(research.document_block(index, extension, _read(obj, extension)))
        if names is not None:
            names.append(name)
    return documents


def check_request_size(kwargs):
    """Measure JSON and Base64 lengths without duplicating entire files in memory."""
    request_body = {key: value for key, value in kwargs.items() if key != "modelId"}
    base64_bytes = 0
    messages = []
    for message in request_body["messages"]:
        content = []
        for block in message["content"]:
            if "document" not in block:
                content.append(block)
                continue
            document = block["document"]
            data = document["source"]["bytes"]
            base64_bytes += 4 * ((len(data) + 2) // 3)
            content.append({"document": {**document, "source": {"bytes": ""}}})
        messages.append({**message, "content": content})
    request_body["messages"] = messages
    if len(json.dumps(request_body)) + base64_bytes > MAX_CONVERSE_BYTES:
        raise research.ResearchError(413, "会話履歴と資料を含むモデルへの送信サイズが上限を超えています。選ぶ資料を減らしてください。")
