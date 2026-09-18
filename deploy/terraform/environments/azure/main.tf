# Azure environment: Service Bus + Azure Files NFS + Blob Storage + PostgreSQL
# Flexible Server, realized from docs/deployment/azure-deployment-guide.md §3 in
# M6. Container Apps + managed-identity role assignments stay in that guide's
# §4-5 imperative `az` steps by design, same split as the GCP environment.

locals {
  location = "eastus"
  rg_name  = "rg-sitewatch-ai"
  tags = {
    project     = "sitewatch-ai"
    managed-by  = "terraform"
    ttl         = "30d" # auto-expiry tag for cost safety
    environment = var.environment
  }
}

resource "azurerm_resource_group" "rg" {
  name     = local.rg_name
  location = local.location
  tags     = local.tags
}

# --- Service Bus: anomaly events queue + dead-letter subqueue ----------------
resource "azurerm_servicebus_namespace" "sb" {
  # Azure rejects names ending in "-sb"/"-mgmt"/a hyphen -- real validation
  # error caught by actually running `terraform validate`, not by inspection.
  name                = "sitewatch-ai-servicebus"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_servicebus_queue" "anomaly_events" {
  name         = "sitewatch-ai-anomaly-events"
  namespace_id = azurerm_servicebus_namespace.sb.id

  max_delivery_count                   = 5 # then -> dead-letter subqueue
  dead_lettering_on_message_expiration = true
  default_message_ttl                  = "P7D"
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
  name                 = "prime-state" # mounted at /home/node/.prime
  storage_account_name = azurerm_storage_account.prime_state.name
  quota                = 100 # GiB
  # Not "protocol" -- the deployment guide's illustrative snippet had this
  # wrong; azurerm_storage_share's actual argument name (verified against the
  # real provider schema, azurerm ~> 3.0) is enabled_protocol.
  enabled_protocol = "NFS"
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
  sku_name               = "B_Standard_B1ms" # smallest burstable SKU
  storage_mb             = 32768
  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password
  tags                   = local.tags
}
