# EventBridge Rule to capture MediaConvert Job Completion
resource "aws_cloudwatch_event_rule" "mediaconvert_complete_rule" {
  name          = "${local.name_prefix}-mediaconvert-job-complete-rule"
  description   = "Captures MediaConvert job completion events to trigger Lambda function"
  event_bus_name = "default"

  event_pattern = jsonencode({
    "source": ["aws.mediaconvert"],
    "detail-type": ["MediaConvert Job State Change"],
    "detail": {
      "status": ["COMPLETE"]
    }
  })

  tags = {
    Name = "MediaConvert Job Complete Rule"
  }
}

# create event target fot the mediaconvert job completion rule 
# to run the lambda function "pretrained annotation"
resource "aws_cloudwatch_event_target" "lambda-function-pretrained-annotation-target" {
  target_id = "lambda-function-pretrained-annotation"
  rule      = aws_cloudwatch_event_rule.mediaconvert_complete_rule.name
  arn       = aws_lambda_function.pretrained_annotation.arn
}

# Permission for EventBridge to invoke Lambda function for pretrained annotation
resource "aws_lambda_permission" "allow_invoke_pretrained_annotation_lambda" {
  statement_id  = "${local.name_prefix}-allow-invoke-pretrained-annotation-lambda"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pretrained_annotation.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.mediaconvert_complete_rule.arn
}

# CloudWatch Logs Log Group for EventBridge Events
resource "aws_cloudwatch_log_group" "mediaconvert_events_log_group" {
  # Log group names for EventBridge targets often start with /aws/events/
  # for automatic permission handling by AWS, though explicit policies are safer in IaC.
  name = "/aws/events/mediaconvert-job-complete-events"
  retention_in_days = 14 # Or your desired retention period

  tags = {
    Name = "MediaConvert Job Complete Events Log Group"
  }
}

# Resource Policy to allow EventBridge to write to the Log Group
# This is necessary when setting up the target via IaC like Terraform.
data "aws_iam_policy_document" "eventbridge_to_logs_policy" {
  statement {
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "delivery.logs.amazonaws.com"] # Include delivery.logs.amazonaws.com
    }

    resources = [
      "${aws_cloudwatch_log_group.mediaconvert_events_log_group.arn}:*"
    ]
  }
}

resource "aws_cloudwatch_log_resource_policy" "eventbridge_to_logs_resource_policy" {
  policy_name = "${local.name_prefix}-eventbridge-to-logs-policy"
  policy_document = data.aws_iam_policy_document.eventbridge_to_logs_policy.json
}


# EventBridge Target to send events to CloudWatch Logs
resource "aws_cloudwatch_event_target" "log_mediaconvert_complete_events" {
  # Use the name or ID of the rule
  rule = aws_cloudwatch_event_rule.mediaconvert_complete_rule.name
  # Target must have a unique ID within the rule
  target_id = "SendToCloudWatchLogs"
  # ARN of the CloudWatch Logs log group
  arn = aws_cloudwatch_log_group.mediaconvert_events_log_group.arn

}