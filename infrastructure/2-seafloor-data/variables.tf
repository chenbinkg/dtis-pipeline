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
  default     = 84
  
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

variable "biigle_anno_session_collection_name" {
  type        = string
  description = "Name of the MongoDB collection for Biigle annotation sessions"
  default     = "dtis_biigle_annotation_session"
  
}

variable "biigle_create_user_disk_secret_name" {
  type        = string
  description = "Name of the AWS Secrets Manager secret for Biigle create user disk"
  default     = "aws-credentials/biigle/create-user-disk"
}