# Fargate task security group -- egress control for the agent worker container.
resource "aws_security_group" "agent_task_sg" {
  name        = "${var.project_name}-task-sg-${var.environment}"
  description = "Egress control for the agent worker container"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow outbound HTTPS for LLM API providers and AWS services"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow NFS communication to EFS mount targets"
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# ECS Execution Role -- pulls images, fetches secrets, pushes CloudWatch logs.
resource "aws_iam_role" "ecs_execution_role" {
  name = "${var.project_name}-ecs-execution-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_base" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role -- runtime permissions granted to the agent worker process itself.
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.project_name}-ecs-task-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

# SQS read/delete permissions for the worker's consume loop
# (agent/worker.py's ConsumerGroupReader analog).
resource "aws_iam_policy" "agent_sqs_policy" {
  name        = "${var.project_name}-agent-sqs-policy-${var.environment}"
  description = "Allows the agent worker to consume incident messages"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = aws_sqs_queue.incident_queue.arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_sqs_attach" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.agent_sqs_policy.arn
}

# S3 read/write for evidence clips (agent/worker.py copies clip.mp4 into the
# incident workspace; a real deployment would also push it to S3 from there).
resource "aws_iam_policy" "agent_s3_policy" {
  name        = "${var.project_name}-agent-s3-policy-${var.environment}"
  description = "Allows the agent worker to read/write incident evidence clips"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.incident_clips.arn}/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_s3_attach" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.agent_s3_policy.arn
}
