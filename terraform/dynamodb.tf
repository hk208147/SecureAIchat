resource "aws_dynamodb_table" "chat" {
  name         = "${local.name_prefix}-chat"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  server_side_encryption {
    enabled = true # AWS-managed key (SSE-S3 equivalent for DynamoDB)
  }

  # PITR disabled per spec (cost saving — excluded from MVP)
  point_in_time_recovery {
    enabled = false
  }

  # No GSI — session listing uses pk query on USER#<sub> prefix

  tags = local.tags
}
