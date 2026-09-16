# GCP environment — realized in M6 (Cloud Run + Pub/Sub + Cloud SQL). Validate-only (ADR-004).
# NOTE: Filestore BASIC_HDD has a 1 TiB minimum (~$180/mo); the state-storage choice
# (Filestore vs GCS/gcsfuse) must be resolved here per docs/10-cost-model.md §4.

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
  value       = "M0 placeholder — GCP env realized in M6 (Cloud Run + Pub/Sub + Cloud SQL)"
  description = "Placeholder output so validate has something to check."
}
