output "cloudfront_domain" {
  description = "CloudFront domain name for the web app (use as the app URL)"
  value       = aws_cloudfront_distribution.web.domain_name
}

output "api_endpoint" {
  description = "HTTP API base URL — append /chat or /sessions"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID — needed for admin-create-user and sub lookup"
  value       = aws_cognito_user_pool.main.id
}

output "cognito_app_client_id" {
  description = "Cognito App Client ID — needed for frontend VITE_USER_POOL_CLIENT_ID"
  value       = aws_cognito_user_pool_client.web.id
}

output "cognito_login_url" {
  description = "Cognito Managed Login base URL — base for OAuth authorize endpoint"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "cognito_domain_host" {
  description = "Cognito Managed Login hostname only (no https://) — use as VITE_COGNITO_DOMAIN in Amplify config"
  value       = "${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "frontend_bucket_name" {
  description = "S3 bucket name for frontend static files — target for 'aws s3 sync dist/ s3://...'"
  value       = aws_s3_bucket.frontend.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID — needed for cache invalidation after deploy"
  value       = aws_cloudfront_distribution.web.id
}

output "dynamodb_table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.chat.name
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.chat.function_name
}
