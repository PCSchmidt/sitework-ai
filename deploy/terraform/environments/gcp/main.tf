# GCP environment: Pub/Sub + Filestore + Cloud SQL + GCS, realized from
# docs/deployment/gcp-deployment-guide.md §3 in M6. Cloud Run services and IAM
# bindings stay in that guide's §4-5 imperative `gcloud` steps by design (this
# Terraform owns the stateful/data-plane resources; service deploys are a
# separate, more frequently-changing concern better suited to `gcloud run deploy`
# than to a Terraform apply cadence) -- not a gap, a deliberate split.

locals {
  region = "us-central1"
  labels = {
    project     = "sitewatch-ai"
    managed-by  = "terraform"
    ttl         = "30d" # auto-expiry tag for cost safety
    environment = var.environment
  }
}

# Service account the Pub/Sub push subscription authenticates as (OIDC) when
# invoking the Cloud Run worker -- referenced by the guide's push_config but
# not previously defined; real gap closed here rather than left dangling.
resource "google_service_account" "run_invoker" {
  account_id   = "sitewatch-ai-run-invoker"
  display_name = "SiteWatch AI Pub/Sub -> Cloud Run push invoker"
  project      = var.project_id
}

# --- Pub/Sub: anomaly events + dead-letter topic -----------------------------
resource "google_pubsub_topic" "anomaly_dlq" {
  name    = "sitewatch-ai-anomaly-dlq"
  project = var.project_id
}

resource "google_pubsub_topic" "anomaly_events" {
  name    = "sitewatch-ai-anomaly-events"
  project = var.project_id
}

resource "google_pubsub_subscription" "anomaly_push" {
  name    = "sitewatch-ai-anomaly-push"
  topic   = google_pubsub_topic.anomaly_events.id
  project = var.project_id

  push_config {
    push_endpoint = var.worker_run_url
    oidc_token {
      service_account_email = google_service_account.run_invoker.email
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.anomaly_dlq.id
    max_delivery_attempts = 5
  }

  expiration_policy {
    ttl = "" # never expire
  }
}

# --- Filestore: persistent agent harness state (/home/node/.prime) ----------
# BASIC_HDD's 1 TiB minimum (~$180/mo) is the Filestore caveat docs/10-cost-model.md
# §4 flags -- kept as the guide specifies (smallest available tier) rather than
# silently swapped for a cheaper alternative; the cost-model doc is where that
# tradeoff is discussed, not this file.
resource "google_filestore_instance" "prime_state" {
  name     = "sitewatch-ai-prime-state"
  project  = var.project_id
  location = local.region
  tier     = "BASIC_HDD"

  file_shares {
    capacity_gb = 1024
    name        = "prime_state"
  }

  networks {
    network = "default"
    modes   = ["MODE_IPV4"]
  }
}

# --- Cloud Storage: incident clips -------------------------------------------
resource "google_storage_bucket" "incident_clips" {
  name                        = "sitewatch-ai-incident-clips"
  location                    = local.region
  uniform_bucket_level_access = true
  labels                      = local.labels

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

# --- Cloud SQL: PostgreSQL (serverless-style) --------------------------------
resource "google_sql_database_instance" "postgres" {
  name             = "sitewatch-ai-pg"
  database_version = "POSTGRES_15"
  region           = local.region
  project          = var.project_id

  settings {
    tier                        = "db-custom-1-3840" # 1 vCPU / 3.75 GB, smallest viable
    disk_size                   = 10
    disk_autoresize             = true
    availability_type           = "ZONAL"
    deletion_protection_enabled = false # reference architecture only
    user_labels                 = local.labels
  }
}
