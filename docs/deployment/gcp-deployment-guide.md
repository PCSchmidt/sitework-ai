# SiteWatch AI — GCP Deployment Guide (Deployable Reference Architecture)

> **Scope statement.** SiteWatch AI is a portfolio project; this is deployable reference
> architecture documentation for Google Cloud. No live deployment is performed. All
> `terraform apply` commands are intentionally commented out.

The FAST PATH (TensorRT inference, ByteTrack, homography, geofencing) runs on-prem
at the edge. This guide covers only the SLOW PATH (Prime Agent reasoning worker),
delivery plane (FastAPI + React), and persistence.

## 1. Architecture Mapping

| Component | Architecture Role | Cloud Primitive | Operational Role |
|---|---|---|---|
| Anomaly event bus | FAST PATH trigger events consumed by SLOW PATH | Pub/Sub topic + push subscription | Edge publisher emits JSON trigger events; Cloud Run worker receives pushes |
| Failed-event isolation | DLQ for poison / undecodable anomaly events | Pub/Sub dead-letter topic + retry policy | Events failing N delivery attempts route to `sitewatch-ai-anomaly-dlq` |
| Reasoning worker | SLOW PATH: kinematic verification, OSHA compliance correlation, shift reports | Cloud Run (v2) service | Dockerized Prime Agent supervisor + headless IPython REPL, RLM sub-agents |
| Agent harness state | Persistent memory / prompt notes / skills for the agent runtime | Filestore (NFS) instance | NFS volume mounted read-write at `/home/node/.prime` in the worker container |
| Incident clips | Video evidence retained per incident | Cloud Storage (standard, regional) | Edge uploader puts MP4 clips; FastAPI backend serves signed URLs |
| Incident / telemetry DB | Structured incidents, tracklets, shift reports | Cloud SQL for PostgreSQL | System of record for the delivery plane; queried by FastAPI |
| FastAPI + React | Delivery plane REST API and operator dashboard | Cloud Run (v2) service + static hosting | Serves incident data, signed clip URLs, and compliance summaries |
| GPU edge (optional) | Hosted variant of the FAST PATH for lab / demo sites | GKE Autopilot (g2 nodes, L4 GPU) | Alternative to on-prem edge; TensorRT inference via Triton on Autopilot |

## 2. Prerequisites

```bash
# CLI versions (minimum): gcloud >= 476.0 | terraform >= 1.7 | docker >= 24
gcloud --version && terraform --version && docker --version

# Authenticate and set project context
gcloud auth login
gcloud config set project sitewatch-ai-prod
gcloud auth application-default login

# Enable required APIs
gcloud services enable run.googleapis.com pubsub.googleapis.com file.googleapis.com \
  storage.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
  iam.googleapis.com
```

## 3. Infrastructure Provisioning

Terraform root: `deploy/terraform/environments/gcp`; CI runs `terraform fmt -check` and `terraform validate` on every push.

