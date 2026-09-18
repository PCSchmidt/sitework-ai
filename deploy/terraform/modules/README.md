# Shared Terraform modules

M0's placeholder for this directory assumed a `broker`/`container-service`/`storage`/`db`
module layer shared across `environments/{aws,gcp,azure}/`. Realizing those environments in
M6 (from the AWS PDF spec and the GCP/Azure deployment guides) showed that decision wasn't
right: AWS's SQS+EFS+ECS, GCP's Pub/Sub+Filestore+Cloud Run, and Azure's Service Bus+Files+
Container Apps don't share Terraform resource schemas at all -- a "broker module" would just
be three unrelated resource blocks behind one name, adding an indirection layer without
removing any real duplication. Each `environments/{aws,gcp,azure}/` directory stays flat
(`main.tf`/`variables.tf`/`outputs.tf`/`versions.tf`), matching the source specs (the PDF, and
docs/deployment/{aws,gcp,azure}-deployment-guide.md §3) directly rather than abstracting over
them speculatively.

This directory is kept (rather than deleted) as the place a real shared module would go if a
genuine cross-cloud commonality shows up later -- none has yet. Everything under
`environments/` is fmt/validate-checked in CI (`iac-check.yaml`); `terraform apply` is never
run in automation (ADR-004).
