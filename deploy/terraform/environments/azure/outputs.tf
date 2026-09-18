output "anomaly_events_queue" {
  value       = azurerm_servicebus_queue.anomaly_events.name
  description = "Service Bus queue to inject into the edge vision filter's publisher config."
}

output "incident_clips_container" {
  value       = azurerm_storage_container.incident_clips.name
  description = "Blob container the FastAPI backend resolves SAS clip URLs against."
}

output "postgres_fqdn" {
  value       = azurerm_postgresql_flexible_server.pg.fqdn
  description = "PostgreSQL Flexible Server FQDN for the delivery-plane connection string."
}
