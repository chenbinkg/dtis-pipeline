#!/bin/bash

# Set variables
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="ap-southeast-2"  # Change to your region
ECR_REPOSITORY="dtis-annotation-container"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
IMAGE_TAG="latest"

# Create the ECR repository if it doesn't exist
aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} || \
aws ecr create-repository --repository-name ${ECR_REPOSITORY}

# Get login credentials for ECR
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Prepare docker build directory (assuming your Dockerfile and code are in 'code/docker')
# If your Dockerfile is in the root, adjust the context path in the build command
# mkdir -p code/docker/checkpoints
# cp ./checkpoints/checkpoint_best_regular.pth code/docker/checkpoints/
# cp requirements.txt code/docker/
# cp *.py code/docker/

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