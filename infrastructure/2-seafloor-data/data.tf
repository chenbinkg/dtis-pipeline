# Data sources for dynamic partition, region, and account ID
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}