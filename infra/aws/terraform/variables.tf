variable "aws_region" {
  description = "AWS region for ContentOps infrastructure."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for AWS resources."
  type        = string
  default     = "ai-contentops-studio"
}

variable "container_image" {
  description = "Container image URI for the API and worker services."
  type        = string
}

variable "vpc_id" {
  description = "VPC where RDS and future ECS services will run."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for RDS and scheduled ECS worker tasks."
  type        = list(string)
}

variable "worker_security_group_ids" {
  description = "Security group IDs attached to scheduled ECS worker tasks."
  type        = list(string)
  default     = []
}

variable "db_allowed_cidr_blocks" {
  description = "Optional CIDR blocks allowed to connect to Postgres."
  type        = list(string)
  default     = []
}

variable "db_name" {
  description = "Postgres database name for run metadata."
  type        = string
  default     = "contentops"
}

variable "db_username" {
  description = "Postgres username for run metadata."
  type        = string
  default     = "contentops"
}

variable "db_instance_class" {
  description = "RDS instance class for the metadata database."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Allocated RDS storage in GB."
  type        = number
  default     = 20
}

variable "db_deletion_protection" {
  description = "Whether deletion protection is enabled for RDS."
  type        = bool
  default     = false
}

variable "openai_api_key_secret_arn" {
  description = "Secrets Manager ARN containing the OpenAI API key."
  type        = string
  default     = ""
}

variable "research_provider" {
  description = "Research provider used by API and scheduled workers."
  type        = string
  default     = "discovery"
}

variable "research_search_api_key_secret_arn" {
  description = "Secrets Manager ARN containing the optional search provider API key."
  type        = string
  default     = ""
}

variable "research_github_token_secret_arn" {
  description = "Secrets Manager ARN containing the optional GitHub token for repository research."
  type        = string
  default     = ""
}

variable "operator_api_key_secret_arn" {
  description = "Secrets Manager ARN containing the optional operator API key."
  type        = string
  default     = ""
}

variable "read_api_key_secret_arn" {
  description = "Secrets Manager ARN containing the optional read-only API key."
  type        = string
  default     = ""
}

variable "require_read_api_key" {
  description = "Whether read routes should require a read or operator API key."
  type        = bool
  default     = false
}

variable "notification_webhook_url_secret_arn" {
  description = "Secrets Manager ARN containing an optional notification webhook URL."
  type        = string
  default     = ""
}

variable "notification_timeout_seconds" {
  description = "Webhook notification timeout in seconds."
  type        = number
  default     = 5
}

variable "latency_slo_ms" {
  description = "Run duration SLO in milliseconds for operational scorecards."
  type        = number
  default     = 120000
}

variable "min_source_count" {
  description = "Minimum source count expected by operational scorecards."
  type        = number
  default     = 1
}

variable "token_budget_per_run" {
  description = "Per-run estimated token budget for cost reports."
  type        = number
  default     = 12000
}

variable "homepage_repo_path" {
  description = "Optional mounted path for homepage publisher in container deployments."
  type        = string
  default     = ""
}

variable "worker_schedule_expression" {
  description = "EventBridge Scheduler expression for recurring worker runs."
  type        = string
  default     = "cron(0 13 * * ? *)"
}

variable "worker_schedule_timezone" {
  description = "Timezone for the worker schedule expression."
  type        = string
  default     = "America/New_York"
}

variable "worker_schedule_enabled" {
  description = "Whether the recurring worker schedule is enabled."
  type        = bool
  default     = false
}

variable "worker_pipeline_path" {
  description = "Pipeline YAML path executed by the scheduled worker task."
  type        = string
  default     = "pipelines/daily_ai_roundup.yaml"
}

variable "worker_alert_schedule_expression" {
  description = "EventBridge Scheduler expression for recurring worker alert notification checks."
  type        = string
  default     = "cron(30 13 * * ? *)"
}

variable "worker_alert_schedule_enabled" {
  description = "Whether the recurring worker alert notifier schedule is enabled."
  type        = bool
  default     = false
}

variable "worker_alert_window_days" {
  description = "Number of recent days included by the worker alert notifier task."
  type        = number
  default     = 14
}

variable "release_gate_schedule_expression" {
  description = "EventBridge Scheduler expression for recurring release gate evidence checks."
  type        = string
  default     = "cron(0 14 * * ? *)"
}

variable "release_gate_schedule_enabled" {
  description = "Whether the recurring release gate evidence check is enabled."
  type        = bool
  default     = false
}

variable "release_gate_window_size" {
  description = "Number of recent runs included by the recurring release gate task."
  type        = number
  default     = 100
}

variable "release_gate_require_approval" {
  description = "Whether the recurring release gate task requires release approval."
  type        = bool
  default     = true
}

variable "alarm_actions" {
  description = "SNS topic ARNs or other CloudWatch alarm actions for alarm and OK transitions."
  type        = list(string)
  default     = []
}

variable "alarm_period_seconds" {
  description = "CloudWatch alarm period in seconds."
  type        = number
  default     = 300
}

variable "alarm_evaluation_periods" {
  description = "Number of periods evaluated before an alarm changes state."
  type        = number
  default     = 1
}

variable "api_error_alarm_threshold" {
  description = "API log-derived error count that triggers an alarm within the alarm period."
  type        = number
  default     = 1
}

variable "worker_failure_alarm_threshold" {
  description = "Worker log-derived failure count that triggers an alarm within the alarm period."
  type        = number
  default     = 1
}

variable "db_connection_alarm_threshold" {
  description = "Average RDS connection count that triggers an alarm within the alarm period."
  type        = number
  default     = 40
}
