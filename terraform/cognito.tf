resource "aws_cognito_user_pool" "main" {
  name           = "${local.name_prefix}-users"
  user_pool_tier = "ESSENTIALS"

  # Self-signup disabled — only admin can create users
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # TOTP MFA required; SMS not used
  mfa_configuration = "ON"
  software_token_mfa_configuration {
    enabled = true
  }

  # Password policy
  password_policy {
    minimum_length                   = 8
    require_uppercase                = true
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 1
  }

  # Account recovery via email only
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # No Advanced Security Features (paid tier — excluded per spec)

  tags = local.tags
}

# Managed Login domain — version 2 enables the new Managed Login UI (Essentials)
resource "aws_cognito_user_pool_domain" "main" {
  domain                = local.cognito_domain
  user_pool_id          = aws_cognito_user_pool.main.id
  managed_login_version = 2
}

# API-created app clients need an explicit branding style, even with defaults.
resource "aws_cognito_managed_login_branding" "web" {
  client_id                   = aws_cognito_user_pool_client.web.id
  user_pool_id                = aws_cognito_user_pool.main.id
  use_cognito_provided_values = true

  depends_on = [aws_cognito_user_pool_domain.main]
}

# Resource server that owns the custom chat scope
resource "aws_cognito_resource_server" "api" {
  identifier   = "personal-chat-api"
  name         = "Personal Chat API"
  user_pool_id = aws_cognito_user_pool.main.id

  scope {
    scope_name        = "chat"
    scope_description = "Access to chat endpoint"
  }
}

# SPA app client — no secret, Authorization Code + PKCE
resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name_prefix}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Token validity
  access_token_validity  = 60 # minutes
  id_token_validity      = 60 # minutes
  refresh_token_validity = 7  # days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # OAuth: Authorization Code flow with Managed Login
  allowed_oauth_flows_user_pool_client = true
  supported_identity_providers         = ["COGNITO"]
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes = [
    "openid",
    "email",
    "profile",
    "personal-chat-api/chat",
  ]

  # Callback and logout URLs derived from CloudFront distribution.
  # Terraform resolves the dependency: CloudFront has no dependency on Cognito,
  # so it is provisioned first and its domain_name is available here.
  callback_urls = ["https://${aws_cloudfront_distribution.web.domain_name}/callback"]
  logout_urls   = ["https://${aws_cloudfront_distribution.web.domain_name}/logout"]

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"

  # Resource server must exist before the client references its scope
  depends_on = [aws_cognito_resource_server.api]
}
