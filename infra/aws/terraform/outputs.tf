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

output "worker_alert_notifier_task_definition_arn" {
  description = "Worker alert notifier task definition ARN."
  value       = aws_ecs_task_definition.worker_alert_notifier.arn
}

output "ops_brief_notifier_task_definition_arn" {
  description = "Operations brief notifier task definition ARN."
  value       = aws_ecs_task_definition.ops_brief_notifier.arn
}

output "release_gate_task_definition_arn" {
  description = "Release gate task definition ARN."
  value       = aws_ecs_task_definition.release_gate.arn
}

output "retention_archive_task_definition_arn" {
  description = "Retention archive task definition ARN."
  value       = aws_ecs_task_definition.retention_archive.arn
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

output "worker_alert_notifier_schedule_arn" {
  description = "EventBridge Scheduler ARN for recurring worker alert notifications."
  value       = aws_scheduler_schedule.worker_alert_notifier.arn
}

output "ops_brief_notifier_schedule_arn" {
  description = "EventBridge Scheduler ARN for recurring operations brief notifications."
  value       = aws_scheduler_schedule.ops_brief_notifier.arn
}

output "release_gate_schedule_arn" {
  description = "EventBridge Scheduler ARN for recurring release gate checks."
  value       = aws_scheduler_schedule.release_gate.arn
}

output "retention_archive_schedule_arn" {
  description = "EventBridge Scheduler ARN for recurring retention archive creation."
  value       = aws_scheduler_schedule.retention_archive.arn
}

output "scheduler_dlq_url" {
  description = "SQS dead-letter queue URL for failed EventBridge Scheduler invocations."
  value       = aws_sqs_queue.scheduler_dlq.url
}

output "scheduler_dlq_arn" {
  description = "SQS dead-letter queue ARN for failed EventBridge Scheduler invocations."
  value       = aws_sqs_queue.scheduler_dlq.arn
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

output "scheduler_dlq_alarm_name" {
  description = "CloudWatch alarm for EventBridge Scheduler DLQ messages."
  value       = aws_cloudwatch_metric_alarm.scheduler_dlq_messages.alarm_name
}
