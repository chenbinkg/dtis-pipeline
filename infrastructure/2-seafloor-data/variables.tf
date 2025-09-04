variable "project_name" {
  type = string
  default = "data-platform-dtis"
}

variable "project_id" {
  type = string
  default = "FPEI2606"
}

variable "environment" {
  type = string
  default = "dev"
}

variable "service_owner" {
  type = string
  default = "Jochen Schmidt"
}

variable "service_category" {
  type = string
  default = "dtis-ofop-data"
}

variable "authors" {
  type = string
  default = "Bryce Chen/Alan Tan/Yinjing Lin"
}

variable "aws_region" {
  type    = string
  default = "ap-southeast-2"
}

variable "mongo_uri" {
  type        = string
  description = "MongoDB connection URI"
  default     = "mongodb://localhost:27017"
  sensitive   = true
}

variable "mongo_db" {
  type        = string
  description = "MongoDB database name"
  default     = "dtis-data"
}

variable "mongo_dtis_master_collection" {
  type        = string
  description = "MongoDB collection for DTIS master data"
  default     = "dtis_master"
}

variable "mongo_biigle_anno_session_collection" {
  type        = string
  description = "Name of the MongoDB collection for Biigle annotation sessions"
  default     = "dtis_biigle_annotation_session"
}

variable "mongo_dtis_ofop_obser_collection" {
  type        = string
  description = "MongoDB collection for DTIS OFOP observations"
  default     = "dtis_ofop_obser"
}

variable "mongo_dtis_video_collection" {
  type        = string
  description = "MongoDB collection for DTIS video data"
  default     = "dtis_videos"
}

variable "mongo_dtis_ofop_prot_collection" {
  type        = string
  description = "MongoDB collection for DTIS protocol data"
  default     = "dtis_ofop_prot"
}

variable "mongo_dtis_metadata_collection" {
  type        = string
  description = "MongoDB collection for DTIS metadata"
  default     = "dtis_metadata"
}

variable "mongo_dtis_stills_collection" {
  type        = string
  description = "MongoDB collection for DTIS still images"
  default     = "dtis_stills"
}

variable "mongo_dtis_taxonomy_collection" {
  type        = string
  description = "MongoDB collection for DTIS taxonomy data"
  default     = "dtis_taxonomy"
}

variable "biigle_api_url" {
  type        = string
  description = "Base URL for the Biigle API"
  default     = "https://biigle.de/api/v1"
  
}

variable "biigle_api_email" {
  type        = string
  description = "Email for Biigle API authentication"
  default     = "bryce.chen@niwa.co.nz"
}

variable "biigle_api_token" {
  type        = string
  description = "Token for Biigle API authentication"
  default     = "uLYOXorOXzZvr7dGBx2coOSFr2nYq168"
  sensitive   = true 
}

variable "biigle_label_tree_id" {
  type        = number
  description = "ID of the label tree in Biigle"
  default     = 3270
  
}

variable "biigle_disk_id" {
  type        = number
  description = "ID of the storage disk in Biigle"
  default     = 107
  
}

variable "biigle_user_pattern" {
  type        = string
  description = "Pattern for Biigle usernames"
  default     = "Caroline"
}

variable "biigle_user_lastname" {
  type        = string
  description = "Last name for Biigle users"
  default     = "Chin"
  
}

variable "biigle_create_user_disk_secret_name" {
  type        = string
  description = "Name of the AWS Secrets Manager secret for Biigle create user disk"
  default     = "aws-credentials/biigle/create-user-disk"
}