# Pit Wall AWS infrastructure: DynamoDB (What If cache + share links), S3 (FastF1 cache / model files),
# ECR + ECS Fargate (API), CloudWatch logs. ClickHouse is NOT provisioned here (see PLAN.md § 8:
# hosting choice deferred); the API reads CLICKHOUSE_* from variables.
#
# Usage: terraform init && terraform plan -var 'clickhouse_host=...' -var 'clickhouse_password=...'

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name = "${var.project}-${var.environment}"
  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------- DynamoDB: single table, mirrors pitwall/db/dynamo.py ----------
resource "aws_dynamodb_table" "pitwall" {
  name         = local.name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "GSI1PK"
    type = "S"
  }
  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = local.tags
}

# ---------- S3: FastF1 cache + fitted model files ----------
resource "aws_s3_bucket" "data" {
  bucket        = "${local.name}-data-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment != "prod"
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_caller_identity" "current" {}

# ---------- ECR + ECS Fargate for the API ----------
resource "aws_ecr_repository" "api" {
  name                 = "${local.name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment != "prod"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = local.tags
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}-api"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  tags = local.tags
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${local.name}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "DynamoSingleTable"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.pitwall.arn, "${aws_dynamodb_table.pitwall.arn}/index/*"]
  }
  statement {
    sid       = "DataBucket"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${local.name}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name         = "api"
      image        = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
      essential    = true
      portMappings = [{ containerPort = 8080, protocol = "tcp" }]
      environment = [
        { name = "CLICKHOUSE_HOST", value = var.clickhouse_host },
        { name = "CLICKHOUSE_PORT", value = tostring(var.clickhouse_port) },
        { name = "CLICKHOUSE_USER", value = var.clickhouse_user },
        { name = "CLICKHOUSE_DATABASE", value = "pitwall" },
        { name = "DYNAMODB_ENDPOINT_URL", value = "" },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "PITWALL_DDB_TABLE", value = aws_dynamodb_table.pitwall.name },
      ]
      secrets = [
        { name = "CLICKHOUSE_PASSWORD", valueFrom = aws_ssm_parameter.clickhouse_password.arn },
        { name = "ANTHROPIC_API_KEY", valueFrom = aws_ssm_parameter.anthropic_api_key.arn },
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

resource "aws_ssm_parameter" "clickhouse_password" {
  name  = "/${local.name}/clickhouse_password"
  type  = "SecureString"
  value = var.clickhouse_password
  tags  = local.tags
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name  = "/${local.name}/anthropic_api_key"
  type  = "SecureString"
  value = var.anthropic_api_key
  tags  = local.tags
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["ssm:GetParameters", "kms:Decrypt"]
    resources = [aws_ssm_parameter.clickhouse_password.arn, aws_ssm_parameter.anthropic_api_key.arn, "arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "${local.name}-execution-secrets"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api"
  description = "Pit Wall API"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = var.api_ingress_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.tags
}

resource "aws_ecs_service" "api" {
  name            = "${local.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true
  }
  tags = local.tags
}
