import config
import logger


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _build_system(system_text: str) -> list[dict]:
    parts: list[dict] = [{"text": system_text}]
    if _estimate_tokens(system_text) >= config.CACHE_MIN_TOKENS:
        parts.append({"cachePoint": {"type": "default"}})
    return parts


def _build_messages(history: list[dict], user_message: str) -> list[dict]:
    messages: list[dict] = []
    for entry in history:
        messages.append({"role": entry["role"], "content": [{"text": entry["content"]}]})

    cumulative = sum(_estimate_tokens(m["content"][0]["text"]) for m in messages)
    cumulative += _estimate_tokens(user_message)

    user_content: list[dict] = [{"text": user_message}]
    if cumulative >= config.CACHE_MIN_TOKENS:
        user_content.append({"cachePoint": {"type": "default"}})

    messages.append({"role": "user", "content": user_content})
    return messages


_SYSTEM_TEXT = (
    "あなたは個人専用AIアシスタントです。"
    "ユーザーの質問に丁寧かつ正確に回答してください。"
    "回答は明確にまとめ、必要に応じて詳細を提供してください。"
)


def invoke_chat(
    client,
    history: list[dict],
    user_message: str,
    system_text: str = _SYSTEM_TEXT,
    model_id: str | None = None,
    thinking_level: str | None = None,
) -> dict:
    resolved_model = model_id if model_id is not None else config.MODEL_ID
    system = _build_system(system_text)
    messages = _build_messages(history, user_message)

    inference_config: dict = {"maxTokens": config.MAX_TOKENS}
    additional_fields: dict | None = None

    if thinking_level is not None:
        # Adaptive thinking: effort controls depth; temperature must not be set.
        additional_fields = {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": thinking_level},
        }
    else:
        # Legacy path: original behavior preserved.
        inference_config["temperature"] = config.TEMPERATURE

    kwargs: dict = {
        "modelId": resolved_model,
        "system": system,
        "messages": messages,
        "inferenceConfig": inference_config,
    }
    if additional_fields is not None:
        kwargs["additionalModelRequestFields"] = additional_fields

    logger.log(
        "INFO", "bedrock_invoke_start",
        model_id=kwargs["modelId"],
        effort=kwargs.get("additionalModelRequestFields", {}).get("output_config", {}).get("effort"),
        history_count=len(history),
    )
    response = client.converse(**kwargs)

    # Extract the text block; thinking-enabled responses include additional block types.
    content_blocks = response["output"]["message"]["content"]
    content = next((block["text"] for block in content_blocks if "text" in block), "")

    input_tokens: int = response["usage"]["inputTokens"]
    output_tokens: int = response["usage"]["outputTokens"]
    stop_reason: str = response.get("stopReason", "end_turn")

    return {
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "stop_reason": stop_reason,
        "model_used": resolved_model,
    }
