# GCP environment -- realized from docs/deployment/gcp-deployment-guide.md §3 in M6.
# ADR-004: authored + fmt/validate-checked in CI, never applied by automation.

variable "project_id" {
  type        = string
  default     = "sitewatch-ai-prod"
  description = "GCP project ID."
}

variable "environment" {
  type        = string
  default     = "reference"
  description = "Deployment stage tag (production/staging/reference)."
}

variable "worker_run_url" {
  type        = string
  default     = "https://sitewatch-ai-worker-abc123-uc.a.run.app/pubsub/push"
  description = "Cloud Run push endpoint for the anomaly-events subscription -- fill in with the real service URL after the worker's first `gcloud run deploy` (the guide's §4/§5 imperative steps; not managed by this Terraform)."
}
