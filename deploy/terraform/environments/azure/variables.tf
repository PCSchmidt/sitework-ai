# Azure environment -- realized from docs/deployment/azure-deployment-guide.md §3 in M6.
# ADR-004: authored + fmt/validate-checked in CI, never applied by automation.

variable "environment" {
  type        = string
  default     = "reference"
  description = "Deployment stage tag (production/staging/reference)."
}

# azurerm_postgresql_flexible_server requires admin credentials -- not shown in the
# deployment guide's illustrative HCL snippet (real gap closed here rather than left
# unresolvable); no default on the password so a real deployment can't accidentally
# apply with a placeholder.
variable "postgres_admin_login" {
  type        = string
  default     = "sitewatch_admin"
  description = "Administrator login for the PostgreSQL Flexible Server."
}

variable "postgres_admin_password" {
  type        = string
  sensitive   = true
  description = "Administrator password for the PostgreSQL Flexible Server -- set via TF_VAR_postgres_admin_password or a real secrets backend, never committed."
}
