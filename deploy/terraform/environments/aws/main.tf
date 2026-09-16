# AWS environment — realized from the existing ECS Fargate & EFS PDF spec in M6.
# Validate-only in CI (ADR-004). No provider block yet on purpose: keeps `terraform
# validate` credential-free until the module wiring lands.

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
  value       = "M0 placeholder — AWS env realized in M6 (ECS Fargate + EFS + SQS + Aurora Serverless)"
  description = "Placeholder output so validate has something to check."
}
