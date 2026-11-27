import base64
import json
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

import chat_files
import chat_handler
import research

BUCKET = "chat-files-test"
MODEL = "au.anthropic.claude-sonnet-4-6"
OWNER = "test-sub-123"


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("CHAT_FILES_BUCKET", BUCKET)
    with mock_aws():
        client = boto3.client("s3", region_name="ap-southeast-2")
        client.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
        )
        yield client


def stage(client, name, data, scope="saved", session="first"):
    details = {"name": name, "size": len(data), "scope": scope, "session_id": session}
    upload = chat_files.upload_policy(OWNER, details)
    client.put_object(Bucket=BUCKET, Key=upload["fields"]["key"], Body=data)
    return {**details, "id": upload["id"]}


def test_s3_policy_binds_key_content_type_and_exact_10_mb(monkeypatch):
    monkeypatch.setenv("CHAT_FILES_BUCKET", BUCKET)
    with mock_aws():
        upload = chat_files.upload_policy(OWNER, {
            "name": "論文.pdf", "size": 10_000_000, "scope": "temporary", "session_id": "first",
        })
        assert "s3.ap-southeast-2.amazonaws.com" in upload["url"]
        fields = upload["fields"]
        policy = json.loads(base64.b64decode(fields["policy"]))
        assert ["content-length-range", 10_000_000, 10_000_000] in policy["conditions"]
        assert {"key": fields["key"]} in policy["conditions"]
        assert {"Content-Type": "application/pdf"} in policy["conditions"]
        assert fields["key"].endswith("/first/" + upload["id"])
        with pytest.raises(research.ResearchError, match="10 MB"):
            chat_files.upload_policy(OWNER, {
                "name": "論文.pdf", "size": 10_000_001, "scope": "saved",
            })


def test_saved_file_is_available_cross_session_and_deleted(storage):
    header = b"%PDF-1.7\n"
    footer = b"end"
    pdf = header + b"x" * (10_000_000 - len(header) - len(footer)) + footer
    request = stage(storage, "論文.pdf", pdf)
    file = chat_files.complete_upload(OWNER, request)
    assert file["size"] == 10_000_000
    # Completing a successful upload can be retried even after staging was cleaned up.
    assert chat_files.complete_upload(OWNER, request) == file
    assert chat_files.list_saved(OWNER, None)["documents"] == [file]
    assert chat_files.list_saved("other", None)["documents"] == []
    selected = [{"id": file["id"], "scope": "saved"}]
    for session in ("first", "second"):
        block = chat_files.model_documents(OWNER, session, selected, MODEL)[0]["document"]
        assert block == {"name": "Document 1", "format": "pdf", "source": {"bytes": pdf}}
    with pytest.raises(research.ResearchError) as error:
        chat_files.model_documents("other", "first", selected, MODEL)
    assert error.value.status == 404
    chat_files.delete_saved("other", file["id"])
    assert chat_files.list_saved(OWNER, None)["documents"] == [file]
    chat_files.delete_saved(OWNER, file["id"])
    assert chat_files.list_saved(OWNER, None)["documents"] == []
    with pytest.raises(research.ResearchError) as error:
        chat_files.model_documents(OWNER, "first", selected, MODEL)
    assert error.value.status == 404


def test_temporary_files_remain_private_to_session(storage):
    request = stage(storage, "draft.txt", "冒頭と末尾".encode(), scope="temporary")
    doc = chat_files.complete_upload(OWNER, request)
    assert chat_files.list_saved(OWNER, None)["documents"] == []
    selected = [{"id": doc["id"], "scope": "temporary"}]
    with pytest.raises(research.ResearchError) as error:
        chat_files.model_documents(OWNER, "other-session", selected, MODEL)
    assert error.value.status == 404
    assert chat_files.model_documents(OWNER, "first", selected, MODEL)[0]["document"]["format"] == "txt"


