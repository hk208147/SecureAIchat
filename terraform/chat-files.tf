resource "aws_s3_bucket" "chat_files" {
  bucket = "${local.name_prefix}-chat-files-${local.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "chat_files" {
  bucket                  = aws_s3_bucket.chat_files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "chat_files" {
  bucket = aws_s3_bucket.chat_files.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "chat_files" {
  bucket = aws_s3_bucket.chat_files.id
  cors_rule {
    allowed_origins = ["https://${aws_cloudfront_distribution.web.domain_name}"]
    allowed_methods = ["POST"]
    allowed_headers = ["Content-Type"]
    max_age_seconds = 300
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "chat_files" {
  bucket = aws_s3_bucket.chat_files.id

  rule {
    id     = "expire-staging"
    status = "Enabled"
    filter {
      prefix = "staging/"
    }
    expiration {
      days = 1
    }
  }

  rule {
    id     = "expire-temporary"
    status = "Enabled"
    filter {
      prefix = "temporary/"
    }
    expiration {
      days = 1
    }
  }
}

resource "aws_iam_role_policy" "chat_files" {
  name = "${local.name_prefix}-chat-files"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = aws_s3_bucket.chat_files.arn
        Condition = { StringLike = { "s3:prefix" = "saved/*" } }
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.chat_files.arn}/staging/*",
          "${aws_s3_bucket.chat_files.arn}/temporary/*",
          "${aws_s3_bucket.chat_files.arn}/saved/*",
          "${aws_s3_bucket.chat_files.arn}/history/*",
        ]
      },
      {
        Effect = "Allow"
        Action = ["s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.chat_files.arn}/saved/*",
          "${aws_s3_bucket.chat_files.arn}/staging/*",
          "${aws_s3_bucket.chat_files.arn}/temporary/*",
          "${aws_s3_bucket.chat_files.arn}/history/*",
        ]
      }
    ]
  })
}

resource "aws_apigatewayv2_route" "chat_files" {
  for_each = toset([
    "GET /research/projects", "POST /research/projects", "PUT /research/projects",
    "POST /research/files/import", "GET /research/files/history",
    "GET /research/files", "DELETE /research/files",
    "POST /research/files/upload", "POST /research/files/complete",
  ])

  api_id               = aws_apigatewayv2_api.chat.id
  route_key            = each.key
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.jwt.id
  authorization_scopes = ["personal-chat-api/chat"]
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}
