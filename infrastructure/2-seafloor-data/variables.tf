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