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

  environment {
    variables = {
      #  S3_BUCKET_NAME = "${data.aws_s3_bucket.raw_data.id}"
			MONGODB_URI = "TODO"
			MONGODB_DATABASE = "TODO"
			MONGODB_COLLECTION = "TODO"
			INGRESS_COLLECTION_DTIS = "TODO"
      # TODO
      SQS_QUEUE_NAME = "dtis-ofop-testing"
    }
  }
  tags          = local.tags
}


# TODO: make it work with checkov security scanning

### SQS event source mapping to Lambda
resource "aws_lambda_event_source_mapping" "dtis" {
  event_source_arn = aws_sqs_queue.queue.arn
  function_name    = aws_lambda_function.dtis.arn
  enabled = true
}
