variable "project" {
  type    = string
  default = "pitwall"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "api_image_tag" {
  type    = string
  default = "latest"
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 2048
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "api_ingress_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

variable "clickhouse_host" {
  type = string
}

variable "clickhouse_port" {
  type    = number
  default = 8443
}

variable "clickhouse_user" {
  type    = string
  default = "pitwall"
}

variable "clickhouse_password" {
  type      = string
  sensitive = true
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
  default   = ""
}
