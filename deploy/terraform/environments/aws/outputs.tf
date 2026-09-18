output "incident_queue_url" {
  value       = aws_sqs_queue.incident_queue.url
  description = "SQS URL to inject into the edge vision filter's publisher config."
}

output "incident_queue_arn" {
  value       = aws_sqs_queue.incident_queue.arn
  description = "ARN of the incident processing queue."
}

output "efs_file_system_id" {
  value       = aws_efs_file_system.agent_storage.id
  description = "ID of the shared persistent harness-state volume."
}

output "ecs_service_name" {
  value       = aws_ecs_service.agent_service.name
  description = "Name of the deployed Fargate ECS service."
}

output "postgres_endpoint" {
  value       = aws_rds_cluster.postgres.endpoint
  description = "Aurora Serverless v2 writer endpoint for the delivery plane's DATABASE_URL."
}

output "incident_clips_bucket" {
  value       = aws_s3_bucket.incident_clips.bucket
  description = "S3 bucket the FastAPI backend resolves evidence clip URLs against."
}
