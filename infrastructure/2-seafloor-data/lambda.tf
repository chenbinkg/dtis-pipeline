### Lambda logging configuration

# This is to optionally manage the CloudWatch Log Group for the Lambda Function.
# If skipping this resource configuration, also add "logs:CreateLogGroup" to the IAM policy below.
resource "aws_cloudwatch_log_group" "dtis_lambda" {
  name              = "/aws/lambda/dtis-ofop-${var.environment}"
  retention_in_days = 90
  tags          = local.tags
}

# See also the following AWS managed policy: AWSLambdaBasicExecutionRole
data "aws_iam_policy_document" "dtis_lambda_logging" {
  statement {
    effect = "Allow"

    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["arn:aws:logs:*:*:*"]
  }
}

resource "aws_iam_policy" "dtis_lambda_logging" {
  name        = "dtis-lambda-logging-${var.environment}"
  path        = "/"
  description = "IAM policy for logging from a lambda"
  policy      = data.aws_iam_policy_document.dtis_lambda_logging.json
  tags          = local.tags
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.iam_for_lambda.name
  policy_arn = aws_iam_policy.dtis_lambda_logging.arn
}

### End of Lambda logging configuration

data "aws_iam_policy_document" "dtis_lambda_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

# lambda execution role for ingress lambda function
resource "aws_iam_role" "iam_for_lambda" {
  name               = "dtis-lambda-execution-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.dtis_lambda_assume_role.json
  tags          = local.tags
}

data "aws_iam_policy_document" "dtis_lambda_sqs_permissions" {
  statement {
    effect = "Allow"
    resources = [ aws_sqs_queue.queue.arn ]
    actions = ["sqs:*"]
  }
}

resource "aws_iam_policy" "dtis_lambda_sqs_permissions" {
  name        = "dtis-lambda-sqs-${var.environment}"
  path        = "/"
  policy      = data.aws_iam_policy_document.dtis_lambda_sqs_permissions.json
  tags          = local.tags
}

resource "aws_iam_role_policy_attachment" "lambda_sqs_role_policy" {
  role       = aws_iam_role.iam_for_lambda.name
  policy_arn = aws_iam_policy.dtis_lambda_sqs_permissions.arn
}

data "aws_iam_policy_document" "dtis_lambda_s3_permissions" {
  statement {
    effect = "Allow"
    resources = [ "${aws_s3_bucket.raw_data.arn}/*" ]
    actions = ["s3:GetObject", "s3:GetObjectTagging"]
  }
}

resource "aws_iam_policy" "dtis_lambda_s3_permissions" {
  name        = "dtis-lambda-s3-${var.environment}"
  path        = "/"
  policy      = data.aws_iam_policy_document.dtis_lambda_s3_permissions.json
  tags          = local.tags
}

resource "aws_iam_role_policy_attachment" "lambda_s3_role_policy" {
  role       = aws_iam_role.iam_for_lambda.name
  policy_arn = aws_iam_policy.dtis_lambda_s3_permissions.arn
}

## use this if we want Terraform to generate the zip file (instead of us
## doing it in Bash):
# data "archive_file" "lambda" {
#   type        = "zip"
#   source_file = "lambda_function.py"
#   output_path = "lambda_function.zip"
# }

data "local_file" "lambda_function_zip" {
  filename = "lambda_function.zip"
}

resource "aws_lambda_function" "dtis" {
	depends_on = [
		aws_iam_role_policy_attachment.lambda_logs,
		aws_cloudwatch_log_group.dtis_lambda,
	]

  # If the file is not in the current working directory you will need to include a
  # path.module in the filename.
  filename      = "lambda_function.zip"
  function_name = "dtis-ofop-${var.environment}"
  role          = aws_iam_role.iam_for_lambda.arn
  handler       = "lambda_function_mongoDB_schema.lambda_handler"

  ## use this if we want Terraform to generate the zip file (instead of us
  ## doing it in Bash):
  # source_code_hash = data.archive_file.lambda.output_base64sha256

  source_code_hash = data.local_file.lambda_function_zip.content_sha256

  runtime = "python3.9"

  # TODO bump it for batching
  reserved_concurrent_executions = 1
  # defaults to 3 (seconds)
  timeout = 900
  # defaults to 128 (MB)
  memory_size = 1024

  environment {
    variables = {
			MONGODB_URI = "mongodb+srv://DTISFederation:2LzFpNbdRfvxnQze@serverlessinstance0.ta8golw.mongodb.net/"
			MONGODB_DATABASE = "dtistest"
			MONGODB_COLLECTION = "DTISOFOP"
			INGRESS_COLLECTION_DTIS = "ingresses"
    }
  }
  tags = local.tags
}


  # TODO: make it work with checkov security scanning

### SQS event source mapping to Preprocessing Lambda function
resource "aws_lambda_event_source_mapping" "dtis" {
  event_source_arn = aws_sqs_queue.queue.arn
  function_name    = aws_lambda_function.dtis.arn
  enabled = true
}

