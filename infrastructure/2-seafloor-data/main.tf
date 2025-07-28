locals {
  tags = {
    creation_method  = "terraform"
    Authors       = var.authors
    ServiceOwner = var.service_owner
    ServiceCategory = var.service_category
    Project = var.project_id
    ProjectName = var.project_name
    Environment = var.environment
  }
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_s3_bucket" "raw_data" {
  #checkov:skip=CKV_AWS_18: "Ensure the S3 bucket has access logging enabled" - no need here, use Amazon CloudTrail instead
  #checkov:skip=CKV_AWS_144: "Ensure that S3 bucket has cross-region replication enabled"
  #checkov:skip=CKV2_AWS_61: "Ensure that an S3 bucket has a lifecycle configuration"
  #checkov:skip=CKV2_AWS_62: "Ensure S3 buckets should have event notifications enabled"
  bucket        = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-raw-data"
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

resource "aws_s3_bucket_lifecycle_configuration" "intelligent_tiering_archive" {
  bucket = aws_s3_bucket.raw_data.id

  rule {
    id     = "IntelligentTieringArchive"
    status = "Enabled"

    transition {
      days          = 30                       // Transition after 30 days
      storage_class = "INTELLIGENT_TIERING"
    }
  }
}

resource "aws_sqs_queue" "queue" {
  name                       =   "${local.name_prefix}-sqs-queue"
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

resource "aws_s3_bucket_notification" "bucket_notification" {
  bucket = aws_s3_bucket.raw_data.id

  queue {
    queue_arn     = aws_sqs_queue.queue.arn
    # https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-how-to-event-types-and-destinations.html
    events        = ["s3:ObjectCreated:*"]
  }
}

# S3 bucket for dtis model
resource "aws_s3_bucket" "dtis_model" {
  bucket        = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-model-data"
  tags          = local.tags
  force_destroy = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "dtis_model" {
  bucket = aws_s3_bucket.dtis_model.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_versioning"  "dtis_model" {
  bucket = aws_s3_bucket.dtis_model.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "dtis_model_s3_setup" {
  bucket                  = aws_s3_bucket.dtis_model.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "dtis_model" {
  bucket = aws_s3_bucket.dtis_model.id

  rule {
    id     = "IntelligentTieringArchive"
    status = "Enabled"

    transition {
      days          = 30   // Transition after 30 days
      storage_class = "INTELLIGENT_TIERING"
    }
  }
}

# S3 bucket policy for data access to rekognition
# This policy allows the Rekognition service to access the S3 bucket for read/write operations
# for the dtis model and annotations
resource "aws_s3_bucket_policy" "rekognition_s3_access_policy" {
  bucket = aws_s3_bucket.dtis_model.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject",
          "s3:DeleteObject"
        ],
        Effect   = "Allow",
        Principal = {
          AWS = aws_iam_role.rekognition_role.arn
        },
        Resource = [
          "${aws_s3_bucket.dtis_model.arn}",
          "${aws_s3_bucket.dtis_model.arn}/*"
        ]
      },
    ]
  })
}

# IAM role for Rekognition Custom Labels
# This role allows Rekognition to access the S3 bucket for read/write operations
resource "aws_iam_role" "rekognition_role" {
  name = "${local.name_prefix}-rekognition-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect   = "Allow",
        Principal = {
          Service = "rekognition.amazonaws.com"
        }
      },
    ]
  })

  tags = local.tags
}

# IAM policy for Rekognition Custom Label
# This policy allows Rekognition to read/write access to dtis-model bucket
# and read access to raw data bucket
resource "aws_iam_policy" "rekognition_policy" {
  name        = "${local.name_prefix}-rekognition-custom-label-policy"
  description = "Permissions for Rekognition Custom Labels to access S3 buckets"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject",
          "s3:DeleteObject"
        ],
        Effect   = "Allow",
        Resource = [
          "${aws_s3_bucket.dtis_model.arn}",
          "${aws_s3_bucket.dtis_model.arn}/*"
        ]
      },
      {
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Effect   = "Allow",
        Resource = [
          "${aws_s3_bucket.raw_data.arn}",
          "${aws_s3_bucket.raw_data.arn}/*"
        ]
      },
      {
        Action = [
          "rekognition:CreateProject",
          "rekognition:DescribeProject",
          "rekognition:UpdateProject",
          "rekognition:DeleteProject",
          "rekognition:CreateDataset",
          "rekognition:DescribeDataset",
          "rekognition:UpdateDatasetEntries",
          "rekognition:DeleteDataset",
          "rekognition:CreateProjectVersion",
          "rekognition:DescribeProjectVersion",
          "rekognition:StartProjectVersion",
          "rekognition:StopProjectVersion",
          "rekognition:DeleteProjectVersion",
          "rekognition:DetectCustomLabels"
        ],
        Effect   = "Allow",
        Resource = "*" # Consider narrowing down the scope if possible
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "rekognition_policy_attachment" {
  role       = aws_iam_role.rekognition_role.name
  policy_arn = aws_iam_policy.rekognition_policy.arn
}