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
  description = "Private subnet IDs for the RDS subnet group."
  type        = list(string)
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

variable "homepage_repo_path" {
  description = "Optional mounted path for homepage publisher in container deployments."
  type        = string
  default     = ""
}
