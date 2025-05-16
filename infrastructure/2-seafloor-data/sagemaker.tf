# --- IAM Role and Policy for SageMaker Pipeline ---
resource "aws_iam_role" "sagemaker_pipeline_role" {
  name = "DTIS-SageMakerPipelineExecutionRole-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "sagemaker.amazonaws.com"
        },
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_policy" "sagemaker_pipeline_policy" {
  name = "DTIS-SageMakerPipelineExecutionPolicy-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ],
        Resource = [
          aws_s3_bucket.dtis_model.arn,
          "${aws_s3_bucket.dtis_model.arn}/*",
          # Add ARNs for other S3 buckets your pipeline needs to access
        ]
      },
      {
        Effect = "Allow",
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability"
        ],
        Resource = "*" # Adjust this to be more restrictive if possible
      },
      {
        Effect = "Allow",
        Action = [
          "cloudwatch:PutMetricData",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents"
        ],
        Resource = "*" # Adjust this to be more restrictive if possible
      },
      {
        Effect = "Allow",
        Action = [
          "sagemaker:CreateTrainingJob",
          "sagemaker:DescribeTrainingJob",
          "sagemaker:StopTrainingJob",
          "sagemaker:CreateProcessingJob",
          "sagemaker:DescribeProcessingJob",
          "sagemaker:StopProcessingJob",
          "sagemaker:CreateTransformJob",
          "sagemaker:DescribeTransformJob",
          "sagemaker:StopTransformJob",
          "sagemaker:CreateModel",
          "sagemaker:CreateModelPackage",
          "sagemaker:CreateEndpointConfig",
          "sagemaker:CreateEndpoint",
          "sagemaker:InvokeEndpoint",
          "sagemaker:DeleteEndpointConfig",
          "sagemaker:DeleteEndpoint",
          "sagemaker:UpdateEndpoint",
          "sagemaker:DescribeEndpoint"
          # Add other SageMaker actions required by your pipeline steps
        ],
        Resource = "*" # Adjust this to be more restrictive if possible
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_pipeline_role_policy_attachment" {
  role       = aws_iam_role.sagemaker_pipeline_role.name
  policy_arn = aws_iam_policy.sagemaker_pipeline_policy.arn
}

# Policy Attachment for AmazonSageMakerFullAccess
resource "aws_iam_role_policy_attachment" "sagemaker_full_access_attachment" {
  # Attach to the role created in this file
  role       = aws_iam_role.sagemaker_pipeline_role.name
  # Reference the ARN of the AWS managed policy
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}