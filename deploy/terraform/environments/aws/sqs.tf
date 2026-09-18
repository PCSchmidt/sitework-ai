# Telemetry queue + dead-letter queue. SQS is this repo's Redis Streams
# (pipelines/broker/streams.py's trigger_events) analog in AWS -- the agent worker
# consumes TriggerEvents from here instead of XREADGROUP.

# Dead-letter queue for failed or corrupted reasoning payloads.
resource "aws_sqs_queue" "agent_dlq" {
  name                      = "${var.project_name}-incident-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Main queue buffering anomaly events dispatched by the edge vision filter.
resource "aws_sqs_queue" "incident_queue" {
  name                       = "${var.project_name}-incident-queue-${var.environment}"
  visibility_timeout_seconds = 300 # set higher than max agent-worker execution/turn timeout
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.agent_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