```hcl
# deploy/terraform/environments/gcp/main.tf
locals {
  region     = "us-central1"
  project_id = "sitewatch-ai-prod"
  labels = { project = "sitewatch-ai", managed-by = "terraform",
             ttl = "30d", environment = "reference" }  # ttl = auto-expiry tag
}

# Service account the push subscription below authenticates as (OIDC) -- real
# resource this guide referenced without defining until `terraform validate`
# caught the dangling reference.
resource "google_service_account" "run_invoker" {
  account_id   = "sitewatch-ai-run-invoker"
  display_name = "SiteWatch AI Pub/Sub -> Cloud Run push invoker"
  project      = local.project_id
}

# --- Pub/Sub: anomaly events + dead-letter topic -----------------------------
resource "google_pubsub_topic" "anomaly_dlq" {
  name    = "sitewatch-ai-anomaly-dlq"
  project = local.project_id
}

resource "google_pubsub_topic" "anomaly_events" {
  name    = "sitewatch-ai-anomaly-events"
  project = local.project_id
}

resource "google_pubsub_subscription" "anomaly_push" {
  name    = "sitewatch-ai-anomaly-push"
  topic   = google_pubsub_topic.anomaly_events.id
  project = local.project_id

  push_config {
    push_endpoint = "https://sitewatch-ai-worker-abc123-uc.a.run.app/pubsub/push"
    oidc_token { service_account_email = google_service_account.run_invoker.email }
  }

  retry_policy { minimum_backoff = "10s", maximum_backoff = "600s" }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.anomaly_dlq.id
    max_delivery_attempts = 5
  }

  expiration_policy { ttl = "" }   # never expire
}

# --- Filestore: persistent agent harness state (/home/node/.prime) ----------------
resource "google_filestore_instance" "prime_state" {
  name     = "sitewatch-ai-prime-state"
  project  = local.project_id
  location = local.region
  tier     = "BASIC_HDD"   # smallest tier; BASIC_SSD if latency matters
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
    condition { age = 90 }
    action { type = "Delete" }
  }
}

# --- Cloud SQL: PostgreSQL (serverless-style) --------------------------------
resource "google_sql_database_instance" "postgres" {
  name             = "sitewatch-ai-pg"
  database_version = "POSTGRES_15"
  region           = local.region
  settings {
    tier                        = "db-custom-1-3840"  # 1 vCPU / 3.75 GB, smallest viable
    disk_size                   = 10
    disk_autoresize             = true
    availability_type           = "ZONAL"
    deletion_protection_enabled = false    # reference architecture only
    labels                      = local.labels
  }
}
```

```bash
cd deploy/terraform/environments/gcp
terraform init
terraform fmt -check
terraform validate

# REVIEW ONLY — expected output: 9 to add, 0 to change, 0 to destroy.
terraform plan -out=tfplan

# ┌────────────────────────────  ⚠️  COST WARNING  ────────────────────────────┐
# │ Running this plan incurs ~$180–$260/month: Filestore 1 TB (~$180),        │
# │ Cloud SQL (~$50), Cloud Run + Pub/Sub (~$5). Do NOT run the command       │
# │ below unless you accept that burn. Budget alerts are preconfigured.       │
# └────────────────────────────────────────────────────────────────────────────┘
# terraform apply tfplan
```

## 4. Container Image Publication

```bash
# Artifact Registry repository
gcloud artifacts repositories create sitewatch-ai \
  --repository-format=docker --location=us-central1 \
  --description="SiteWatch AI slow-path worker images"

AR_HOST=us-central1-docker.pkg.dev
gcloud auth configure-docker ${AR_HOST}
W=${AR_HOST}/sitewatch-ai-prod/sitewatch-ai
docker build -t ${W}/worker:0.1.0 ./services/reasoning-worker   # Prime Agent slow path
docker push  ${W}/worker:0.1.0
docker build -t ${W}/backend:0.1.0 ./services/backend           # FastAPI delivery plane
docker push  ${W}/backend:0.1.0
```

## 5. Secrets & Identity

```bash
# LLM provider API key (injected at runtime, never baked into images)
gcloud secrets create sitewatch-ai-llm-api-key --replication-policy=automatic
echo -n "sk-REDACTED" | gcloud secrets versions add sitewatch-ai-llm-api-key --data-file=-
```

Least-privilege service accounts:

