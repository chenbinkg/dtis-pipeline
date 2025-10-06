#!/bin/bash
PROJECT_NAME=${1:-data-platform-dtis}
ENVIRONMENT=${2:-prod}
AWS_REGION=${3:-ap-southeast-2}
# Set variables
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPOSITORY="${PROJECT_NAME}-${ENVIRONMENT}-annotation"
IMAGE_TAG="latest"

# Create the ECR repository if it doesn't exist
aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} || \
aws ecr create-repository --repository-name ${ECR_REPOSITORY}

# Get login credentials for ECR
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# # Prepare docker build directory
# mkdir -p code/docker/checkpoints
# cp ./checkpoints/checkpoint_best_regular.pth code/docker/checkpoints/
# cp requirements.txt code/docker/
# cp *.py code/docker/

# Build the Docker image
docker build -t ${ECR_REPOSITORY}:${IMAGE_TAG} code/docker

# Tag the image for ECR
docker tag ${ECR_REPOSITORY}:${IMAGE_TAG} ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${IMAGE_TAG}

# Push the image to ECR
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${IMAGE_TAG}

echo "Image successfully pushed to ECR"