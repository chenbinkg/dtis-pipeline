#!/bin/bash
set -e

ENVIRONMENT=${1:-dev}
AWS_REGION=${2:-ap-southeast-2}
# Set variables
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPOSITORY="dtis-annotation-${ENVIRONMENT}"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
IMAGE_TAG="latest"

# Create the ECR repository if it doesn't exist
aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} || \
aws ecr create-repository --repository-name ${ECR_REPOSITORY}

# Get login credentials for ECR
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Enable Docker Buildx if not already enabled
docker buildx create --name mybuilder --driver docker-container --use > /dev/null 2>&1
docker buildx inspect --bootstrap > /dev/null 2>&1

# Build and push the multi-platform Docker image using Buildx
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  --no-cache -t ${ECR_URI}:${IMAGE_TAG} \
  --push \
  code/docker # Context path to your Dockerfile

echo "Multi-architecture image successfully built and pushed to ECR"