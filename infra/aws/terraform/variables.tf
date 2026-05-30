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

