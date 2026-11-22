variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Project name used as a prefix for all resource names"
  type        = string
  default     = "personal-chat-app"
}

variable "alert_email" {
  description = "Email address for cost and usage alert notifications (SNS + Budgets)"
  type        = string
}

variable "allowed_sub" {
  description = "Cognito sub of the sole authorized user. Set this after creating the user via admin-create-user. Lambda rejects all other subs."
  type        = string
  sensitive   = true
}

variable "daily_request_threshold" {
  description = "Lambda invocation count in a rolling 24-hour window that triggers a warning alert"
  type        = number
  default     = 30
}

variable "daily_token_threshold" {
  description = "Output token count in a rolling 24-hour window that triggers a warning alert"
  type        = number
  default     = 30000
}

variable "bedrock_inference_profile_arn" {
  description = <<-EOT
    ARN of the Bedrock AU cross-region inference profile for au.anthropic.claude-sonnet-4-6.
    TODO: Verify the exact ARN before terraform apply by running:
      aws bedrock get-inference-profile \
        --inference-profile-identifier au.anthropic.claude-sonnet-4-6 \
        --region ap-southeast-2 \
        --profile bedrock-terraform
  EOT
  type        = string
}

variable "bedrock_base_model_arns" {
  description = <<-EOT
    ARNs of the Bedrock foundation models that the AU cross-region inference profile routes to.
    The AU profile routes across Sydney (ap-southeast-2) and Melbourne (ap-southeast-4).
    TODO: Verify the exact ARNs before terraform apply by running:
      aws bedrock list-foundation-models --region ap-southeast-2 --profile bedrock-terraform
      aws bedrock list-foundation-models --region ap-southeast-4 --profile bedrock-terraform
  EOT
  type        = list(string)
}

variable "bedrock_opus46_inference_profile_arn" {
  description = "ARN of the Bedrock AU cross-region inference profile for au.anthropic.claude-opus-4-6-v1."
  type        = string
  default     = ""
}

variable "bedrock_opus46_base_model_arns" {
  description = "ARNs of the base models that the AU Opus 4.6 cross-region inference profile routes to."
  type        = list(string)
  default     = []
}
