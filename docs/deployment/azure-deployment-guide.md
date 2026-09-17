# SiteWatch AI — Azure Deployment Guide (Deployable Reference Architecture)

> **Scope statement.** SiteWatch AI is a portfolio project; this is deployable reference
> architecture documentation for Microsoft Azure. No live deployment is performed; all
> `terraform apply` commands are intentionally commented out.

The FAST PATH (TensorRT inference, ByteTrack, homography, Shapely geofencing) runs
on-prem at the edge. This guide covers only the SLOW PATH (Prime Agent reasoning
worker), delivery plane (FastAPI + React), and persistence.

## 1. Architecture Mapping

| Component | Architecture Role | Cloud Primitive | Operational Role |
|---|---|---|---|
| Anomaly event bus | FAST PATH trigger events consumed by SLOW PATH | Azure Service Bus queue (Standard tier) | Edge publisher sends JSON trigger events; Container Apps worker consumes |
| Failed-event isolation | DLQ for poison / undecodable anomaly events | Service Bus dead-letter subqueue | Messages exceeding `maxDeliveryCount` move to `$DeadLetterQueue` |
| Reasoning worker | SLOW PATH: kinematic verification, OSHA compliance correlation, shift reports | Azure Container Apps (scale on queue length via KEDA) | Dockerized Prime Agent supervisor + headless IPython REPL, RLM sub-agents |
| Agent harness state | Persistent memory / prompt notes / skills for the agent runtime | Azure Files NFS share (Premium, `Premium_ZRS`) | NFS volume mounted read-write at `/home/node/.prime` in the worker container |
| Incident clips | Video evidence retained per incident | Blob Storage (Cool tier, lifecycle delete at 90d) | Edge uploader puts MP4 clips; FastAPI backend serves SAS URLs |
| Incident / telemetry DB | Structured incidents, tracklets, shift reports | Azure Database for PostgreSQL Flexible Server | System of record for the delivery plane; queried by FastAPI |
| FastAPI + React | Delivery plane REST API and operator dashboard | Container Apps + static web hosting | Serves incident data, SAS clip URLs, and compliance summaries |
| GPU edge (optional) | Hosted variant of the FAST PATH for lab / demo sites | Azure IoT Edge on GPU-capable devices | Alternative to on-prem edge; deploys TensorRT inference modules fleet-wide |

## 2. Prerequisites

```bash
# CLI versions (minimum): az >= 2.60 | terraform >= 1.7 | docker >= 24
az version && terraform --version && docker --version
# Authenticate and set subscription context
az login
az account set --subscription "sitewatch-ai-reference"
# Register resource providers
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.ServiceBus
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.DBforPostgreSQL
az provider register --namespace Microsoft.ContainerRegistry
```

## 3. Infrastructure Provisioning

Terraform root: `deploy/terraform/environments/azure`; CI runs `terraform fmt -check` and `terraform validate` on every push.

```hcl
# deploy/terraform/environments/azure/main.tf
locals {
  location = "eastus"
  rg_name  = "rg-sitewatch-ai"
  tags = {
    project     = "sitewatch-ai"
    managed-by  = "terraform"
    ttl         = "30d"          # auto-expiry tag for cost safety
    environment = "reference"
  }
}

resource "azurerm_resource_group" "rg" {
  name     = local.rg_name
  location = local.location
  tags     = local.tags
}

# --- Service Bus: anomaly events queue + dead-letter subqueue ----------------
resource "azurerm_servicebus_namespace" "sb" {
  name                = "sitewatch-ai-sb"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_servicebus_queue" "anomaly_events" {
  name         = "sitewatch-ai-anomaly-events"
  namespace_id = azurerm_servicebus_namespace.sb.id

  max_delivery_count   = 5     # then -> dead-letter subqueue
  dead_lettering_on_message_expiration = true
  default_message_ttl  = "P7D"
}

# --- Azure Files NFS (Premium): persistent agent harness state (/home/node/.prime)
resource "azurerm_storage_account" "prime_state" {
  name                     = "stsitewatchaiprime"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Premium"
  account_replication_type = "ZRS"
  account_kind             = "FileStorage"
  tags                     = local.tags
}

resource "azurerm_storage_share" "prime_state" {
  name                 = "prime-state"   # mounted at /home/node/.prime
  storage_account_name = azurerm_storage_account.prime_state.name
  quota                = 100             # GiB
  protocol             = "NFS"
}

# --- Blob Storage: incident clips --------------------------------------------
resource "azurerm_storage_account" "clips" {
  name                     = "stsitewatchaiclips"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = local.tags
}

resource "azurerm_storage_container" "incident_clips" {
  name                  = "incident-clips"
  storage_account_name  = azurerm_storage_account.clips.name
  container_access_type = "private"
}

# --- Azure Database for PostgreSQL Flexible Server ---------------------------
resource "azurerm_postgresql_flexible_server" "pg" {
  name                   = "psql-sitewatch-ai"
  resource_group_name    = azurerm_resource_group.rg.name
  location               = azurerm_resource_group.rg.location
  version                = "15"
  sku_name               = "B_Standard_B1ms"   # smallest burstable SKU
  storage_mb             = 32768
  tags                   = local.tags
}
```

