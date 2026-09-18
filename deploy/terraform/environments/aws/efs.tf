# Persistent volume for the Prime Agent harness's own session/state directory
# (~/.prime in the container -- see docker/docker-compose.yml's agent service,
# which mounts this from the host locally; EFS is the same role in AWS).

# Dedicated security group for EFS mount targets.
resource "aws_security_group" "efs_sg" {
  name        = "${var.project_name}-efs-sg-${var.environment}"
  description = "Allow inbound NFS from ECS Fargate agent worker tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "NFS inbound from ECS agent worker"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.agent_task_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# EFS filesystem storing the agent's ~/.prime state, refined sub-agent specs, and
# session logs -- the same directory docker-compose.yml bind-mounts from the host's
# PRIME_HARNESS_DIR locally (docker/docker-compose.yml's agent service).
resource "aws_efs_file_system" "agent_storage" {
  creation_token = "${var.project_name}-efs-${var.environment}"
  encrypted      = true

  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name        = "${var.project_name}-efs-${var.environment}"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Mount targets created across all designated private subnets.
resource "aws_efs_mount_target" "mount" {
  count = length(var.private_subnet_ids)

  file_system_id  = aws_efs_file_system.agent_storage.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs_sg.id]
}

# EFS Access Point enforcing POSIX permissions for the agent execution root --
# node:22-bookworm-slim's uid-1000 "node" user (docker/Dockerfile.agent).
resource "aws_efs_access_point" "agent_access_point" {
  file_system_id = aws_efs_file_system.agent_storage.id

  posix_user {
    gid = 1000
    uid = 1000
  }

  root_directory {
    path = "/prime_harness"
    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "755"
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
