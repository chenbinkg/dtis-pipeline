# SSM Parameters for configuration
resource "aws_ssm_parameter" "aws_region" {
  name  = "/dtis/biigle/aws-region"
  type  = "String"
  value = var.aws_region
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_api_url" {
  name  = "/dtis/biigle/api-url"
  type  = "String"
  value = var.biigle_api_url
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_api_email" {
  name  = "/dtis/biigle/api-email"
  type  = "String"
  value = var.biigle_api_email
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_api_token" {
  name  = "/dtis/biigle/api-token"
  type  = "SecureString"
  value = var.biigle_api_token
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_label_tree_id" {
  name  = "/dtis/biigle/label-tree-id"
  type  = "String"
  value = tostring(var.biigle_label_tree_id)
  tags  = local.tags
  
}

resource "aws_ssm_parameter" "biigle_disk_id" {
  name  = "/dtis/biigle/disk-id"
  type  = "String"
  value = tostring(var.biigle_disk_id)
  tags  = local.tags
  
}

resource "aws_ssm_parameter" "biigle_user_pattern" {
  name  = "/dtis/biigle/user-pattern"
  type  = "String"
  value = var.biigle_user_pattern
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_user_lastname" {
  name  = "/dtis/biigle/user-lastname"
  type  = "String"
  value = var.biigle_user_lastname
  tags  = local.tags
}

resource "aws_ssm_parameter" "biigle_create_user_disk_secret_name" {
  name  = "/dtis/biigle/create-user-disk-secret-name"
  type  = "String"
  value = var.biigle_create_user_disk_secret_name
  tags  = local.tags
}

# These parameters need to be set manually or through the upload script
resource "aws_ssm_parameter" "mongo_uri" {
  name  = "/dtis/mongodb/mongo-uri"
  type  = "SecureString"
  value = var.mongo_uri
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_db" {
  name  = "/dtis/mongodb/mongo-db"
  type  = "String"
  value = var.mongo_db
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_dtis_ofop_prot_collection" {
  name  = "/dtis/mongodb/dtis-ofop-prot-collection"
  type  = "String"
  value = var.mongo_dtis_ofop_prot_collection
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_biigle_anno_session_collection" {
  name  = "/dtis/mongodb/biigle-anno-session-collection"
  type  = "String"
  value = var.mongo_biigle_anno_session_collection
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_dtis_master_collection" {
  name  = "/dtis/mongodb/dtis-master-collection"
  type  = "String"
  value = var.mongo_dtis_master_collection
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_dtis_ofop_obser_collection" {
  name  = "/dtis/mongodb/dtis-ofop-obser-collection"
  type  = "String"
  value = var.mongo_dtis_ofop_obser_collection
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_dtis_video_collection" {
  name  = "/dtis/mongodb/dtis-video-collection"
  type  = "String"
  value = var.mongo_dtis_video_collection
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_dtis_metadata_collection" {
  name  = "/dtis/mongodb/dtis-metadata-collection"
  type  = "String"
  value = var.mongo_dtis_metadata_collection
  tags  = local.tags
}

resource "aws_ssm_parameter" "mongo_dtis_stills_collection" {
  name  = "/dtis/mongodb/dtis-stills-collection"
  type  = "String"
  value = var.mongo_dtis_stills_collection
  tags  = local.tags
}

 resource "aws_ssm_parameter" "ecr_repository" {
  name  = "/dtis/pipeline/ecr-repository"
  type  = "String"
  value = var.ecr_repository
  tags  = local.tags
 }