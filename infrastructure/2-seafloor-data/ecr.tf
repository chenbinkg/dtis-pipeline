# This resource creates an Amazon ECR repository
resource "aws_ecr_repository" "dtis_annotation_ecr" {
  name = "${local.name_prefix}-annotation"

  # Optional: Image tag mutability allows you to overwrite tags.
  # "IMMUTABLE" prevents tags from being overwritten.
  image_tag_mutability = "MUTABLE"

  # Optional: Configure image scanning on push
  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.tags
}
