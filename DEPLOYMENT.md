# NIWA DTIS Data Platform - Deployment Guide

This guide provides step-by-step instructions for deploying the NIWA Ocean Floor DTIS Data Platform to production.

## Prerequisites

- AWS CLI configured with appropriate permissions
- Terraform >= 1.5.6
- Docker (for ECR image builds)
- Access to GitHub repository with appropriate secrets configured
- MongoDB Atlas cluster (or self-hosted MongoDB)

## Production Deployment Procedures

### 1. Create Terraform State Infrastructure (Layer 1)

First, set up the foundational S3 bucket for Terraform remote state:

```bash
cd infrastructure/1-terraform-init
export PROJECT_NAME=data-platform-dtis
export ENVIRONMENT=prod
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

terraform init
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

This creates:
- S3 bucket for Terraform state: `${PROJECT_NAME}-${ENVIRONMENT}-${AWS_ACCOUNT_ID}-terraform-state`
- DynamoDB table for state locking

### 2. Create AWS Secrets Manager Secrets

Create the required secrets for BIIGLE storage disk access:

```bash
aws secretsmanager create-secret \
    --region ap-southeast-2 \
    --name "aws-credentials/biigle/create-user-disk" \
    --description "AWS Access Key ID and Secret Access Key for BIIGLE storage disk creation" \
    --secret-string '{"access_key_id":"AKIA...","secret_access_key":"..."}'
```

### 3. Configure GitHub Environment Secrets

Set up GitHub repository secrets for the `prod` environment:

**Required Secrets:**
- `AWS_ACCESS_KEY_ID`: AWS access key for production account
- `AWS_SECRET_ACCESS_KEY`: AWS secret key for production account  
- `MONGO_URI`: MongoDB connection string (e.g., `mongodb+srv://username:password@cluster.mongodb.net`)

**GitHub Configuration:**
1. Go to repository Settings → Environments
2. Create/configure `prod` environment
3. Add the above secrets to the `prod` environment

### 4. Deploy Production Infrastructure via GitHub Actions

Push to the `prod` branch to trigger automated deployment:

```bash
git checkout prod
git push origin prod
```

The GitHub Actions pipeline will:
1. Run security scans (Checkov, ShellCheck)
2. Execute unit tests
3. Package Lambda functions
4. Deploy infrastructure via Terraform
5. Create all AWS resources (S3, Lambda, SQS, IAM roles, etc.)

### 5. Data Migration (Optional)

If migrating from existing systems:

```bash
# Export data from existing MongoDB
mongodump --uri="mongodb://old-cluster" --db=old-database

# Import to new MongoDB
mongorestore --uri="${MONGO_URI}" --db=dtis-data dump/old-database/

# Sync S3 data if needed
aws s3 sync s3://old-bucket/ s3://data-platform-dtis-prod-${AWS_ACCOUNT_ID}-raw-data/
```

### 6. Build and Deploy ECR Container Images

Build the Docker image for SageMaker processing:

```bash
cd annotation/code/docker

# Build multi-architecture image
./docker_buildx.sh Dockerfile.slim

# Tag and push to ECR
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.ap-southeast-2.amazonaws.com/data-platform-dtis-prod-ecr-repo"

aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin ${ECR_REPO}
docker tag your-image:latest ${ECR_REPO}:latest
docker push ${ECR_REPO}:latest
```

### 7. Deploy SageMaker Inference Pipeline

Upload required model files and create the inference pipeline:

```bash
# Upload model checkpoint
aws s3 cp checkpoint_best_regular.pth s3://data-platform-dtis-prod-${AWS_ACCOUNT_ID}-model-data/models/RF-DETR/

# Upload test data (if needed)
aws s3 sync ./test-data/ s3://data-platform-dtis-prod-${AWS_ACCOUNT_ID}-model-data/pipeline_testdata/

# Create SageMaker pipeline
cd annotation
python sagemaker_create_inference_pipeline.py \
    --environment prod \
    --cruise TAN0616 \
    --station 095
```

**Pipeline Dependencies:**
- Model file: `s3://data-platform-dtis-prod-${AWS_ACCOUNT_ID}-model-data/models/RF-DETR/checkpoint_best_regular.pth`
- Input frames: `s3://data-platform-dtis-prod-${AWS_ACCOUNT_ID}-model-data/pipeline_testdata/TAN0616/095/video/TAN0616_095/frames/`
- Output annotations: `s3://data-platform-dtis-prod-${AWS_ACCOUNT_ID}-model-data/pipeline_testdata/TAN0616/095/video/TAN0616_095/annotations/`
- Matched annotations: `s3://data-platform-dtis-prod-${AWS_ACCOUNT_ID}-model-data/pipeline_testdata/TAN0616/095/video/TAN0616_095/matched_annotations/`

