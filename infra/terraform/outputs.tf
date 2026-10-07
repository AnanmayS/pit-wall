output "dynamodb_table" {
  value = aws_dynamodb_table.pitwall.name
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecs_service" {
  value = aws_ecs_service.api.name
}
