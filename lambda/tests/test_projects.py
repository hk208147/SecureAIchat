import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from moto import mock_aws

import chat_files
import chat_handler
import conversation
import history_files
from research import document_block
from tests.test_chat_files import BUCKET, OWNER, stage
from tests.test_chat_handler import _make_context, _make_event, _mock_bedrock_result


@pytest.fixture
def project_app(monkeypatch):
    monkeypatch.setenv("CHAT_FILES_BUCKET", BUCKET)
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-southeast-2")
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"})
        table = boto3.resource("dynamodb", region_name="ap-southeast-2").create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        calls = []

        def invoke(client, history, message, **kwargs):
            calls.append((history, kwargs))
            return _mock_bedrock_result()

        monkeypatch.setattr(chat_handler, "_table", table)
        monkeypatch.setattr(chat_handler.bedrock_client, "invoke_chat", invoke)
        monkeypatch.setattr(chat_handler.metrics, "emit_request_metrics", lambda *_: None)

        def request(method, path, body=None, status=200, **params):
            event = _make_event(method, path, body)
            event["queryStringParameters"] = params
            result = chat_handler.lambda_handler(event, _make_context())
            assert result["statusCode"] == status, result
            return json.loads(result["body"])

        yield request, table, s3, calls


def test_project_a_b_and_existing_general_chat(project_app):
    request, table, s3, calls = project_app
    conversation.save_session_if_new(table, OWNER, "same-id", "従来の一般履歴")
    conversation.save_message(table, OWNER, "same-id", "user", "従来の一般履歴")

    def persona(name):
        return request("POST", "/research/personas", {
            "name": name, "description": name, "prompt": f"指示 {name}", "chatType": "LLM",
        })["id"]

    personal, persona_a, persona_b = [persona(name) for name in ("一般", "A", "B")]
    request("PUT", "/research/personas/active", {"persona_id": personal})
    project_a, project_b = [
        request("POST", "/research/projects", {"name": name}, status=201)["id"] for name in ("A", "B")
    ]
    assert {project["id"] for project in request("GET", "/research/projects")["projects"]} == {project_a, project_b}
    for project, selected in [(project_a, persona_a), (project_b, persona_b)]:
        request("PUT", "/research/projects", {"project_id": project, "persona_id": selected})

    file_a, file_b = [
        chat_files.complete_upload(OWNER, stage(s3, name, name.encode()))
        for name in ("A.txt", "B.txt")
    ]
    for project, file in [(project_a, file_a), (project_b, file_b)]:
        request("POST", "/research/files/import", {"project_id": project, "id": file["id"]})
        assert request("GET", "/research/files", project_id=project)["documents"] == [file]
    assert request("GET", "/research/files")["documents"] == sorted([file_a, file_b], key=lambda item: item["id"])

    def send(message, project=None, **options):
        return request("POST", "/chat", {
            "session_id": "same-id", "message": message, "persona_enabled": True,
            "project_id": project, **options,
        })["research_context"]["persona_id"]

    ref_a = {"id": file_a["id"], "scope": "saved"}
    assert send("会話A", project_a, persona_id=persona_b, file_refs=[ref_a]) == persona_a
    assert calls[-1][0] == []
    assert "指示 A" in calls[-1][1]["system_text"]
    request("POST", "/chat", {"session_id": "same-id", "message": "混入", "project_id": project_b,
                            "file_refs": [ref_a]}, status=404)
    assert send("会話B", project_b) == persona_b
    assert calls[-1][0] == []
    assert "指示 B" in calls[-1][1]["system_text"]
    assert send("一般チャット") == personal
    assert calls[-1][0] == [{"role": "user", "content": "従来の一般履歴"}]
    assert "指示 一般" in calls[-1][1]["system_text"]

    request("PUT", "/research/projects", {"project_id": project_a, "persona_id": persona_b})
    assert send("変更後の会話A", project_a) == persona_b
    assert calls[-1][0][0]["content"] == "会話A"
    assert "指示 B" in calls[-1][1]["system_text"]
    assert send("Persona無効", project_a, persona_enabled=False) == "default"
    assert "指示" not in calls[-1][1].get("system_text", "")
    for params, first in [({}, "従来の一般履歴"), ({"project_id": project_a}, "会話A"), ({"project_id": project_b}, "会話B")]:
        assert request("GET", "/sessions", **params)["sessions"][0]["firstMessage"] == first
        assert request("GET", "/messages", session_id="same-id", **params)["messages"][0]["content"] == first
    request("DELETE", "/sessions", session_id="same-id", project_id=project_a)
    assert request("GET", "/sessions", project_id=project_a)["sessions"] == []
    assert request("GET", "/sessions", project_id=project_b)["sessions"]
    assert request("GET", "/sessions")["sessions"]