**Pipeline Components:**
1. **inference.py**: Generates annotations from model and frame images
2. **annotation_matching.py**: Matches annotations with MongoDB data (`dtis_ofop_obser`, `dtis_ofop_prot`)
3. **biigle_annotation_session.py**: Creates BIIGLE storage disk and annotation session

### 8. Deploy BIIGLE Annotation Retrieval Pipeline

```bash
python sagemaker_create_biigle_anno_retrieval_pipeline.py --environment prod
```

This pipeline:
- Triggered by EventBridge daily events
- Detects "Completed" BIIGLE annotation sessions
- Retrieves human-validated annotations
- Updates job status to "Retrieved"

### 9. Deploy Taxonomy Processing Pipeline

```bash
python sagemaker_create_taxonomy_pipeline.py --environment prod
```

This pipeline:
- Triggered by S3 ObjectCreated events for `biigle_labels.csv` in the model_data S3 bucket
- Processes taxonomy data via `generate_taxonomy_docs.py`
- Updates MongoDB `dtis_taxonomy` collection

## Human-in-the-Loop Annotation Workflow

### Overview
The platform supports human annotation through BIIGLE integration with the following workflow:

### 1. Initial Setup
After the inference pipeline runs:
- BIIGLE project/volume is created automatically
- Job status is set to **"Created"** in MongoDB
- Check status in `dtis-data` database, collection `dtis_biigle_annotation_session`

### 2. Human Annotation Process
1. **Access BIIGLE**: Log into the BIIGLE platform using provided credentials
2. **Perform Annotations**: Review and annotate the uploaded images/videos
3. **Mark Complete**: When finished, update the MongoDB record:
   ```javascript
   db.dtis_biigle_annotation_session.updateOne(
     {"biigle_project_id": PROJECT_ID},
     {"$set": {"biigle_annotation_job_status": "Completed"}}
   )
   ```

### 3. Automated Retrieval
- **Daily Job**: EventBridge triggers daily scans for "Completed" projects
- **Retrieval Process**: Automatically downloads validated annotations from BIIGLE
- **Status Update**: Job status changes to **"Retrieved"**
- **Output**: Creates `validated_annotation` folder in the video project directory

### 4. Active Learning Integration
The `validated_annotation` folder can be used as input for active learning pipelines to improve model performance.

## Configuration Parameters

### SSM Parameters
SSM parameter stores will be set up automatically when running terraform script, i.e. when pushing the changes of infra to production branch, avoid manual update of the SSM parameters as they could be override by default values set in terraform script whenenver there is a push to the prod repo. 
If you need to update the SSM parameters, make sure you update the terraform script and CICD pipeline.


## Monitoring and Maintenance

### CloudWatch Logs
Monitor Lambda function logs:
- `/aws/lambda/dtis-ofop-ingress-prod`
- `/aws/lambda/dtis-ofop-mediaconvert-prod`
- `/aws/lambda/dtis-taxonomy-prod`
- `/aws/lambda/dtis-biigle-anno-retrieval-prod`

### SageMaker Pipeline Monitoring
Check pipeline execution status:
```bash
aws sagemaker list-pipeline-executions --pipeline-name DTIS-Annotation-Pipeline-prod
```

### Data Upload
Scientists can upload data using the provided upload client at different repo https://github.com/niwa-advanced-technology/data-platform-dtis-upload.


## Troubleshooting

### Common Issues

1. **Lambda Timeout**: Increase timeout in `lambda.tf` if processing large files
2. **S3 Permissions**: Ensure IAM roles have proper S3 access
3. **MongoDB Connection**: Verify MongoDB URI and network access
4. **ECR Image**: Ensure Docker image is built for correct architecture

### Cleanup
To destroy the infrastructure:
```bash
export PROJECT_NAME=data-platform-dtis
export ENVIRONMENT=dev
export TF_VAR_environment=${ENVIRONMENT}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export BIIGLE_DISK_ID=$(aws ssm get-parameter --names /dtis/biigle/disk-id --region ap-southeast-2 --query Parameter.Value --output text)
export TF_VAR_biigle_disk_id=${BIIGLE_DISK_ID}

cd infrastructure/2-seafloor-data
terraform plan -destroy -out=plan.tfplan
terraform apply plan.tfplan
```

## Security Considerations

- All secrets stored in AWS Secrets Manager or SSM Parameter Store
- S3 buckets have public access blocked
- IAM roles follow least-privilege principle
- VPC endpoints recommended for production
- Enable CloudTrail for audit logging

## Support

For issues or questions:
1. Check CloudWatch logs for error details
2. Review GitHub Actions pipeline logs
3. Verify AWS resource configurations
4. Contact the development team with specific error messages