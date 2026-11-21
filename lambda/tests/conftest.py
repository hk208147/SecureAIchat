import sys
import os

# Add lambda/ source directory to path so tests can import directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set required env vars before any lambda module is imported
os.environ.setdefault("DYNAMODB_TABLE", "test-table")
os.environ.setdefault("ALLOWED_ORIGIN", "https://example.cloudfront.net")
os.environ.setdefault("ALLOWED_SUB", "test-sub-123")
os.environ.setdefault("MODEL_ID", "au.anthropic.claude-sonnet-4-6")
os.environ.setdefault("BEDROCK_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
