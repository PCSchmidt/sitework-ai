# Provider declaration only -- `terraform init -backend=false` + `validate` (iac-check.yaml)
# don't need real AWS credentials for this; they just resolve the provider plugin and
# type-check the config. `plan`/`apply` do need credentials and are never run in CI (ADR-004).

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
