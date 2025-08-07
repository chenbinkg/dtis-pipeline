# SSM Parameters for configuration
resource "aws_ssm_parameter" "aws_region" {
  name  = "/biigle/aws-region"
  type  = "String"
  value = var.aws_region
  tags  = local.tags
}
# These parameters need to be set manually or through the upload script
resource "aws_ssm_parameter" "mongo_uri" {
  name  = "/biigle/mongo-uri"
  type  = "SecureString"
  value = var.mongo_uri
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_db" {
  name  = "/biigle/mongo-db"
  type  = "String"
  value = var.mongo_db
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_api_url" {
  name  = "/biigle/api-url"
  type  = "String"
  value = var.biigle_api_url
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_api_email" {
  name  = "/biigle/api-email"
  type  = "String"
  value = var.biigle_api_email
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_api_token" {
  name  = "/biigle/api-token"
  type  = "SecureString"
  value = var.biigle_api_token
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_label_tree_id" {
  name  = "/biigle/label-tree-id"
  type  = "String"
  value = tostring(var.biigle_label_tree_id)
  tags  = local.tags
  
}

resource "aws_ssm_parameter" "biigle_disk_id" {
  name  = "/biigle/disk-id"
  type  = "String"
  value = tostring(var.biigle_disk_id)
  tags  = local.tags
  
}

resource "aws_ssm_parameter" "biigle_user_pattern" {
  name  = "/biigle/user-pattern"
  type  = "String"
  value = var.biigle_user_pattern
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_user_lastname" {
  name  = "/biigle/user-lastname"
  type  = "String"
  value = var.biigle_user_lastname
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_anno_session_collection_name" {
  name  = "/biigle/anno-session-collection-name"
  type  = "String"
  value = var.biigle_anno_session_collection_name
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_create_user_disk_secret_name" {
  name  = "/biigle/create-user-disk-secret-name"
  type  = "String"
  value = var.biigle_create_user_disk_secret_name
  tags  = local.tags
}