resource "aws_iam_role" "lambda_exec" {
  name = "${local.name_prefix}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${local.name_prefix}-lambda-policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        # Scoped to the specific log group created below
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:Query",
          "dynamodb:ConditionCheckItem",
        ]
        # Table ARN only — no GSI, so no /index/* required
        Resource = aws_dynamodb_table.chat.arn
      },
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
        ]
        # Inference profile ARNs + all base model ARNs that each profile routes to.
        # All variables must be set in terraform.tfvars before apply.
        Resource = concat(
          [var.bedrock_inference_profile_arn],
          var.bedrock_base_model_arns,
          length(var.bedrock_opus46_inference_profile_arn) > 0 ? [var.bedrock_opus46_inference_profile_arn] : [],
          var.bedrock_opus46_base_model_arns,
        )
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name_prefix}-chat"
  retention_in_days = 7
  tags              = local.tags
}

# Build Lambda zip from source directory (excludes tests and build artifacts)
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/../dist/lambda.zip"
  excludes = [
    "tests",
    "__pycache__",
    "*.pyc",
    "requirements.txt",
    "requirements-dev.txt",
  ]
}

resource "aws_lambda_function" "chat" {
  function_name    = "${local.name_prefix}-chat"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "chat_handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = 60 # HTTP API integration timeout is 30s max — see docs/IMPLEMENTATION_NOTES.md
  memory_size      = 512

  # Use account shared concurrency pool; throttling enforced by API Gateway rate/burst limits
  reserved_concurrent_executions = -1

  environment {
    variables = {
      DYNAMODB_TABLE           = aws_dynamodb_table.chat.name
      ALLOWED_ORIGIN           = "https://${aws_cloudfront_distribution.web.domain_name}"
      MODEL_ID                 = "au.anthropic.claude-sonnet-4-6"
      BEDROCK_REGION           = var.aws_region
      MAX_TOKENS               = "4000"
      MAX_CONTEXT_MESSAGES     = "10"
      ALLOWED_SUB              = var.allowed_sub
      CHAT_FILES_BUCKET        = aws_s3_bucket.chat_files.id
      RESEARCH_DOCUMENT_BUCKET = (var.enable_research_knowledge_base && var.enable_research_rag_active) ? aws_s3_bucket.research[0].id : ""
      RESEARCH_KB_ID           = (var.enable_research_knowledge_base && var.enable_research_rag_active) ? aws_cloudformation_stack.research[0].outputs["KnowledgeBaseId"] : ""
      RESEARCH_DATA_SOURCE_ID  = (var.enable_research_knowledge_base && var.enable_research_rag_active) ? aws_cloudformation_stack.research[0].outputs["DataSourceId"] : ""
      RESEARCH_WEB_SEARCH      = tostring(var.enable_research_web_search)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_policy,
    aws_iam_role_policy.chat_files,
  ]

  tags = local.tags
}
