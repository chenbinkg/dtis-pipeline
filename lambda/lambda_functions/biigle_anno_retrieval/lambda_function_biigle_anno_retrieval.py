import os
import json
import boto3
from pymongo.mongo_client import MongoClient
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
        # Get MongoDB configuration
        mongodb_uri = get_ssm_parameter("/dtis/mongodb/mongo-uri")
        mongodb_db = get_ssm_parameter("/dtis/mongodb/mongo-db")
        mongodb_collection = get_ssm_parameter("/dtis/mongodb/biigle-anno-session-collection")
        
        # Query MongoDB for documents with 'Completed' status
        client = MongoClient(mongodb_uri)
        collection = client[mongodb_db][mongodb_collection]
        
        completed_docs = list(collection.find({
            "biigle_annotation_job_status": "Completed"
        }))
        
        if not completed_docs:
            logger.info("No completed BIIGLE annotation sessions found")
            return {
                'statusCode': 200,
                'body': json.dumps('No completed annotation sessions to process')
            }
        
        # Process each completed document
        for doc in completed_docs:
            project_id = doc.get('biigle_project_id')
            project_name = doc.get('biigle_project_name')
            s3_input_uri = doc.get('s3_input_uri')
            
            if not all([project_id, project_name, s3_input_uri]):
                logger.warning(f"Skipping document with missing fields: {doc.get('_id')}")
                continue

            pipeline_parameters = [
                {"Name": "ProcessingInstanceCount", "Value": "1"},
                {"Name": "ProcessingInstanceType", "Value": "ml.m5.xlarge"},
                {"Name": "S3InputURI", "Value": s3_input_uri},
                {"Name": "ProjectId", "Value": project_id},
                {"Name": "ProjectName", "Value": project_name},
                {"Name": "BiigleApiUrl", "Value": get_ssm_parameter("/dtis/biigle/api-url")},
                {"Name": "BiigleApiEmail", "Value": get_ssm_parameter("/dtis/biigle/api-email")},
                {"Name": "BiigleApiToken", "Value": get_ssm_parameter("/dtis/biigle/api-token")},
                {"Name": "MongoDBURI", "Value": mongodb_uri}
            ]

            # Start the SageMaker pipeline execution
            response = sagemaker_client.start_pipeline_execution(
                PipelineName=pipeline_name,
                PipelineParameters=pipeline_parameters,
            )

            logger.info(f"Started annotation retrieval pipeline for project {project_name}: {response['PipelineExecutionArn']}")

        return {
            'statusCode': 200,
            'body': json.dumps(f'Started annotation retrieval for {len(completed_docs)} completed sessions')
        }

    except Exception as e:
        logger.error(f"Error processing event or starting SageMaker annotation retrieval pipeline: {e}")
        raise e