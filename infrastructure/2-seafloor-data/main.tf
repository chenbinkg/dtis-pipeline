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

resource "aws_sqs_queue" "queue" {
  name                       =   "dtis-ofop-${var.environment}"
  # Any message that is sent to the queue remains invisible to consumers for the duration of this delay period.
  delay_seconds              = 10
  # It determines the duration during which a message remains invisible to other consumers after it has been retrieved by a consumer. This allows the consumer enough time to process the message before it becomes available for other consumers to retrieve.
  visibility_timeout_seconds = 60*60*2
  # The maximum size of the message that can be sent to the SQS queue. If a message exceeds this size, it will be rejected.
  max_message_size           = 2048
  # This argument sets the duration, for which messages are retained in the queue. After this duration, any messages that haven’t been processed or deleted will be automatically removed from the queue.
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 2
  # enables encryption
  sqs_managed_sse_enabled = true

  tags          = local.tags
}

# SQS access policy
data "aws_iam_policy_document" "sqs_policy" {
  statement {
    sid    = "sqs"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage"
    ]
    resources = [
      aws_sqs_queue.queue.arn
    ]
  }
  statement {
    sid    = "AllowWritesFromS3"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    actions = [
      "sqs:SendMessage"
    ]
    resources = [
      aws_sqs_queue.queue.arn
    ]

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.raw_data.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# SQS access policy
resource "aws_sqs_queue_policy" "sqs_policy" {
  queue_url = aws_sqs_queue.queue.id
  policy    = data.aws_iam_policy_document.sqs_policy.json
}
