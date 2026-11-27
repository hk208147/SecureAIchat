resource "aws_cloudwatch_log_group" "history_files_cleanup" {
  name              = "/aws/lambda/${local.name_prefix}-history-files-cleanup"
  retention_in_days = 7
  tags              = local.tags
}

resource "aws_iam_role" "history_files_cleanup" {
  name = "${local.name_prefix}-history-files-cleanup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "history_files_cleanup" {
  role = aws_iam_role.history_files_cleanup.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.history_files_cleanup.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Query", "dynamodb:DeleteItem"]
        Resource = aws_dynamodb_table.chat.arn
        Condition = {
          "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["CHAT_FILE_RETENTION"] }
        }
      },
      {
        Effect   = "Allow"
        Action   = "s3:DeleteObject"
        Resource = "${aws_s3_bucket.chat_files.arn}/history/*"
      },
    ]
  })
}

resource "aws_lambda_function" "history_files_cleanup" {
  function_name    = "${local.name_prefix}-history-files-cleanup"
  role             = aws_iam_role.history_files_cleanup.arn
  handler          = "history_files.scheduled_cleanup"
  runtime          = aws_lambda_function.chat.runtime
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = 60
  environment {
    variables = {
      DYNAMODB_TABLE    = aws_dynamodb_table.chat.name
      CHAT_FILES_BUCKET = aws_s3_bucket.chat_files.bucket
    }
  }
  depends_on = [aws_iam_role_policy.history_files_cleanup]
  tags       = local.tags
}

resource "aws_cloudwatch_event_rule" "history_files_cleanup" {
  name                = "${local.name_prefix}-history-files-cleanup"
  schedule_expression = "rate(5 minutes)"
  tags                = local.tags
}

resource "aws_lambda_permission" "history_files_cleanup" {
  statement_id  = "AllowAttachmentCleanupSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.history_files_cleanup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.history_files_cleanup.arn
}

resource "aws_cloudwatch_event_target" "history_files_cleanup" {
  rule       = aws_cloudwatch_event_rule.history_files_cleanup.name
  arn        = aws_lambda_function.history_files_cleanup.arn
  depends_on = [aws_lambda_permission.history_files_cleanup]
}
