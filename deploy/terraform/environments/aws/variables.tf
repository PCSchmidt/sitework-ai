# AWS environment -- realized from "SiteWatch AI - AWS ECS Fargate & EFS Terraform
# Configuration.pdf" (repo root) in M6. See docs/adr/ADR-004: this is authored and
# fmt/validate-checked in CI, never applied by automation. A real deployment fills in
# terraform.tfvars.example with a real VPC/subnets/ECR image and runs `terraform plan`
# by hand (docs/deployment/aws-deployment-guide.md has the runbook).

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS deployment region."
}

variable "environment" {
  type        = string
  default     = "reference"
  description = "Deployment stage tag (production/staging/reference)."
}

variable "project_name" {
  type        = string
  default     = "sitewatch-ai"
  description = "Base naming prefix for all resources."
}

variable "vpc_id" {
  type        = string
  description = "Target VPC ID where Fargate and EFS will reside."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "List of private subnet IDs with egress to internet or VPC endpoints."
}

variable "agent_image_uri" {
  type        = string
  description = "ECR URI of the containerized agent worker image (docker/Dockerfile.agent), e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/sitewatch-agent:latest."
}

variable "cpu" {
  type        = number
  default     = 1024
  description = "Fargate CPU units (1024 = 1 vCPU)."
}

variable "memory" {
  type        = number
  default     = 2048
  description = "Fargate memory limit in MiB (2048 = 2 GB)."
}

variable "db_master_username" {
  type        = string
  default     = "sitewatch_admin"
  description = "Master username for the Aurora Serverless v2 cluster."
}

variable "db_master_password" {
  type        = string
  sensitive   = true
  description = "Master password for the Aurora Serverless v2 cluster -- set via TF_VAR_db_master_password or a real secrets backend, never committed."
}