### MediaConvert role and policy
resource "aws_iam_role" "mediaconvert_role" {
  name = "dtis-mediaconvert-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "mediaconvert.amazonaws.com"
        },
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_policy" "mediaconvert_policy" {
  name        = "dtis-mediaconvert-${var.environment}"
  description = "Policy for MediaConvert to access S3 and CloudWatch"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject"
        ],
        Resource = [ "${aws_s3_bucket.raw_data.arn}/*" ]
      },
      {
        Effect = "Allow",
        Action = [
          "mediaconvert:*"
        ],
        Resource = [ "*" ]
      },
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "mediaconvert_role_policy" {
  role       = aws_iam_role.mediaconvert_role.name
  policy_arn = aws_iam_policy.mediaconvert_policy.arn
}


### MediaConvert lambda function
# create lambda execution role for mediaconvert lambda function
resource "aws_iam_role" "iam_for_lambda_mediaconvert" {
  name               = "dtis-lambda-mediaconvert-execution-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.dtis_lambda_assume_role.json
  tags          = local.tags
}

# grant lambda execution role access to SQS
resource "aws_iam_role_policy_attachment" "lambda_medianconvert_sqs_role_policy" {
  role       = aws_iam_role.iam_for_lambda_mediaconvert.name
  policy_arn = aws_iam_policy.dtis_lambda_sqs_permissions.arn
}

# Attach mediaconvert policy to the lambda execution role
resource "aws_iam_role_policy_attachment" "lambda_mediaconvert_execution" {
  role       = aws_iam_role.iam_for_lambda_mediaconvert.name
  policy_arn = aws_iam_policy.mediaconvert_policy.arn
}

# Define PassRole policy for MediaConvert to assume the lambda execution role
data "aws_iam_policy_document" "pass_mediaconvert_role" {
  statement {
    effect = "Allow"
    resources = [ "${aws_iam_role.mediaconvert_role.arn}" ]
    actions = ["iam:PassRole"]
  }
}

resource "aws_iam_policy" "pass_mediaconvert_permissions" {
  name        = "dtis-lambda-mediaconvert-${var.environment}"
  path        = "/"
  policy      = data.aws_iam_policy_document.pass_mediaconvert_role.json
  tags          = local.tags
}

resource "aws_iam_role_policy_attachment" "lambda_mediaconvert_role_policy" {
  role       = aws_iam_role.iam_for_lambda_mediaconvert.name
  policy_arn = aws_iam_policy.pass_mediaconvert_permissions.arn
}

# This is to optionally manage the CloudWatch Log Group for the Lambda Function.
# If skipping this resource configuration, also add "logs:CreateLogGroup" to the IAM policy below.
resource "aws_cloudwatch_log_group" "dtis_mediaconvert_lambda_loggroup" {
  name              = "/aws/lambda/dtis-ofop-mediaconvert-${var.environment}"
  retention_in_days = 90
  tags          = local.tags
}

data "local_file" "lambda_mediaconvert_zip" {
  filename = "lambda_media_convert.zip"
}

resource "aws_lambda_function" "dtis_mediaconvert" {
	depends_on = [
		aws_iam_role_policy_attachment.lambda_logs,
		aws_cloudwatch_log_group.dtis_mediaconvert_lambda_loggroup,
	]

  # If the file is not in the current working directory you will need to include a
  # path.module in the filename.
  filename      = "lambda_media_convert.zip"
  function_name = "dtis-ofop-mediaconvert-${var.environment}"
  role          = aws_iam_role.iam_for_lambda_mediaconvert.arn
  handler       = "lambda_function_media_convert.lambda_handler"

  ## use this if we want Terraform to generate the zip file (instead of us
  ## doing it in Bash):
  # source_code_hash = data.archive_file.lambda.output_base64sha256

  source_code_hash = data.local_file.lambda_mediaconvert_zip.content_sha256

  runtime = "python3.9"

  # TODO bump it for batching
  reserved_concurrent_executions = 1
  # defaults to 3 (seconds)
  timeout = 900
  # defaults to 128 (MB)
  memory_size = 1024

  tags = local.tags
}

# ### SQS event source mapping to Mediaconvert Lambda function
# resource "aws_lambda_event_source_mapping" "dtis_mediaconvert" {
#   event_source_arn = aws_sqs_queue.queue.arn
#   function_name    = aws_lambda_function.dtis_mediaconvert.arn
#   enabled = true
# }

# IAM policy document to invoke lambda function for media convert
data "aws_iam_policy_document" "invoke_mediaconvert_lambda_permissions" {
  statement {
    effect = "Allow"
    resources = [ aws_lambda_function.dtis_mediaconvert.arn ]
    actions = ["lambda:InvokeFunction"]
  }
}

# IAM policy for main lambda to invoke lambda function for media convert
resource "aws_iam_policy" "invoke_media_convert_lambda_permissions" {
  name        = "dtis-lambda-invoke-lambda-${var.environment}"
  path        = "/"
  policy      = data.aws_iam_policy_document.invoke_mediaconvert_lambda_permissions.json
  tags          = local.tags
}

# attach the policy to the main lambda role
resource "aws_iam_role_policy_attachment" "invoke_mediaconvert_lambda_policy" {
  role       = aws_iam_role.iam_for_lambda.name
  policy_arn = aws_iam_policy.invoke_media_convert_lambda_permissions.arn
}