```bash
cd deploy/terraform/environments/azure
terraform init
terraform fmt -check
terraform validate

# REVIEW ONLY — expected output: 8 to add, 0 to change, 0 to destroy.
terraform plan -out=tfplan

# ┌────────────────────────────  ⚠️  COST WARNING  ────────────────────────────┐
# │ Running this plan incurs ~$120–$200/month: Premium Azure Files 100 GiB    │
# │ (~$40), PostgreSQL B1ms (~$25), Service Bus Standard (~$10), Container    │
# │ Apps (~$5). Do NOT run the command below unless you accept that burn.     │
# └────────────────────────────────────────────────────────────────────────────┘
# terraform apply tfplan
```

## 4. Container Image Publication

```bash
ACR=sitewatchaiacr.azurecr.io
az acr create --name sitewatchaiacr --resource-group rg-sitewatch-ai \
  --sku Standard --admin-enabled false   # use managed identity for pulls
az acr login --name sitewatchaiacr

docker build -t ${ACR}/sitewatch-ai/worker:0.1.0 ./services/reasoning-worker   # Prime Agent slow path
docker push ${ACR}/sitewatch-ai/worker:0.1.0
docker build -t ${ACR}/sitewatch-ai/backend:0.1.0 ./services/backend           # FastAPI delivery plane
docker push ${ACR}/sitewatch-ai/backend:0.1.0
```

## 5. Secrets & Identity

The worker and backend run under **system-assigned managed identities** — no
connection strings or registry credentials in the app. Least-privilege role
assignments:

```bash
WORKER=$(az containerapp show -g rg-sitewatch-ai -n sitewatch-ai-worker \
  --query identity.principalId -o tsv)
BACKEND=$(az containerapp show -g rg-sitewatch-ai -n sitewatch-ai-backend \
  --query identity.principalId -o tsv)
SB_ID=$(az servicebus namespace show -g rg-sitewatch-ai -n sitewatch-ai-sb --query id -o tsv)

# 1. Worker: receive + send on the anomaly queue ONLY
az role assignment create --assignee-object-id ${WORKER} --assignee-principal-type ServicePrincipal \
  --role "Azure Service Bus Data Receiver"  --scope ${SB_ID}
az role assignment create --assignee-object-id ${WORKER} --assignee-principal-type ServicePrincipal \
  --role "Azure Service Bus Data Sender"    --scope ${SB_ID}
# 2. Worker: read/write incident clips only (blob data plane)
az role assignment create --assignee-object-id ${WORKER} --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope $(az storage container show -n incident-clips --account-name stsitewatchaiclips --query id -o tsv)
# 3. Worker NFS share access is enforced via VNet-integrated Container Apps env + account firewall.

# 4. Backend: PostgreSQL data-plane access via Entra (Azure AD) auth, no SQL admin password
az role assignment create --assignee-object-id ${BACKEND} --assignee-principal-type ServicePrincipal \
  --role "Contributor" --scope $(az postgres flexible-server show -g rg-sitewatch-ai -n psql-sitewatch-ai --query id -o tsv)

# 5. LLM provider API key: injected as a Container Apps secret, never baked into images
az containerapp secret set -g rg-sitewatch-ai -n sitewatch-ai-worker \
  --secrets llm-api-key=keyvaultref=https://kv-sitewatch-ai.vault.azure.net/secrets/llm-api-key,identity=system
```

