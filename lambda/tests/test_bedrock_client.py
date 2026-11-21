import pytest
from unittest.mock import MagicMock, patch
import config
import bedrock_client


def _make_mock_client(content="test response", input_tokens=100, output_tokens=50):
    client = MagicMock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": content}]}},
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
        "stopReason": "end_turn",
    }
    return client


def test_converse_called_with_correct_model_id():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello")
    call_kwargs = client.converse.call_args[1]
    assert call_kwargs["modelId"] == config.MODEL_ID


def test_model_id_is_fixed_regardless_of_history():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [{"role": "user", "content": "hi"}], "follow up")
    assert client.converse.call_args[1]["modelId"] == "au.anthropic.claude-sonnet-4-6"


def test_explicit_model_id_overrides_default():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello", model_id="au.anthropic.claude-opus-4-6-v1")
    assert client.converse.call_args[1]["modelId"] == "au.anthropic.claude-opus-4-6-v1"


def test_inference_config_max_tokens():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello")
    inf = client.converse.call_args[1]["inferenceConfig"]
    assert inf["maxTokens"] == 4000


def test_inference_config_temperature():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello")
    inf = client.converse.call_args[1]["inferenceConfig"]
    assert inf["temperature"] == 0.7


def test_messages_list_ends_with_user_message():
    client = _make_mock_client()
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    bedrock_client.invoke_chat(client, history, "new question")
    messages = client.converse.call_args[1]["messages"]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"][0]["text"] == "new question"


def test_history_included_in_messages():
    client = _make_mock_client()
    history = [{"role": "user", "content": "first"}]
    bedrock_client.invoke_chat(client, history, "second")
    messages = client.converse.call_args[1]["messages"]
    assert len(messages) == 2
    assert messages[0]["content"][0]["text"] == "first"


def test_system_in_converse_call():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello", system_text="You are helpful.")
    system = client.converse.call_args[1]["system"]
    assert isinstance(system, list)
    assert system[0]["text"] == "You are helpful."


def test_no_cache_point_when_system_below_threshold():
    client = _make_mock_client()
    short_system = "short"  # well below 1024 token estimate
    bedrock_client.invoke_chat(client, [], "hello", system_text=short_system)
    system = client.converse.call_args[1]["system"]
    assert not any("cachePoint" in part for part in system)


def test_cache_point_added_to_system_when_above_threshold():
    client = _make_mock_client()
    long_system = "a" * (config.CACHE_MIN_TOKENS * 4)  # exactly at threshold
    bedrock_client.invoke_chat(client, [], "hello", system_text=long_system)
    system = client.converse.call_args[1]["system"]
    assert any("cachePoint" in part for part in system)


def test_no_cache_point_in_user_message_when_tokens_below_threshold():
    client = _make_mock_client()
    short_msg = "hi"  # very short
    bedrock_client.invoke_chat(client, [], short_msg, system_text="short system")
    messages = client.converse.call_args[1]["messages"]
    user_content = messages[-1]["content"]
    assert not any("cachePoint" in part for part in user_content)


def test_cache_point_added_to_user_message_when_tokens_above_threshold():
    client = _make_mock_client()
    long_msg = "b" * (config.CACHE_MIN_TOKENS * 4)
    bedrock_client.invoke_chat(client, [], long_msg, system_text="short system")
    messages = client.converse.call_args[1]["messages"]
    user_content = messages[-1]["content"]
    assert any("cachePoint" in part for part in user_content)


def test_return_value_shape():
    client = _make_mock_client(content="answer", input_tokens=10, output_tokens=20)
    result = bedrock_client.invoke_chat(client, [], "question")
    assert result["content"] == "answer"
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 20
    assert "stop_reason" in result
    assert "model_used" in result


def test_model_used_in_return_value():
    client = _make_mock_client()
    result = bedrock_client.invoke_chat(client, [], "hi", model_id="au.anthropic.claude-opus-4-6-v1")
    assert result["model_used"] == "au.anthropic.claude-opus-4-6-v1"


def test_legacy_path_uses_temperature():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello")
    inf = client.converse.call_args[1]["inferenceConfig"]
    assert "temperature" in inf
    assert "additionalModelRequestFields" not in client.converse.call_args[1]


def test_thinking_path_no_temperature():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello", thinking_level="medium")
    inf = client.converse.call_args[1]["inferenceConfig"]
    assert "temperature" not in inf


def test_thinking_path_sends_adaptive_thinking():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello", thinking_level="high")
    extra = client.converse.call_args[1]["additionalModelRequestFields"]
    assert extra["thinking"]["type"] == "adaptive"
    assert extra["output_config"]["effort"] == "high"


def test_thinking_level_low_uses_low_effort():
    client = _make_mock_client()
    bedrock_client.invoke_chat(client, [], "hello", thinking_level="low")
    extra = client.converse.call_args[1]["additionalModelRequestFields"]
    assert extra["output_config"]["effort"] == "low"


def test_bedrock_invoke_start_logged_with_kwargs_values():
    """bedrock_invoke_start must log model_id and effort from the actual Converse kwargs."""
    from unittest.mock import patch as _patch
    client = _make_mock_client()
    with _patch("bedrock_client.logger.log") as mock_log:
        bedrock_client.invoke_chat(
            client,
            [{"role": "user", "content": "hi"}],
            "follow up",
            model_id="au.anthropic.claude-opus-4-6-v1",
            thinking_level="low",
        )
    start_calls = [c for c in mock_log.call_args_list if len(c.args) >= 2 and c.args[1] == "bedrock_invoke_start"]
    assert len(start_calls) == 1
    kw = start_calls[0].kwargs
    assert kw["model_id"] == "au.anthropic.claude-opus-4-6-v1"
    assert kw["effort"] == "low"
    assert kw["history_count"] == 1


def test_bedrock_invoke_start_effort_none_for_legacy_path():
    """Legacy path (no thinking_level) must log effort=None."""
    from unittest.mock import patch as _patch
    client = _make_mock_client()
    with _patch("bedrock_client.logger.log") as mock_log:
        bedrock_client.invoke_chat(client, [], "hello")
    start_calls = [c for c in mock_log.call_args_list if len(c.args) >= 2 and c.args[1] == "bedrock_invoke_start"]
    assert len(start_calls) == 1
    assert start_calls[0].kwargs["effort"] is None


def test_thinking_response_with_multiple_blocks():
    """When response contains thinking + text blocks, text block is extracted."""
    client = MagicMock()
    client.converse.return_value = {
        "output": {"message": {"content": [
            {"reasoningContent": {"reasoningText": {"text": "thinking..."}}},
            {"text": "final answer"},
        ]}},
        "usage": {"inputTokens": 50, "outputTokens": 100},
        "stopReason": "end_turn",
    }
    result = bedrock_client.invoke_chat(client, [], "hello", thinking_level="high")
    assert result["content"] == "final answer"
