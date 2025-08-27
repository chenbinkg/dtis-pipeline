output "raw_data_s3_bucket_name" {
  value    = aws_s3_bucket.raw_data.id
}

output "dtis_model_s3_bucket_name" {
  value    = aws_s3_bucket.dtis_model.id
}

output "mediaconvert_events_log_group_name" {
  description = "Name of the CloudWatch Logs log group for MediaConvert events"
  value       = aws_cloudwatch_log_group.mediaconvert_events_log_group.name
}

output "mediaconvert_events_log_group_arn" {
  description = "ARN of the CloudWatch Logs log group for MediaConvert events"
  value       = aws_cloudwatch_log_group.mediaconvert_events_log_group.arn
}

output "dtis_annotation_ecr_repository_url" {
  description = "ECR repository URL for the annotation container"
  value = aws_ecr_repository.dtis_annotation_ecr.repository_url
}

output "dtis_annotation_ecr_repository_name" {
  description = "ECR repository name for the annotation container"
  value = aws_ecr_repository.dtis_annotation_ecr.name
}