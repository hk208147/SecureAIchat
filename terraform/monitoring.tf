resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  tags = local.tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Rolling 24-hour request count alarm.
# CloudWatch evaluates period=86400 as a sliding window (not a calendar day):
# at each evaluation interval the alarm checks the sum of the last 86,400 seconds.
# This matches the spec's "ローリング24時間" requirement.
# Note: evaluation_window is not a valid aws_cloudwatch_metric_alarm argument —
# the rolling behaviour is achieved by period=86400 with evaluation_periods=1.
resource "aws_cloudwatch_metric_alarm" "daily_requests" {
  alarm_name          = "${local.name_prefix}-daily-requests"
  alarm_description   = "Lambda invocations >= ${var.daily_request_threshold} in rolling 24h"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "Invocations"
  namespace           = "AWS/Lambda"
  period              = 86400
  statistic           = "Sum"
  threshold           = var.daily_request_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.chat.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = local.tags
}

# Rolling 24-hour output token alarm using the custom EMF metric emitted by Lambda.
# EMF namespace and metric name must match what lambda/metrics.py publishes.
resource "aws_cloudwatch_metric_alarm" "daily_output_tokens" {
  alarm_name          = "${local.name_prefix}-daily-output-tokens"
  alarm_description   = "Output tokens >= ${var.daily_token_threshold} in rolling 24h"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "OutputTokens"
  namespace           = "personal-chat-app/Chat"
  period              = 86400
  statistic           = "Sum"
  threshold           = var.daily_token_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.chat.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = local.tags
}
