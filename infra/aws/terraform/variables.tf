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

variable "operator_api_key_secret_arn" {
  description = "Secrets Manager ARN containing the optional operator API key."
  type        = string
  default     = ""
}

variable "require_read_api_key" {
  description = "Whether read routes should require the operator API key."
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
