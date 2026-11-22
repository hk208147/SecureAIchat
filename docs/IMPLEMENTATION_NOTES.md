# Implementation Notes

Generated: 2026-11-18. Records decisions delegated to the implementer by PHASE2_IMPLEMENTATION_SPEC.md.

---

## Naming conventions

| Resource | Value |
|---|---|
| Project prefix | `personal-chat-app` |
| DynamoDB table | `personal-chat-app-chat` |
| Lambda function | `personal-chat-app-chat` |
| S3 bucket | `personal-chat-app-frontend-<account_id>` |
| Cognito user pool | `personal-chat-app-users` |
| Cognito app client | `personal-chat-app-web` |
| Cognito resource server identifier | `personal-chat-api` |
| Custom OAuth scope | `personal-chat-api/chat` |
| EMF namespace | `personal-chat-app/Chat` |
| SNS topic | `personal-chat-app-alerts` |
| CloudFront OAC | `personal-chat-app-oac` |
| Cognito domain prefix | `personal-chat-app-<account_id>` |

---

## DynamoDB schema decisions

### SK uniqueness for messages
`MSG#<ISOtimestamp>#<uuid4[:8]>` — appending an 8-char UUID hex suffix prevents SK collisions
when two messages arrive within the same millisecond.

### Session record SK (R09 schema change)
Session records use a **stable SK**: `SESSION#<session_id>` (no timestamp suffix).

Original design used `SESSION#<session_id>#<ISOtimestamp>`, but that SK was unique on every
call, so `ConditionExpression("attribute_not_exists(sk)")` always evaluated to true and could
not prevent duplicate writes. Storing the timestamp as a plain attribute and using the stable SK
enables true idempotency.

The `created_at` attribute (ISO string) is stored separately for display ordering. Sessions
are sorted by `created_at` descending in Python after the DynamoDB query.

### Session record creation
`save_session_if_new()` uses `ConditionExpression="attribute_not_exists(sk)"` with the stable SK
to ensure exactly one session record per `session_id`, even if called concurrently.

### No GSI
The spec resolved a GSI inconsistency by using the PK structure directly:
- `USER#<sub>` prefix with `SESSION#` SK range covers session listing without a GSI.
- GSI resources are absent from Terraform intentionally.

---

## HTTP API integration timeout (known constraint)

**Spec §7** says "Lambdaの60秒設定だけでHTTP APIの60秒応答を保証しない."

AWS HTTP API supports an integration timeout of at most 30 seconds. This app uses
29 seconds (`timeout_milliseconds = 29000`); Lambda retains the spec's 60-second timeout.
Setting an integration timeout does not ensure Lambda can return a controlled error first.

Bedrock uses a 25-second socket-read timeout and a 5-second connection timeout.
These are not an end-to-end deadline: connection setup, credential work, DynamoDB operations,
and response transfer all add time. No fixed DynamoDB latency is assumed.
`retries={"mode": "standard", "total_max_attempts": 1}` disables automatic SDK retries.
In a botocore Config object, `max_attempts=1` would allow ONE RETRY after the initial call;
`total_max_attempts=1` includes the initial call. A regression test exercises a synthetic
HTTP 503 through botocore and verifies that only one request is sent, without AWS access.

**Known MVP limitation**: HTTP API can return 504 while Lambda continues and saves a response.
Message writes are not idempotent. Do not automatically resend after an error. Reopen the
session to check for a saved reply before manually deciding to retry. Increasing the API
integration timeout or lowering Lambda's timeout alone does not establish idempotency.

Resolution options if 30s is insufficient (not implemented in MVP): async pattern with polling,
or streaming (Bedrock `ConverseStream` API + Lambda response streaming).

---

## CloudWatch alarm: evaluation_window not used

The Terraform AWS provider does not have an `evaluation_window` argument for
`aws_cloudwatch_metric_alarm`. HANDOVER.md flagged this as unverified (§7).

Implementation uses the standard approach:
- `period = 86400` — 86,400-second (24h) evaluation window
- `evaluation_periods = 1` — single period
- `datapoints_to_alarm = 1`

CloudWatch evaluates the last 86,400 seconds on a rolling basis (not calendar-day).
This is the SlidingWindow behavior described in the spec.

---

## Bedrock ARNs: required before deploy

Variables `bedrock_inference_profile_arn` and `bedrock_base_model_arns` have no defaults
and must be set in `terraform/terraform.tfvars` before `terraform apply`.

Verification command (requires aws login with bedrock-dev profile):
```
aws bedrock get-inference-profile \
  --inference-profile-identifier au.anthropic.claude-sonnet-4-6 \
  --region ap-southeast-2 \
  --profile bedrock-terraform
```

