locals {
  account_id  = data.aws_caller_identity.current.account_id
  name_prefix = var.project_name

  # Cognito domain prefix — account ID suffix ensures global uniqueness
  cognito_domain = "${local.name_prefix}-${local.account_id}"

  # S3 bucket name — globally unique
  frontend_bucket_name = "${local.name_prefix}-frontend-${local.account_id}"

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}
