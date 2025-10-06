import os
import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create a SageMaker client
sagemaker_client = boto3.client("sagemaker")

def lambda_handler(event, context):
    pipeline_name = os.environ.get("PIPELINE_NAME")
    
    # Get SSM parameters
    ssm_client = boto3.client('ssm')
    
    def get_ssm_parameter(param_name):
        try:
            response = ssm_client.get_parameter(Name=param_name, WithDecryption=True)
            return response['Parameter']['Value']
        except Exception as e:
            logger.error(f"Failed to get SSM parameter {param_name}: {e}")
            return ""
    
    if not pipeline_name:
        logger.error("Environment variable PIPELINE_NAME is not set.")
        return {"statusCode": 500, "body": "Missing PIPELINE_NAME environment variable."}

    logger.info("Received event: %s", json.dumps(event, indent=2))

    try:
        # Extract S3 bucket and key from S3 event
        s3_records = event.get('Records', [])
        if not s3_records:
            logger.error("No S3 records found in event")
            return {"statusCode": 400, "body": "No S3 records found"}
        
        s3_record = s3_records[0]['s3']
        s3_bucket = s3_record['bucket']['name']
        s3_key = s3_record['object']['key']
        
        logger.info(f"Processing S3 object: s3://{s3_bucket}/{s3_key}")
        
        # Get configuration from SSM
        mongodb_uri = get_ssm_parameter("/dtis/mongodb/mongo-uri")
        mongodb_db = get_ssm_parameter("/dtis/mongodb/mongo-db")
        mongodb_collection = get_ssm_parameter("/dtis/mongodb/dtis-taxonomy-collection")

        pipeline_parameters = [
            {"Name": "ProcessingInstanceCount", "Value": "1"},
            {"Name": "ProcessingInstanceType", "Value": "ml.m5.xlarge"},
            {"Name": "S3Bucket", "Value": s3_bucket},
            {"Name": "S3Key", "Value": s3_key},
            {"Name": "MongoDBURI", "Value": mongodb_uri},
            {"Name": "MongoDBDB", "Value": mongodb_db},
            {"Name": "Workers", "Value": "5"},
            {"Name": "MongoDBCollection", "Value": mongodb_collection}
        ]

        # Start the SageMaker pipeline execution
        response = sagemaker_client.start_pipeline_execution(
            PipelineName=pipeline_name,
            PipelineParameters=pipeline_parameters,
        )

        logger.info("SageMaker taxonomy processing pipeline execution started:", response)

        return {
            'statusCode': 200,
            'body': json.dumps('SageMaker taxonomy processing pipeline execution started successfully!')
        }

    except Exception as e:
        logger.error(f"Error processing event or starting SageMaker taxonomy processing pipeline: {e}")
        raise e