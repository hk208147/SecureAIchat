# Budget 1: warn at $25 actual spend
# This gives early notice before the $30 target is reached.
resource "aws_budgets_budget" "warn_25" {
  name         = "${local.name_prefix}-warn-25"
  budget_type  = "COST"
  limit_amount = "25"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

# Budget 2: notify at $30 actual spend and when $30 is forecast to be reached.
# Note: check Billing > Budgets before deploy — an existing $5 budget may already exist
# for the account. Duplicate budget names within the same account are not allowed.
resource "aws_budgets_budget" "critical_30" {
  name         = "${local.name_prefix}-critical-30"
  budget_type  = "COST"
  limit_amount = "30"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
