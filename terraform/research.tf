variable "enable_research_knowledge_base" {
  description = "Create the private document bucket and a Bedrock Knowledge Base backed by S3 Vectors."
  type        = bool
  default     = false
}

variable "enable_research_web_search" {
  description = "Allow the authenticated search route to use AgentCore Web Search."
  type        = bool
  default     = false
}

variable "enable_research_rag_active" {
  description = "Pass KB/document settings to Lambda (requires enable_research_knowledge_base=true). Set to false to suspend RAG without destroying the Knowledge Base or S3 resources."
  type        = bool
  default     = false
}

data "aws_partition" "current" {}

locals {
  research_bucket     = "${local.name_prefix}-research-${local.account_id}"
  research_vector     = "${local.name_prefix}-research-vectors"
  research_vector_arn = "arn:${data.aws_partition.current.partition}:s3vectors:${var.aws_region}:${local.account_id}:bucket/${local.research_vector}"
  research_embed_arn  = "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
}

resource "aws_s3_bucket" "research" {
  count  = var.enable_research_knowledge_base ? 1 : 0
  bucket = local.research_bucket
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "research" {
  count                   = var.enable_research_knowledge_base ? 1 : 0
  bucket                  = aws_s3_bucket.research[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "research" {
  count  = var.enable_research_knowledge_base ? 1 : 0
  bucket = aws_s3_bucket.research[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_iam_role" "research_kb" {
  count = var.enable_research_knowledge_base ? 1 : 0
  name  = "${local.name_prefix}-research-kb"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}:${local.account_id}:knowledge-base/*" }
      }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "research_kb" {
  count = var.enable_research_knowledge_base ? 1 : 0
  role  = aws_iam_role.research_kb[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = local.research_embed_arn },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.research[0].arn },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.research[0].arn}/documents/*" },
      {
        Effect   = "Allow"
        Action   = ["s3vectors:GetIndex", "s3vectors:GetVectors", "s3vectors:PutVectors", "s3vectors:DeleteVectors", "s3vectors:QueryVectors", "s3vectors:ListVectors"]
        Resource = "${local.research_vector_arn}/index/research"
      },
    ]
  })
}

# Keep the existing AWS provider version. CloudFormation supplies S3 Vectors resources.
resource "aws_cloudformation_stack" "research" {
  count         = var.enable_research_knowledge_base ? 1 : 0
  name          = "${local.name_prefix}-research"
  template_body = file("${path.module}/research-stack.yaml")
  parameters = {
    VectorBucketName  = local.research_vector
    DocumentBucketArn = aws_s3_bucket.research[0].arn
    RoleArn           = aws_iam_role.research_kb[0].arn
    EmbeddingModelArn = local.research_embed_arn
  }
  depends_on = [
    aws_iam_role_policy.research_kb,
    aws_s3_bucket_public_access_block.research,
    aws_s3_bucket_server_side_encryption_configuration.research,
  ]
  tags = local.tags
}

resource "aws_iam_role_policy" "research_documents" {
  count = var.enable_research_knowledge_base ? 1 : 0
  role  = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.research[0].arn}/documents/*"
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:Retrieve", "bedrock:IngestKnowledgeBaseDocuments", "bedrock:GetKnowledgeBaseDocuments", "bedrock:DeleteKnowledgeBaseDocuments"]
        Resource = aws_cloudformation_stack.research[0].outputs["KnowledgeBaseArn"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "research_search" {
  count = var.enable_research_web_search ? 1 : 0
  role  = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock-agentcore:InvokeWebSearch"]
      Resource = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.aws_region}:aws:tool/web-search.v1"
    }]
  })
}

resource "aws_apigatewayv2_route" "research" {
  for_each = toset(concat([
    "GET /research/personas", "POST /research/personas", "DELETE /research/personas",
    "PUT /research/personas/active",
    ], var.enable_research_knowledge_base ? [
    "GET /research/documents", "POST /research/documents", "DELETE /research/documents",
    "GET /research/documents/download",
  ] : [], var.enable_research_web_search ? ["POST /research/search"] : []))

  api_id               = aws_apigatewayv2_api.chat.id
  route_key            = each.key
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.jwt.id
  authorization_scopes = ["personal-chat-api/chat"]
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}
