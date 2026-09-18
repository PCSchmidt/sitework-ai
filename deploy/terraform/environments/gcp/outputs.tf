output "anomaly_events_topic" {
  value       = google_pubsub_topic.anomaly_events.id
  description = "Pub/Sub topic to inject into the edge vision filter's publisher config."
}

output "incident_clips_bucket" {
  value       = google_storage_bucket.incident_clips.name
  description = "GCS bucket the FastAPI backend resolves clip signed URLs against."
}

output "postgres_connection_name" {
  value       = google_sql_database_instance.postgres.connection_name
  description = "Cloud SQL instance connection name for the Cloud SQL Auth Proxy."
}
