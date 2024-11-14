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
  name        = "dtis_lambda_logging_${var.environment}"
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
  name               = "iam_for_lambda"
  assume_role_policy = data.aws_iam_policy_document.dtis_lambda_assume_role.json
  tags          = local.tags
}

data "archive_file" "lambda" {
  type        = "zip"
  source_file = "lambda_function.py"
  output_path = "lambda_function.zip"
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
  handler       = "lambda_function.lambda_handler"

  source_code_hash = data.archive_file.lambda.output_base64sha256

  runtime = "python3.12"

  # TODO bump it for batching
  reserved_concurrent_executions = 1

  environment {
    variables = {
      #  S3_BUCKET_NAME = "${data.aws_s3_bucket.raw_data.id}"
			MONGODB_URI = "TODO"
			MONGODB_DATABASE = "TODO"
			MONGODB_COLLECTION = "TODO"
			INGRESS_COLLECTION_DTIS = "TODO"
    }
  }
  tags          = local.tags
}