```bash
# 1. Worker runtime: Pub/Sub consumer + storage writer only
gcloud iam service-accounts create sitewatch-ai-worker --display-name="SiteWatch AI slow-path worker"
gcloud pubsub topics add-iam-policy-binding sitewatch-ai-anomaly-events \
  --member="serviceAccount:sitewatch-ai-worker@sitewatch-ai-prod.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
gcloud storage buckets add-iam-policy-binding gs://sitewatch-ai-incident-clips \
  --member="serviceAccount:sitewatch-ai-worker@sitewatch-ai-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
# 2. Push invoker: may ONLY invoke the Cloud Run service
gcloud run services add-iam-policy-binding sitewatch-ai-worker \
  --member="serviceAccount:sitewatch-ai-run-invoker@sitewatch-ai-prod.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# 3. Backend: Cloud SQL client only
gcloud iam service-accounts add-iam-policy-binding \
  sitewatch-ai-backend@sitewatch-ai-prod.iam.gserviceaccount.com \
  --role="roles/cloudsql.client" --project=sitewatch-ai-prod

# 4. Filestore access is network-layer enforced; grant roles/file.editor to the provisioning SA only.
```

## 6. Smoke Test

Inject a synthetic anomaly event and verify the full SLOW PATH response.

```bash
# 1. Publish a synthetic geofence-intrusion trigger (matches FAST PATH schema)
gcloud pubsub topics publish sitewatch-ai-anomaly-events --message='{
  "event_id": "smoke-001", "event_type": "geofence_intrusion",
  "camera_id": "cam-east-gate", "tracklet_id": "tk-4471",
  "ground_coords_m": {"x": 12.4, "y": 8.1}, "velocity_ms": 1.6,
  "zone": "forklift_lane_b", "ts": "2026-01-15T09:30:02Z"
}'

# 2. Confirm the push subscription delivered it (no DLQ accumulation)
gcloud pubsub subscriptions describe sitewatch-ai-anomaly-push \
  --format="value(numUndeliveredMessages)"

# 3. Check the worker logs for the expected agent pipeline stages
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="sitewatch-ai-worker"' \
  --limit=20 --format="value(textPayload)"
```

Expected agent incident response, in order:

1. Event decoded and accepted; JSON schema validation passes.
2. Kinematic verification: trajectory replay confirms sustained intrusion (velocity and
   ground-plane path consistent with the trigger).
3. OSHA-style compliance correlation: maps `forklift_lane_b` intrusion to powered-industrial-truck
   clearance rules; severity assigned.
4. Incident record inserted into Cloud SQL; clip reference resolved from `gs://sitewatch-ai-incident-clips`.
5. Shift-report synthesis updated; harness memory note written to `/home/node/.prime`.
6. Smoke event visible on the dashboard at `/incidents/smoke-001`.

Pass criteria: `numUndeliveredMessages == 0`, DLQ empty, one incident row, and
all six stages present in logs within 120 seconds.

## 7. Teardown & Cost Safety

```bash
# Budget alerts at $5 and $15 (do this BEFORE any apply)
BA=$(gcloud billing projects describe sitewatch-ai-prod \
    --format="value(billingAccountName)" | cut -d/ -f2)
gcloud billing budgets create --billing-account=${BA} \
  --display-name="sitewatch-ai-5usd" --budget-amount=5USD \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9
gcloud billing budgets create --billing-account=${BA} \
  --display-name="sitewatch-ai-15usd" --budget-amount=15USD

# Destructive teardown — reference environments only
# terraform destroy -target=google_filestore_instance.prime_state   # ~$180/mo — first
# terraform destroy -target=google_sql_database_instance.postgres   # ~$50/mo  — second
# terraform destroy                                                  # remainder

# Manual fallbacks if Terraform state is unavailable
# gcloud sql instances delete sitewatch-ai-pg
# gcloud filestore instances delete sitewatch-ai-prime-state --zone=us-central1-b
```

Cost-safety rules:

- Every labeled resource carries `ttl = "30d"`; a weekly job flags stale labels.
- `deletion_protection` is `false` on Cloud SQL (reference only); re-enable for real deployments.
- `terraform apply` stays commented out in CI and here; CI runs `terraform fmt -check` + `terraform validate` only.
- GKE Autopilot (GPU edge alternative) bills per-pod-second on L4 nodes; keep `minReplicas: 0` except during demos.
