locals {
  name = var.project_name
  tags = {
    Project = var.project_name
    System  = "ai-contentops-studio"
  }
  database_url         = "postgresql+psycopg://${var.db_username}:${random_password.db.result}@${aws_db_instance.metadata.address}:${aws_db_instance.metadata.port}/${var.db_name}"
  cloudwatch_namespace = "ContentOps/${local.name}"
  worker_security_group_ids = length(var.worker_security_group_ids) > 0 ? var.worker_security_group_ids : [
    aws_security_group.worker.id
  ]
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

resource "aws_cloudwatch_log_metric_filter" "api_errors" {
  name           = "${local.name}-api-errors"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "?ERROR ?Error ?Traceback ?exception ?failed"

  metric_transformation {
    name      = "ApiErrorCount"
    namespace = local.cloudwatch_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_failures" {
  name           = "${local.name}-worker-failures"
  log_group_name = aws_cloudwatch_log_group.worker.name
  pattern        = "?ERROR ?Error ?Traceback ?exception ?failed"

  metric_transformation {
    name      = "WorkerFailureCount"
    namespace = local.cloudwatch_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${local.name}-api-errors"
  alarm_description   = "API task logs contain errors that should be investigated."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  threshold           = var.api_error_alarm_threshold
  period              = var.alarm_period_seconds
  statistic           = "Sum"
  namespace           = local.cloudwatch_namespace
  metric_name         = "ApiErrorCount"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "worker_failures" {
  alarm_name          = "${local.name}-worker-failures"
  alarm_description   = "Scheduled worker logs contain failures or tracebacks."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  threshold           = var.worker_failure_alarm_threshold
  period              = var.alarm_period_seconds
  statistic           = "Sum"
  namespace           = local.cloudwatch_namespace
  metric_name         = "WorkerFailureCount"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
  tags                = local.tags
}

resource "aws_cloudwatch_metric_alarm" "database_connections" {
  alarm_name          = "${local.name}-db-connections-high"
  alarm_description   = "RDS connection count is above the configured operational threshold."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  threshold           = var.db_connection_alarm_threshold
  period              = var.alarm_period_seconds
  statistic           = "Average"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.metadata.identifier
  }

  tags = local.tags
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "metadata" {
  name       = "${local.name}-metadata"
  subnet_ids = var.private_subnet_ids
  tags       = local.tags
}

resource "aws_security_group" "metadata_db" {
  name        = "${local.name}-metadata-db"
  description = "Postgres access for AI ContentOps metadata."
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "Scheduled worker task network access."
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_egress_rule" "worker" {
  security_group_id = aws_security_group.worker.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow worker outbound access to feeds, S3, Secrets Manager, and logs."
}

resource "aws_vpc_security_group_ingress_rule" "metadata_db_worker" {
  security_group_id            = aws_security_group.metadata_db.id
  referenced_security_group_id = aws_security_group.worker.id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "Allow scheduled workers to write run metadata."
}

resource "aws_vpc_security_group_ingress_rule" "metadata_db_cidr" {
  for_each          = toset(var.db_allowed_cidr_blocks)
  security_group_id = aws_security_group.metadata_db.id
  cidr_ipv4         = each.value
  from_port         = 5432
  ip_protocol       = "tcp"
  to_port           = 5432
  description       = "Allow Postgres metadata access."
}

resource "aws_vpc_security_group_egress_rule" "metadata_db" {
  security_group_id = aws_security_group.metadata_db.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow database maintenance egress."
}

resource "aws_db_instance" "metadata" {
  identifier             = "${local.name}-metadata"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  db_name                = var.db_name
  username               = var.db_username
  password               = random_password.db.result
  db_subnet_group_name   = aws_db_subnet_group.metadata.name
  vpc_security_group_ids = [aws_security_group.metadata_db.id]
  storage_encrypted      = true
  publicly_accessible    = false
  skip_final_snapshot    = !var.db_deletion_protection
  deletion_protection    = var.db_deletion_protection
  tags                   = local.tags
}

resource "aws_secretsmanager_secret" "database_url" {
  name = "${local.name}/database-url"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
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

resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "${local.name}-execution-secrets"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Effect = "Allow"
      Resource = compact([
        aws_secretsmanager_secret.database_url.arn,
        var.openai_api_key_secret_arn,
        var.operator_api_key_secret_arn,
        var.read_api_key_secret_arn,
        var.notification_webhook_url_secret_arn
      ])
    }]
  })
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
        { name = "CONTENTOPS_RESEARCH_PROVIDER", value = "discovery" },
        { name = "CONTENTOPS_RUN_MIGRATIONS", value = "true" },
        { name = "CONTENTOPS_REQUIRE_READ_API_KEY", value = tostring(var.require_read_api_key) },
        { name = "CONTENTOPS_NOTIFICATION_TIMEOUT_SECONDS", value = tostring(var.notification_timeout_seconds) },
        { name = "CONTENTOPS_LATENCY_SLO_MS", value = tostring(var.latency_slo_ms) },
        { name = "CONTENTOPS_MIN_SOURCE_COUNT", value = tostring(var.min_source_count) },
        { name = "CONTENTOPS_TOKEN_BUDGET_PER_RUN", value = tostring(var.token_budget_per_run) },
        { name = "CONTENTOPS_HOMEPAGE_REPO_PATH", value = var.homepage_repo_path }
      ]
      secrets = concat(
        [
          {
            name      = "CONTENTOPS_DATABASE_URL"
            valueFrom = aws_secretsmanager_secret.database_url.arn
          }
        ],
        var.openai_api_key_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_OPENAI_API_KEY"
            valueFrom = var.openai_api_key_secret_arn
          }
        ] : [],
        var.operator_api_key_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_OPERATOR_API_KEY"
            valueFrom = var.operator_api_key_secret_arn
          }
        ] : [],
        var.read_api_key_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_READ_API_KEY"
            valueFrom = var.read_api_key_secret_arn
          }
        ] : [],
        var.notification_webhook_url_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_NOTIFICATION_WEBHOOK_URL"
            valueFrom = var.notification_webhook_url_secret_arn
          }
        ] : []
      )
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
        { name = "CONTENTOPS_RESEARCH_PROVIDER", value = "discovery" },
        { name = "CONTENTOPS_REQUIRE_READ_API_KEY", value = tostring(var.require_read_api_key) },
        { name = "CONTENTOPS_NOTIFICATION_TIMEOUT_SECONDS", value = tostring(var.notification_timeout_seconds) },
        { name = "CONTENTOPS_LATENCY_SLO_MS", value = tostring(var.latency_slo_ms) },
        { name = "CONTENTOPS_MIN_SOURCE_COUNT", value = tostring(var.min_source_count) },
        { name = "CONTENTOPS_TOKEN_BUDGET_PER_RUN", value = tostring(var.token_budget_per_run) }
      ]
      secrets = concat(
        [
          {
            name      = "CONTENTOPS_DATABASE_URL"
            valueFrom = aws_secretsmanager_secret.database_url.arn
          }
        ],
        var.openai_api_key_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_OPENAI_API_KEY"
            valueFrom = var.openai_api_key_secret_arn
          }
        ] : [],
        var.operator_api_key_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_OPERATOR_API_KEY"
            valueFrom = var.operator_api_key_secret_arn
          }
        ] : [],
        var.read_api_key_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_READ_API_KEY"
            valueFrom = var.read_api_key_secret_arn
          }
        ] : [],
        var.notification_webhook_url_secret_arn != "" ? [
          {
            name      = "CONTENTOPS_NOTIFICATION_WEBHOOK_URL"
            valueFrom = var.notification_webhook_url_secret_arn
          }
        ] : []
      )
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

resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "scheduler.amazonaws.com"
      }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "scheduler_run_worker" {
  name = "${local.name}-run-worker"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ecs:RunTask"
        ]
        Effect   = "Allow"
        Resource = aws_ecs_task_definition.worker.arn
      },
      {
        Action = [
          "iam:PassRole"
        ]
        Effect = "Allow"
        Resource = [
          aws_iam_role.task.arn,
          aws_iam_role.task_execution.arn
        ]
      }
    ]
  })
}

resource "aws_scheduler_schedule" "daily_worker" {
  name                         = "${local.name}-daily-worker"
  group_name                   = aws_scheduler_schedule_group.contentops.name
  schedule_expression          = var.worker_schedule_expression
  schedule_expression_timezone = var.worker_schedule_timezone
  state                        = var.worker_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      launch_type         = "FARGATE"
      task_count          = 1
      task_definition_arn = aws_ecs_task_definition.worker.arn

      network_configuration {
        assign_public_ip = false
        security_groups  = local.worker_security_group_ids
        subnets          = var.private_subnet_ids
      }
    }
  }
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.name}-operations"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 2
        properties = {
          markdown = "# AI ContentOps Studio Operations\nRelease evidence: `/release-evidence`; worker receipts: `/job-executions`; job catalog: `/worker-jobs`."
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 2
        width  = 12
        height = 6
        properties = {
          title   = "API and worker log-derived errors"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          metrics = [
            [local.cloudwatch_namespace, "ApiErrorCount"],
            [".", "WorkerFailureCount"]
          ]
          stat   = "Sum"
          period = var.alarm_period_seconds
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 2
        width  = 12
        height = 6
        properties = {
          title   = "RDS metadata database"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", aws_db_instance.metadata.identifier],
            [".", "CPUUtilization", ".", "."],
            [".", "FreeStorageSpace", ".", "."]
          ]
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 8
        width  = 12
        height = 6
        properties = {
          title   = "ECS API task resources"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "TaskDefinitionFamily", aws_ecs_task_definition.api.family],
            [".", "MemoryUtilization", ".", ".", ".", "."]
          ]
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 8
        width  = 12
        height = 6
        properties = {
          title   = "ECS worker task resources"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "TaskDefinitionFamily", aws_ecs_task_definition.worker.family],
            [".", "MemoryUtilization", ".", ".", ".", "."]
          ]
          period = 300
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 14
        width  = 12
        height = 6
        properties = {
          title  = "Recent API errors"
          region = var.aws_region
          query  = "SOURCE '${aws_cloudwatch_log_group.api.name}' | fields @timestamp, @message | filter @message like /ERROR|Error|Traceback|exception|failed/ | sort @timestamp desc | limit 20"
          view   = "table"
        }
      },
      {
        type   = "log"
        x      = 12
        y      = 14
        width  = 12
        height = 6
        properties = {
          title  = "Recent worker failures"
          region = var.aws_region
          query  = "SOURCE '${aws_cloudwatch_log_group.worker.name}' | fields @timestamp, @message | filter @message like /ERROR|Error|Traceback|exception|failed/ | sort @timestamp desc | limit 20"
          view   = "table"
        }
      }
    ]
  })
}
