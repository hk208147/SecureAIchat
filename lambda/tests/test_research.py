import base64
import json
from uuid import uuid4
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws

import chat_handler
import conversation
import research


@pytest.fixture
def table():
    with mock_aws():
        service = boto3.resource("dynamodb", region_name="ap-southeast-2")
        yield service.create_table(
            TableName="research-test",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setenv("RESEARCH_KB_ID", "EXAMPLE123")
    monkeypatch.setenv("RESEARCH_DATA_SOURCE_ID", "SOURCE1234")
    monkeypatch.setenv("RESEARCH_DOCUMENT_BUCKET", "research-example")
    services = {name: Mock() for name in ("s3", "bedrock-agent", "bedrock-agent-runtime", "bedrock-agentcore")}
    monkeypatch.setattr(research, "aws", services.__getitem__)
    return services


def persona(table, sub="test-sub-123"):
    return research.save_persona(table, sub, {
        "name": "論文レビュー", "description": "論文の前提を検討する", "prompt": "主張を保つ", "chatType": "RAG",
    })


def event(method, path, body=None, sub="test-sub-123"):
    return {
        "requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": {"sub": sub}}}},
        "rawPath": path, "body": json.dumps(body),
    }


def test_persona_private_and_selection_can_override_default(table):
    created = persona(table)
    assert "documents" not in created
    assert [row["id"] for row in research.list_personas(table, "someone-else")] == ["default"]
    with pytest.raises(research.ResearchError) as error:
        research.get_persona(table, "someone-else", created["id"])
    assert error.value.status == 404
    system, message, sources, _, mode, chat_type = research.chat_context(
        table, "test-sub-123", {"persona_id": created["id"], "mode": "write", "chat_type": "LLM"}, "原稿",
    )
    assert "主張を保つ" in system and research.MODES["write"] in system
    assert (message, sources, mode, chat_type) == ("原稿", [], "write", "LLM")


def test_document_ingest_filter_and_deletion(table, services):
    created = persona(table)
    sub, persona_id, doc_id = "test-sub-123", created["id"], str(uuid4())
    body = {"id": doc_id, "name": "論点.txt", "data": base64.b64encode(b"test").decode()}
    assert research.register_document(table, sub, persona_id, body)["status"] == "PROCESSING"
    research.register_document(table, sub, persona_id, body)
    ingest = services["bedrock-agent"].ingest_knowledge_base_documents
    assert ingest.call_count == 1
    record = ingest.call_args.kwargs["documents"][0]
    uri = record["content"]["s3"]["s3Location"]["uri"]
    assert record["metadata"]["s3Location"]["uri"] == f"{uri}.metadata.json"
    assert str(persona_id) in uri
    assert json.loads(services["s3"].put_object.call_args.kwargs["Body"]) == {
        "metadataAttributes": {"persona_id": persona_id},
    }
    retrieve = services["bedrock-agent-runtime"].retrieve
    retrieve.return_value = {"retrievalResults": [
        {"location": {"s3Location": {"uri": uri}}, "content": {"text": "証拠"}},
        {"location": {"s3Location": {"uri": "s3://other/foreign.pdf"}}, "content": {"text": "隔離"}},
    ]}
    assert [source["excerpt"] for source in research.retrieve_sources(sub, research.get_persona(table, sub, persona_id), "論点")] == ["証拠"]
    assert retrieve.call_args.kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"] == {
        "equals": {"key": "persona_id", "value": persona_id},
    }
    services["bedrock-agent"].delete_knowledge_base_documents.return_value = {}
    research.delete_document(table, sub, persona_id, doc_id)
    assert not research.retrieve_sources(sub, research.get_persona(table, sub, persona_id), "論点")
    assert services["s3"].delete_object.call_count == 2


