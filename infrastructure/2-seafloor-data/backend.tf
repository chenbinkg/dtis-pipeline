terraform {
  required_version = "= 1.5.6"
  backend "s3" {
    encrypt = true
    region         = "ap-southeast-2"
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 5.56.1"
    }
    local = {
      source  = "hashicorp/local"
      version = "= 2.5.2"
    }
  }
}
provider "aws" {
  region = "ap-southeast-2"
}