## 6. Smoke Test

Inject a synthetic anomaly event and verify the full SLOW PATH response.

```bash
# 1. Send a synthetic geofence-intrusion trigger (matches FAST PATH schema)
SB_CS=$(az servicebus namespace authorization-rule keys list \
  -g rg-sitewatch-ai --namespace-name sitewatch-ai-sb -n RootManageSharedAccessKey \
  --query primaryConnectionString -o tsv)
az servicebus queue send --connection-string ${SB_CS} \
  --queue-name sitewatch-ai-anomaly-events --message '{
  "event_id": "smoke-001", "event_type": "geofence_intrusion",
  "camera_id": "cam-east-gate", "tracklet_id": "tk-4471",
  "ground_coords_m": {"x": 12.4, "y": 8.1}, "velocity_ms": 1.6,
  "zone": "forklift_lane_b", "ts": "2026-01-15T09:30:02Z"
}'

# 2. Confirm the queue drained (no dead-letter accumulation)
az servicebus queue show -g rg-sitewatch-ai --namespace-name sitewatch-ai-sb \
  -n sitewatch-ai-anomaly-events --query "countDetails.{active:activeMessages,dlq:deadLetterMessageCount}" -o table

# 3. Check the worker logs for the expected agent pipeline stages
az containerapp logs show -g rg-sitewatch-ai -n sitewatch-ai-worker --tail 50
```

Expected agent incident response, in order:

1. Event decoded and accepted; JSON schema validation passes.
2. Kinematic verification: trajectory replay confirms sustained intrusion (velocity and
   ground-plane path consistent with the trigger).
3. OSHA-style compliance correlation: maps `forklift_lane_b` intrusion to powered-industrial-truck
   clearance rules; severity assigned.
4. Incident record inserted into PostgreSQL; clip reference resolved from
   `incident-clips` blob container (SAS URL generated).
5. Shift-report synthesis updated; harness memory note written to `/home/node/.prime` (Azure Files NFS).
6. Smoke event visible on the dashboard at `/incidents/smoke-001`.

Pass criteria: `activeMessages == 0`, `deadLetterMessageCount == 0`, one incident row,
and all six stages present in logs within 120 seconds.

## 7. Teardown & Cost Safety

```bash
# Budget alerts at $5 and $15 (do this BEFORE any apply)
az consumption budget create \
  --budget-name "sitewatch-ai-5usd" --amount 5 --time-grain Monthly \
  --category Cost --start-date 2026-01-01 --end-date 2026-12-31 \
  --notifications '{"actual_GreaterThan_50_Percent":{"enabled":true,"operator":"GreaterThan","threshold":50,"contactEmails":["ops@sitewatch-ai.dev"]}}'
az consumption budget create \
  --budget-name "sitewatch-ai-15usd" --amount 15 --time-grain Monthly \
  --category Cost --start-date 2026-01-01 --end-date 2026-12-31 \
  --notifications '{"actual_GreaterThan_90_Percent":{"enabled":true,"operator":"GreaterThan","threshold":90,"contactEmails":["ops@sitewatch-ai.dev"]}}'

# Destructive teardown — reference environments only
# terraform destroy -target=azurerm_postgresql_flexible_server.pg   # keep-always-on cost — first
# terraform destroy -target=azurerm_storage_share.prime_state        # Premium NFS — second
# terraform destroy                                                  # remainder (removes RG scope)

# Manual fallbacks if Terraform state is unavailable
# az group delete --name rg-sitewatch-ai --yes --no-wait
```

Cost-safety rules:

- Every tagged resource carries `ttl = "30d"`; a weekly job flags stale tags.
- PostgreSQL has no delete protection here (reference only); enable `delete_protected = true` for real deployments.
- `terraform apply` stays commented out in CI and here; CI runs `terraform fmt -check` + `terraform validate` only.
- KEDA scale rule starts from `minReplicas: 0` — the worker costs nothing while no anomaly events are queued.
- Azure IoT Edge (GPU edge alternative) runs on customer devices; cloud side bills only IoT Hub messaging.