def test_deletion_failure_removes_document_from_retrieval_scope(table, services):
    created = persona(table)
    sub, persona_id, doc_id = "test-sub-123", created["id"], str(uuid4())
    research.register_document(table, sub, persona_id, {
        "id": doc_id, "name": "notes.txt", "data": "dGVzdA==",
    })
    services["bedrock-agent"].delete_knowledge_base_documents.return_value = {}
    services["s3"].delete_object.side_effect = [RuntimeError("failure"), None, None]
    with pytest.raises(RuntimeError):
        research.delete_document(table, sub, persona_id, doc_id)
    assert not research.retrieve_sources(sub, research.get_persona(table, sub, persona_id), "question")
    research.delete_document(table, sub, persona_id, doc_id)
    assert research.get_persona(table, sub, persona_id)["documents"] == []


def test_search_is_explicit_and_owner_scoped(table, services, monkeypatch):
    monkeypatch.setenv("RESEARCH_WEB_SEARCH", "true")
    monkeypatch.setattr(chat_handler, "_table", table)
    client = services["bedrock-agentcore"]
    client.invoke_web_search.return_value = {"results": [
        {"title": "結果", "url": "https://example.org/paper", "text": "抜粋"},
        {"title": "除外対象", "url": "javascript:placeholder", "text": "無効"},
    ]}
    path = "/research/search"
    assert chat_handler.lambda_handler(event("POST", path, {"query": "論点"}, "other"), None)["statusCode"] == 403
    client.invoke_web_search.assert_not_called()
    response = chat_handler.lambda_handler(event("POST", path, {"query": "論点", "draft": "下書き"}, "test-sub-123"), None)
    assert response["statusCode"] == 200
    assert [entry["title"] for entry in json.loads(response["body"])["sources"]] == ["結果"]
    client.invoke_web_search.assert_called_once_with(webSearchId="web-search.v1", searchQuery="論点", maxResults=5)


def test_chat_citations_persist_without_augmenting_user_history(table, monkeypatch):
    monkeypatch.setattr(chat_handler, "_table", table)
    body = {
        "message": "論旨を確認", "session_id": "session", "mode": "review",
        "sources": [{"kind": "attachment", "title": "文献", "locator": "PDF 2ページ", "excerpt": "根拠の抜粋"}],
    }
    with patch("chat_handler.bedrock_client.invoke_chat", return_value={
        "content": "根拠あり [S1]、未確認 [S9]", "input_tokens": 100, "output_tokens": 50,
    }) as invoke:
        response = chat_handler.lambda_handler(event("POST", "/chat", body), None)
    assert response["statusCode"] == 200
    assert [citation["id"] for citation in json.loads(response["body"])["citations"]] == ["S1"]
    assert "根拠の抜粋" in invoke.call_args.args[2]
    history = conversation.get_display_messages(table, "test-sub-123", "session")
    assert history[0]["content"] == "論旨を確認"
    assert history[1]["citations"][0]["locator"] == "PDF 2ページ"
    assert history[1]["research_context"]["mode"] == "review"


def test_switching_persona_isolates_inference_history(table):
    sub, session_id = "test-sub-123", "session"
    first = persona(table)["id"]
    second = persona(table)["id"]
    conversation.save_session_if_new(table, sub, session_id, "First")
    for label, persona_id in (("旧ターン", None), ("First", first), ("Second", second)):
        context = {"persona_id": persona_id} if persona_id else None
        conversation.save_chat_turn(
            table, sub, session_id, label, f"Answer: {label}", research_context=context,
        )
    for label, persona_id in (("First", first), ("Second", second), ("旧ターン", "default")):
        assert [message["content"] for message in conversation.get_history(
            table, sub, session_id, persona_id=persona_id,
        )] == [label, f"Answer: {label}"]


