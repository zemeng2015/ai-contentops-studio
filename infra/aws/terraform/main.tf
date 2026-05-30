locals {
  name = var.project_name
  tags = {
    Project = var.project_name
    System  = "ai-contentops-studio"
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.name}-artifacts-"
  tags          = local.tags
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = 30
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name}/worker"
  retention_in_days = 30
  tags              = local.tags
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  tags = local.tags
}

resource "aws_iam_role" "task_execution" {
  name = "${local.name}-task-execution"
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
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name = "${local.name}-task"
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
  tags = local.tags
}

resource "aws_iam_role_policy" "task_artifacts" {
  name = "${local.name}-artifacts"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ]
      Effect = "Allow"
      Resource = [
        aws_s3_bucket.artifacts.arn,
        "${aws_s3_bucket.artifacts.arn}/*"
      ]
    }]
  })
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.container_image
      essential = true
      command   = ["uvicorn", "contentops_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
      environment = [
        { name = "CONTENTOPS_ARTIFACT_STORE_PROVIDER", value = "s3" },
        { name = "CONTENTOPS_ARTIFACT_S3_BUCKET", value = aws_s3_bucket.artifacts.bucket },
        { name = "CONTENTOPS_ARTIFACT_S3_PREFIX", value = "contentops-artifacts" },
        { name = "CONTENTOPS_GENERATOR_PROVIDER", value = "template" },
        { name = "CONTENTOPS_RESEARCH_PROVIDER", value = "hybrid" },
        { name = "CONTENTOPS_HOMEPAGE_REPO_PATH", value = var.homepage_repo_path }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])
  tags = local.tags
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.container_image
      essential = true
      command   = ["contentops-worker", "run-pipeline", "pipelines/daily_ai_roundup.yaml"]
      environment = [
        { name = "CONTENTOPS_ARTIFACT_STORE_PROVIDER", value = "s3" },
        { name = "CONTENTOPS_ARTIFACT_S3_BUCKET", value = aws_s3_bucket.artifacts.bucket },
        { name = "CONTENTOPS_ARTIFACT_S3_PREFIX", value = "contentops-artifacts" },
        { name = "CONTENTOPS_GENERATOR_PROVIDER", value = "template" },
        { name = "CONTENTOPS_RESEARCH_PROVIDER", value = "hybrid" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "worker"
        }
      }
    }
  ])
  tags = local.tags
}

resource "aws_scheduler_schedule_group" "contentops" {
  name = local.name
  tags = local.tags
}