Expected ARN patterns (unconfirmed — verify output above):
- System-defined inference profile: `arn:aws:bedrock:ap-southeast-2::foundation-model/au.anthropic.claude-sonnet-4-6`
- Or account-scoped: `arn:aws:bedrock:ap-southeast-2:<account_id>:inference-profile/au.anthropic.claude-sonnet-4-6`
- Base model targets in Sydney (ap-southeast-2) and Melbourne (ap-southeast-4)

The IAM policy uses `concat([var.bedrock_inference_profile_arn], var.bedrock_base_model_arns)`.

---

## Cognito callback URL resolution

Cognito app client callback/logout URLs reference `aws_cloudfront_distribution.web.domain_name`
directly. This is NOT a circular dependency — CloudFront has no dependency on Cognito.
Terraform resolves the creation order correctly.

---

## Prompt caching implementation

Token estimation: `len(text) // 4` (rough chars-to-tokens ratio).
CachePoint added to:
- System content when estimated tokens ≥ 1024
- Last user message content when cumulative message tokens ≥ 1024

**Limitation**: The `len // 4` estimate is calibrated for English text (~4 chars/token).
Japanese and CJK text uses more tokens per character (~1–2 chars/token), so the estimate
may undercount and caching may not be applied even when content exceeds 1024 actual tokens.
This is a known approximation; the spec notes "常時ヒットを保証しない."

**Not guaranteed to hit on every request.** Short conversations will not use caching.
TTL is ~5 minutes per Anthropic documentation.

---

## AWS Budgets: check for existing $5 budget before deploy

The spec notes (§9): "既存の5 USD通知設定があるとの以前の記録があるため、重複はデプロイ前に確認する."

Before applying Terraform, verify existing budgets in AWS Billing console.
The two budgets Terraform creates are `personal-chat-app-warn-25` ($25) and
`personal-chat-app-critical-30` ($30). If a $5 budget already exists separately,
it does not conflict — but verify the total notification picture is as intended.

---

## Lambda environment variable: ALLOWED_SUB

After Cognito user creation, retrieve the user's `sub` from:
```
aws cognito-idp admin-get-user \
  --user-pool-id <user_pool_id> \
  --username <email> \
  --profile bedrock-terraform
```

Set in `terraform.tfvars`:
```hcl
allowed_sub = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

If `ALLOWED_SUB` is unset at runtime, the Lambda returns 403 for all requests.

---

## Frontend environment variables

Create `frontend/.env.local` (not committed to git):
```
VITE_USER_POOL_ID=ap-southeast-2_XXXXXXXXX
VITE_USER_POOL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_DOMAIN=personal-chat-app-<account_id>.auth.ap-southeast-2.amazoncognito.com
VITE_API_ENDPOINT=https://xxxxxxxxxx.execute-api.ap-southeast-2.amazonaws.com
```

**`VITE_COGNITO_DOMAIN` must be a hostname only** (no `https://` prefix).
Use `terraform output -raw cognito_domain_host` (not `cognito_login_url`) to populate it.
The frontend code validates this at startup and throws a descriptive error if a protocol prefix
is detected.

Values are available from `terraform output` after apply.

---

## Python local testing

Python 3.12 is not installed in the development environment (Microsoft Store stub only).
Tests require a real Python 3.12 installation with pytest + moto.

To run tests after installing Python:
```powershell
cd C:\Users\Hidey\AWS-Learning\lambda
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## Terraform local validation

Terraform is not installed. Validation (`terraform fmt`, `terraform validate`) requires
Terraform CLI installation. These are pre-deploy checks, not blocking for local code review.

Install: https://developer.hashicorp.com/terraform/install

---

## CloudWatch EMF metrics

The Lambda emits two custom metrics via Embedded Metrics Format (EMF):

| Metric | Unit | Description |
|---|---|---|
| `InputTokens` | Count | Bedrock input tokens per request |
| `OutputTokens` | Count | Bedrock output tokens per request |

Namespace: `personal-chat-app/Chat`, dimension: `FunctionName`.

`RequestCount` is NOT emitted as a custom metric — the built-in `AWS/Lambda Invocations`
metric already provides this at no cost.

CloudWatch alarms in `monitoring.tf` use:
- `AWS/Lambda Invocations` for the daily invocation count alarm
- `personal-chat-app/Chat OutputTokens` for the daily output token alarm

---

## ALLOWED_SUB server configuration gap

The spec requires ALLOWED_SUB to be set before the Lambda accepts any requests.
Since AWS user creation is not performed in this phase, ALLOWED_SUB remains a placeholder.
This is not a code defect — it is an expected pre-deploy configuration step documented in DEPLOY.md.