def test_global_persona_applies_to_new_and_existing_sessions(table, monkeypatch):
    monkeypatch.setattr(chat_handler, "_table", table)
    sub = "test-sub-123"
    chosen = persona(table)["id"]
    path = "/research/personas/active"

    denied = chat_handler.lambda_handler(event("PUT", path, {"persona_id": chosen}, sub="another"), None)
    assert denied["statusCode"] == 403
    unknown = chat_handler.lambda_handler(event("PUT", path, {"persona_id": str(uuid4())}), None)
    assert unknown["statusCode"] == 404
    saved = chat_handler.lambda_handler(event("PUT", path, {"persona_id": chosen}), None)
    assert json.loads(saved["body"]) == {"activePersonaId": chosen}
    assert research.active_persona(table, "another")["id"] == "default"

    conversation.save_session_if_new(table, sub, "old", "前の質問")
    conversation.save_chat_turn(
        table, sub, "old", user_message="前の質問", assistant_content="前の回答", in_tok=1, out_tok=1,
    )
    with patch("chat_handler.bedrock_client.invoke_chat", return_value={
        "content": "回答", "input_tokens": 3, "output_tokens": 2,
    }) as invoke:
        for session in ("old", "new"):
            response = chat_handler.lambda_handler(event("POST", "/chat", {
                "message": "検討", "session_id": session, "mode": "general",
            }), None)
            assert response["statusCode"] == 200
            assert json.loads(response["body"])["research_context"]["persona_id"] == chosen
            assert invoke.call_args.kwargs["system_text"] == "主張を保つ"
            history = invoke.call_args.args[1]
            assert [row["content"] for row in history] == (["前の質問", "前の回答"] if session == "old" else [])

    research.delete_persona(table, sub, chosen)
    response = chat_handler.lambda_handler(event("GET", "/research/personas", {}), None)
    assert json.loads(response["body"])["activePersonaId"] == "default"


def test_chat_sends_document_bytes_and_stores_only_metadata_in_dynamodb(table, monkeypatch):
    monkeypatch.setattr(chat_handler, "_table", table)
    monkeypatch.setenv("CHAT_FILES_BUCKET", "inline-attachments-test")
    s3 = boto3.client("s3", region_name="ap-southeast-2")
    s3.create_bucket(Bucket="inline-attachments-test", CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"})
    pdf = b"%PDF-1.7\nSTART\n" + b"x" * 5000 + b"\nEND"
    docx = b"PK\x03\x04word-document"
    client = Mock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": "回答"}]}},
        "usage": {"inputTokens": 2, "outputTokens": 3},
    }
    monkeypatch.setattr(chat_handler, "_bedrock", client)
    response = chat_handler.lambda_handler(event("POST", "/chat", {
        "message": "文書を読む", "session_id": "attachments",
        "attachments": [
            {"name": "旅行計画.pdf", "data": base64.b64encode(pdf).decode()},
            {"name": "議事録.docx", "data": base64.b64encode(docx).decode()},
        ],
    }), None)

    assert response["statusCode"] == 200
    assert client.converse.call_args.kwargs["messages"][-1]["content"] == [
        {"text": "文書を読む"},
        {"document": {"name": "Document 1", "format": "pdf", "source": {"bytes": pdf}}},
        {"document": {"name": "Document 2", "format": "docx", "source": {"bytes": docx}}},
    ]
    history = conversation.get_history(table, "test-sub-123", "attachments")
    assert [entry["content"] for entry in history] == ["文書を読む", "回答"]
    messages = conversation.get_display_messages(table, "test-sub-123", "attachments")
    attachments = json.loads(response["body"])["attachments"]
    assert messages[0]["attachments"] == attachments
    assert attachments["files"] == ["旅行計画.pdf", "議事録.docx"]
    archive_id = attachments["id"].split("#")[1]
    for index, data in enumerate([pdf, docx]):
        stored = s3.get_object(Bucket="inline-attachments-test", Key=f"history/{archive_id}/{index}")
        assert stored["Body"].read() == data
    json.dumps(messages)


def test_combined_attachment_size_is_rejected_before_converse(table, monkeypatch):
    monkeypatch.setattr(chat_handler, "_table", table)
    data = base64.b64encode(b"x" * (research.MAX_FILE_BYTES // 2 + 1)).decode()
    with patch("chat_handler.bedrock_client.invoke_chat") as invoke:
        response = chat_handler.lambda_handler(event("POST", "/chat", {
            "message": "読む", "attachments": [{"name": "notes.txt", "data": data}] * 2,
        }), None)
    assert response["statusCode"] == 413
    invoke.assert_not_called()
