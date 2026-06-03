output "artifact_bucket" {
  description = "S3 bucket used for mirrored run artifacts."
  value       = aws_s3_bucket.artifacts.bucket
}

output "ecs_cluster_name" {
  description = "ECS cluster for ContentOps tasks."
  value       = aws_ecs_cluster.main.name
}

output "api_task_definition_arn" {
  description = "API task definition ARN."
  value       = aws_ecs_task_definition.api.arn
}

output "worker_task_definition_arn" {
  description = "Worker task definition ARN."
  value       = aws_ecs_task_definition.worker.arn
}

output "metadata_db_endpoint" {
  description = "RDS Postgres endpoint for run metadata."
  value       = aws_db_instance.metadata.endpoint
}

output "database_url_secret_arn" {
  description = "Secrets Manager secret ARN containing CONTENTOPS_DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "daily_worker_schedule_arn" {
  description = "EventBridge Scheduler ARN for the recurring worker."
  value       = aws_scheduler_schedule.daily_worker.arn
}

output "operations_dashboard_name" {
  description = "CloudWatch dashboard for ContentOps operations."
  value       = aws_cloudwatch_dashboard.operations.dashboard_name
}

output "api_error_alarm_name" {
  description = "CloudWatch alarm for API log-derived errors."
  value       = aws_cloudwatch_metric_alarm.api_errors.alarm_name
}

output "worker_failure_alarm_name" {
  description = "CloudWatch alarm for scheduled worker failures."
  value       = aws_cloudwatch_metric_alarm.worker_failures.alarm_name
}
