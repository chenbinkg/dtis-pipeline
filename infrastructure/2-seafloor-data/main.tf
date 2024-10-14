locals {
  tags = {
    creation_method  = "terraform"
    project_name = var.project_name
  }
}

resource "aws_s3_bucket" "raw_data" {
  #checkov:skip=CKV_AWS_18: "Ensure the S3 bucket has access logging enabled" - no need here, use Amazon CloudTrail instead
  #checkov:skip=CKV_AWS_144: "Ensure that S3 bucket has cross-region replication enabled"
  #checkov:skip=CKV2_AWS_61: "Ensure that an S3 bucket has a lifecycle configuration"
  #checkov:skip=CKV2_AWS_62: "Ensure S3 buckets should have event notifications enabled"
  bucket        = "dtis-ofop-${data.aws_caller_identity.current.account_id}-raw-${var.environment}"
  tags          = local.tags
  force_destroy = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw_data" {
  bucket = aws_s3_bucket.raw_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_versioning"  "raw_data" {
  bucket = aws_s3_bucket.raw_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_setup" {
  bucket                  = aws_s3_bucket.raw_data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "local_file" "raw_data_s3_bucket_name" {
  content  = aws_s3_bucket.raw_data.id
  filename = "tf_output_raw_data_s3_bucket_name.txt"
}
