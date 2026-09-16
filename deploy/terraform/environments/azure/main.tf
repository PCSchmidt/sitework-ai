# Azure environment — realized in M6 (Container Apps + Service Bus + PostgreSQL Flexible).
# Validate-only in CI (ADR-004). No provider block yet on purpose.

terraform {
  required_version = ">= 1.6"
}

variable "project" {
  type    = string
  default = "sitewatch-ai"
}

variable "environment" {
  type    = string
  default = "reference"
}

output "status" {
  value       = "M0 placeholder — Azure env realized in M6 (Container Apps + Service Bus + PG Flexible)"
  description = "Placeholder output so validate has something to check."
}
