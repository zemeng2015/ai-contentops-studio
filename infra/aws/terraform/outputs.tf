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

