import os

MODEL_ID: str = os.environ.get("MODEL_ID", "au.anthropic.claude-sonnet-4-6")
DEFAULT_MODEL_ID: str = "au.anthropic.claude-sonnet-4-6"
DYNAMODB_TABLE: str = os.environ.get("DYNAMODB_TABLE", "")
ALLOWED_ORIGIN: str = os.environ.get("ALLOWED_ORIGIN", "")
ALLOWED_SUB: str | None = os.environ.get("ALLOWED_SUB")
BEDROCK_REGION: str = os.environ.get("BEDROCK_REGION", "ap-southeast-2")

MAX_TOKENS: int = int(os.environ.get("MAX_TOKENS", "4000"))
MAX_CONTEXT_MESSAGES: int = int(os.environ.get("MAX_CONTEXT_MESSAGES", "10"))
# DynamoDB items have a 400 KB size limit. Reject messages that exceed this before
# calling Bedrock so we don't burn inference budget on input that cannot be persisted.
MAX_INPUT_BYTES: int = 380_000
TTL_DAYS: int = 30
CACHE_MIN_TOKENS: int = 1024
TEMPERATURE: float = 0.7
BEDROCK_READ_TIMEOUT: int = 25  # leaves buffer before HTTP API 30s max
MESSAGES_DISPLAY_LIMIT: int = 100

EMF_NAMESPACE: str = "personal-chat-app/Chat"

# Allowed models and their supported thinking levels (effort: low/medium/high).
# Adding a model here also requires updating the IAM policy in lambda.tf.
ALLOWED_MODEL_CONFIGS: dict[str, dict] = {
    "au.anthropic.claude-sonnet-4-6": {
        "thinking_levels": ["low", "medium", "high"],
    },
    "au.anthropic.claude-opus-4-6-v1": {
        "thinking_levels": ["low", "medium", "high"],
    },
}

THINKING_LEVELS: list[str] = ["low", "medium", "high"]