def test_limits_count_format_and_combined_payload(storage):
    documents = []
    for index in range(5):
        request = stage(storage, f"paper{index}.pdf", b"%PDF-" + b"x" * 3_700_000)
        chat_files.complete_upload(OWNER, request)
        documents.append({"id": request["id"], "scope": "saved"})
    assert len(chat_files.model_documents(OWNER, "first", documents[:4], MODEL)) == 4
    with pytest.raises(research.ResearchError, match="15 MB"):
        chat_files.model_documents(OWNER, "first", documents, MODEL)
    with pytest.raises(research.ResearchError, match="5件"):
        chat_files.model_documents(OWNER, "first", documents + documents[:1], MODEL)
    request = stage(storage, "large.docx", b"PK\x03\x04" + b"x" * 4_500_000)
    chat_files.complete_upload(OWNER, request)
    with pytest.raises(research.ResearchError, match="1文書"):
        chat_files.model_documents(OWNER, "first", [{"id": request["id"], "scope": "saved"}], MODEL)


def test_malformed_file_does_not_appear_in_library(storage):
    request = stage(storage, "not-a-pdf.pdf", b"invalid")
    with pytest.raises(research.ResearchError) as error:
        chat_files.complete_upload(OWNER, request)
    assert error.value.status == 400
    assert chat_files.list_saved(OWNER, None)["documents"] == []


def test_persona_off_bypasses_loading_and_retains_normal_chat(monkeypatch):
    active = Mock(side_effect=AssertionError("Do not load a Persona when disabled"))
    monkeypatch.setattr(research, "active_persona", active)
    response = research.chat_context(None, OWNER, {"persona_enabled": False, "chat_type": "RAG"}, "質問")
    assert response == ("", "質問", [], "default", "general", "LLM")
    active.assert_not_called()


def test_file_routes_are_authorized_before_access(monkeypatch):
    monkeypatch.setattr(chat_handler.config, "ALLOWED_SUB", OWNER)
    lookup = Mock()
    monkeypatch.setattr(chat_files, "list_saved", lookup)
    event = {
        "rawPath": "/research/files",
        "requestContext": {"http": {"method": "GET"}, "authorizer": {"jwt": {"claims": {"sub": "other"}}}},
    }
    assert chat_handler.lambda_handler(event, None)["statusCode"] == 403
    lookup.assert_not_called()


def test_chat_passes_five_saved_files_without_applying_persona(storage, monkeypatch):
    documents = [
        chat_files.complete_upload(OWNER, stage(storage, f"file{index}.txt", b"beginning and end"))
        for index in range(5)
    ]
    invoke = Mock(return_value={"input_tokens": 5, "output_tokens": 3, "content": "回答"})
    monkeypatch.setattr(chat_handler.config, "ALLOWED_SUB", OWNER)
    monkeypatch.setattr(chat_handler, "_table", None)
    monkeypatch.setattr(chat_handler.metrics, "emit_request_metrics", Mock())
    monkeypatch.setattr(chat_handler.bedrock_client, "invoke_chat", invoke)
    event = {
        "rawPath": "/chat",
        "requestContext": {"http": {"method": "POST"}, "authorizer": {"jwt": {"claims": {"sub": OWNER}}}},
        "body": json.dumps({
            "message": "資料を確認", "session_id": "another-session", "persona_enabled": False,
            "file_refs": [{"scope": "saved", "id": row["id"]} for row in documents],
        }),
    }
    response = chat_handler.lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["research_context"]["persona_enabled"] is False
    blocks = invoke.call_args.kwargs["documents"]
    assert [row["document"]["name"] for row in blocks] == [f"Document {index}" for index in range(1, 6)]
    assert all(row["document"]["source"]["bytes"] == b"beginning and end" for row in blocks)


def test_request_budget_counts_base64_and_json(monkeypatch):
    request = {
        "modelId": MODEL,
        "messages": [{"role": "user", "content": [
            {"text": "資料"}, research.document_block(1, ".pdf", b"%PDF-a"),
        ]}],
    }
    serialized = json.dumps({
        "messages": [{"role": "user", "content": [
            {"text": "資料"},
            {"document": {"name": "Document 1", "format": "pdf", "source": {"bytes": "JVBERi1h"}}},
        ]}],
    })
    monkeypatch.setattr(chat_files, "MAX_CONVERSE_BYTES", len(serialized))
    chat_files.check_request_size(request)
    monkeypatch.setattr(chat_files, "MAX_CONVERSE_BYTES", len(serialized) - 1)
    with pytest.raises(research.ResearchError) as error:
        chat_files.check_request_size(request)
    assert error.value.status == 413