def test_attachment_downloads_survive_unsend_and_registration_removal(project_app, monkeypatch):
    request, table, s3, calls = project_app
    now = int(time.time())
    clock = SimpleNamespace(time=lambda: now)
    monkeypatch.setattr(history_files, "time", clock)
    monkeypatch.setattr(conversation, "time", clock)
    temp = chat_files.complete_upload(OWNER, stage(s3, "一時.txt", b"temp", "temporary", "first"))
    saved = chat_files.complete_upload(OWNER, stage(s3, "共通.txt", b"saved"))

    def send(session, refs):
        return request("POST", "/chat", {"session_id": session, "message": "送信", "file_refs": refs})

    saved_ref = {"id": saved["id"], "scope": "saved"}
    first = send("first", [{"id": temp["id"], "scope": "temporary"}, saved_ref])["attachments"]
    assert first["files"] == ["一時.txt", "共通.txt"]
    assert request("GET", "/messages", session_id="first")["messages"][0]["attachments"] == first

    # Emulate the one-day S3 lifecycle independently of the message TTL.
    now += 86_400 + 1
    s3.delete_object(Bucket=BUCKET, Key=chat_files._prefix(OWNER, "temporary", "first") + temp["id"])
    second = send("second", [saved_ref])["attachments"]
    assert "attachments" not in send("first", [])
    assert "documents" not in calls[-1][1]

    def download(turn, session, index, status=200, **params):
        return request("GET", "/research/files/history", status=status, session_id=session,
                       turn_id=turn["id"], index=str(index), **params)

    def bytes_at(turn, index):
        return s3.get_object(Bucket=BUCKET, Key=history_files._object_key(turn["id"].split("#")[1], index))["Body"].read()

    temp_url = download(first, "first", 0)["url"]
    assert parse_qs(urlparse(temp_url).query)["response-content-disposition"][0].startswith("attachment; filename*=")
    assert bytes_at(first, 0) == b"temp"
    download(first, "second", 0, status=404)
    project = request("POST", "/research/projects", {"name": "A"}, status=201)["id"]
    download(first, "first", 0, status=404, project_id=project)
    assert request("GET", "/research/files")["documents"] == [saved]

    # Expiring one message leaves both the later reference and the saved registration.
    now = int(first["id"].split("#")[0])
    assert request("GET", "/messages", session_id="first")["messages"][0]["content"] == "送信"
    assert any(item["session_id"] == "first" for item in request("GET", "/sessions")["sessions"])
    download(first, "first", 0, status=404)
    assert history_files.sweep(table) == 1
    download(second, "second", 0)
    assert bytes_at(second, 0) == b"saved"
    assert request("GET", "/research/files")["documents"] == [saved]

    request("DELETE", "/research/files", id=saved["id"])
    assert request("GET", "/research/files")["documents"] == []
    download(second, "second", 0)
    assert bytes_at(second, 0) == b"saved"
    request("DELETE", "/sessions", session_id="second")
    download(second, "second", 0, status=404)
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="history/")["KeyCount"] == 0


def test_uncommitted_archive_is_reclaimed_after_upload_interruption(project_app, monkeypatch):
    _, table, s3, _ = project_app
    now = int(time.time())
    monkeypatch.setattr(history_files, "time", SimpleNamespace(time=lambda: now))
    archive, _ = history_files.archive(
        table, OWNER, "first", now + 86_400, ["draft.txt"], [document_block(1, ".txt", b"draft")],
    )
    assert history_files.sweep(table) == 0
    assert s3.get_object(Bucket=BUCKET, Key=history_files._object_key(archive["archive_id"], 0))["ContentLength"] == 5
    now += history_files._PENDING_SECONDS
    assert history_files.sweep(table) == 1
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="history/")["KeyCount"] == 0
    assert history_files.sweep(table) == 0


def test_cleanup_retries_a_deleted_session_and_leaves_unsent_drafts(project_app, monkeypatch):
    request, table, s3, _ = project_app
    sent = chat_files.complete_upload(OWNER, stage(s3, "sent.txt", b"sent", "temporary"))
    draft = chat_files.complete_upload(OWNER, stage(s3, "unsent.txt", b"draft", "temporary"))
    turn = request("POST", "/chat", {
        "session_id": "first", "message": "送信", "file_refs": [{"scope": "temporary", "id": sent["id"]}],
    })["attachments"]

    def fail_once(*args, **kwargs):
        return {"Errors": [{"Code": "ServiceUnavailable"}]}

    with monkeypatch.context() as patch:
        patch.setattr(s3, "delete_objects", fail_once)
        patch.setattr(history_files.research, "aws", lambda *args, **kwargs: s3)
        request("DELETE", "/sessions", session_id="first", status=502)
    request("GET", "/research/files/history", session_id="first", turn_id=turn["id"], index="0", status=404)
    assert request("GET", "/messages", session_id="first")["messages"] == []
    assert history_files.sweep(table) == 1
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="history/")["KeyCount"] == 0
    remaining = s3.list_objects_v2(Bucket=BUCKET, Prefix="temporary/")["Contents"]
    assert [item["Key"] for item in remaining] == [chat_files._prefix(OWNER, "temporary", "first") + draft["id"]]
