# Shared Terraform modules (M6): broker, container-service, storage, db.

Modules are consumed by `environments/{aws,gcp,azure}/`. Everything here is
validate/fmt-checked in CI (`iac-check.yaml`); `terraform apply` is never run in
automation (ADR-004).
