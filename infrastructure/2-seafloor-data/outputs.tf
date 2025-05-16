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