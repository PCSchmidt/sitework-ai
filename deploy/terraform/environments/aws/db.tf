# Aurora Serverless v2 (PostgreSQL) -- the delivery plane's system of record
# (api/schema.sql's incidents/reviews/agent_runs tables), matching
# docs/10-cost-model.md's Scenario A row ("Aurora Serverless v2 (paused)") and
# this guide's own architecture table. Real gap closed here: the source PDF
# spec only covered the agent worker's own ECS/SQS/EFS topology, not the
# delivery-plane DB the architecture table already promised -- added for
# real parity with the GCP (Cloud SQL) and Azure (PostgreSQL Flexible Server)
# environments, which both include their DB from the start.

resource "aws_db_subnet_group" "postgres" {
  name       = "${var.project_name}-db-subnet-${var.environment}"
  subnet_ids = var.private_subnet_ids

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# Separate from agent_task_sg: only the delivery-plane API service should
# reach Postgres directly, not the agent worker (which never touches the DB
# itself -- api/repository.py is the only writer, via agent/persistence.py's
# PostgresPersister running inside the agent container, so the agent task
# does need access too; a future api-service Fargate task's SG should be
# added here once that service is realized in Terraform).
resource "aws_security_group" "postgres_sg" {
  name        = "${var.project_name}-db-sg-${var.environment}"
  description = "Allow inbound Postgres from the agent worker task"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Postgres inbound from the agent worker"
    from_port       = 5432
    to_port         = 5432
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

resource "aws_rds_cluster" "postgres" {
  cluster_identifier = "${var.project_name}-pg-${var.environment}"
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  engine_version     = "15.4"
  database_name      = "sitewatch" # matches docker/docker-compose.yml's POSTGRES_DB
  master_username    = var.db_master_username
  master_password    = var.db_master_password

  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.postgres_sg.id]

  storage_encrypted   = true
  skip_final_snapshot = true # reference architecture only
  deletion_protection = false

  serverlessv2_scaling_configuration {
    min_capacity = 0.5 # smallest ACU step -- scales toward $0 when idle
    max_capacity = 2.0
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_rds_cluster_instance" "postgres" {
  cluster_identifier = aws_rds_cluster.postgres.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.postgres.engine
  engine_version     = aws_rds_cluster.postgres.engine_version

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
