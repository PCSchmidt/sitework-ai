# AWS environment: ECS Fargate agent worker + SQS + EFS, realized from
# "SiteWatch AI - AWS ECS Fargate & EFS Terraform Configuration.pdf" (repo root) in M6.
# Validate-only in CI (ADR-004) -- no provider block change here, see versions.tf.
# Config split into sqs.tf / efs.tf / security_iam.tf / main.tf / outputs.tf, matching
# the source spec's own file layout.

resource "aws_cloudwatch_log_group" "agent_logs" {
  name              = "/ecs/${var.project_name}-worker-${var.environment}"
  retention_in_days = 30

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_ecs_cluster" "cluster" {
  name = "${var.project_name}-cluster-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# Task definition with the EFS volume bound at /root/.prime -- matches
# docker/Dockerfile.agent's harness-state mount point exactly, so the same
# container image behaves identically in ECS as it does under docker-compose.
resource "aws_ecs_task_definition" "agent_task" {
  family                   = "${var.project_name}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  volume {
    name = "prime_agent_state"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.agent_storage.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.agent_access_point.id
        iam             = "DISABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "agent-worker"
      image     = var.agent_image_uri
      essential = true

      mountPoints = [
        {
          sourceVolume  = "prime_agent_state"
          containerPath = "/root/.prime"
          readOnly      = false
        }
      ]

      environment = [
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.incident_queue.url },
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "PRIME_HEADLESS", value = "true" },
        { name = "PRIME_LOG_LEVEL", value = "INFO" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.agent_logs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "agent"
        }
      }
    }
  ])

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# desired_count = 1: a queue-driven, single-worker reference deployment.
# Scale-with-queue-depth (SQS ApproximateNumberOfMessagesVisible -> Application
# Auto Scaling target tracking) is documented in the AWS runbook, not wired here --
# this reference environment demonstrates the topology, not an autoscaling policy
# that would need real traffic to tune sensibly.
resource "aws_ecs_service" "agent_service" {
  name            = "${var.project_name}-service-${var.environment}"
  cluster         = aws_ecs_cluster.cluster.id
  task_definition = aws_ecs_task_definition.agent_task.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.agent_task_sg.id]
    assign_public_ip = false
  }

  depends_on = [
    aws_efs_mount_target.mount
  ]

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
