import sys
import json
import os
import boto3
import sagemaker
import argparse
import logging
from sagemaker.processing import ScriptProcessor
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.workflow.steps import ProcessingStep
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.parameters import (
    ParameterInteger,
    ParameterString,
)
from botocore.exceptions import NoCredentialsError, ClientError
# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from code.docker.utils import get_ssm_parameter, sanitize_log_input

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger()

# def sanitize_log_input(value: str) -> str:
#     """Sanitize input for logging to prevent log injection attacks."""
#     if not isinstance(value, str):
#         value = str(value)
#     return value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

# # Function to get parameters from SSM
# def get_ssm_parameter(name, default_value=None):
#     """Retrieve a parameter from AWS SSM Parameter Store."""
#     try:
#         ssm_client = boto3.client('ssm', region_name=os.environ.get('AWS_REGION', 'ap-southeast-2'))
#         response = ssm_client.get_parameter(Name=name, WithDecryption=True)
#         return response['Parameter']['Value']
#     except ClientError as e:
#         error_code = e.response.get('Error', {}).get('Code')
#         if error_code == 'ParameterNotFound':
#             _logger.warning(f"SSM parameter '{sanitize_log_input(name)}' not found, using default: {sanitize_log_input(str(default_value))}")
#             return default_value
#         elif error_code == 'AccessDenied':
#             _logger.error(f"Access denied to SSM parameter '{sanitize_log_input(name)}': {sanitize_log_input(str(e))}")
#             return default_value
#         else:
#             _logger.error(f"SSM client error for parameter '{sanitize_log_input(name)}': {sanitize_log_input(str(e))}")
#             return default_value
#     except NoCredentialsError as e:
#         _logger.error(f"AWS credentials not found for SSM: {sanitize_log_input(str(e))}")
#         return default_value
    

if __name__ == "__main__":
    # Configuration
    parser = argparse.ArgumentParser(description="SageMaker DTIS Taxonomy Pipeline Creation Script")
    parser.add_argument("--environment", type=str, default="prod", 
                        help="Environment for the pipeline (e.g., dev, prod)")
    parser.add_argument("--s3bucket", type=str, default="data-platform-dtis-prod-851725470721-model-data",
                        help="S3 bucket containing the CSV file")
    parser.add_argument("--s3key", type=str, default="pipeline_testdata/biigle_labels.csv",
                        help="S3 key for the CSV file")

    args, unknown = parser.parse_known_args()
    environment = args.environment
    s3_bucket = args.s3bucket
    s3_key = args.s3key

    # Create a session
    session = boto3.session.Session()
    region = session.region_name
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    
    # ECR image URI
    ssm_client = boto3.client('ssm', region_name=region)
    response = ssm_client.get_parameter(Name="/dtis/pipeline/ecr-repository-url")
    ecr_repo_url = response['Parameter']['Value']
    tag = "latest"
    default_ecr_image_uri = f"{ecr_repo_url}:{tag}"

    # Create standard SageMaker session
    sagemaker_session = sagemaker.session.Session()

    # Get role
    try:
        role = sagemaker.get_execution_role()
    except ValueError:
        project_name = "data-platform-dtis"
        role = f"arn:aws:iam::{account_id}:role/{project_name}-{environment}-sagemaker-pipeline-role"

    # Get SSM parameters
    mongodb_uri_ssm = get_ssm_parameter("/dtis/mongodb/mongo-uri", "")
    mongodb_db_ssm = get_ssm_parameter("/dtis/mongodb/mongo-db", "dtis-data")
    mongodb_collection_ssm = get_ssm_parameter("/dtis/mongodb/dtis-taxonomy-collection", "dtis_taxonomy")

    # Use PipelineSession for defining the pipeline
    pipeline_session = PipelineSession()

    # Define parameters
    processing_instance_count = ParameterInteger(
        name="ProcessingInstanceCount", 
        default_value=1
    )
    instance_type = ParameterString(
        name="ProcessingInstanceType", 
        default_value="ml.m5.xlarge"
    )
    s3_bucket_param = ParameterString(
        name="S3Bucket",
        default_value=s3_bucket
    )
    s3_key_param = ParameterString(
        name="S3Key",
        default_value=s3_key
    )
    mongodb_uri_param = ParameterString(
        name="MongoDBURI",
        default_value=mongodb_uri_ssm
    )
    mongodb_db_param = ParameterString(
        name="MongoDBDB",
        default_value=mongodb_db_ssm
    )
    mongodb_collection_param = ParameterString(
        name="MongoDBCollection",
        default_value=mongodb_collection_ssm
    )
    workers_param = ParameterInteger(
        name="Workers",
        default_value=5
    )

    # Create processor for taxonomy processing
    processor_taxonomy = ScriptProcessor(
        command=["python3"],
        image_uri=default_ecr_image_uri,
        role=role,
        instance_count=processing_instance_count,
        instance_type=instance_type,
        volume_size_in_gb=30,
        max_runtime_in_seconds=7200,
        sagemaker_session=sagemaker_session
    )

    # Define pipeline step for taxonomy processing
    step_taxonomy_processing = ProcessingStep(
        name="dtis_taxonomy_processing",
        processor=processor_taxonomy,
        code="code/docker/generate_taxonomy_docs.py",
        job_arguments=[
            "--s3bucket", s3_bucket_param,
            "--s3key", s3_key_param,
            "--mongo_uri", mongodb_uri_param,
            "--mongo_db", mongodb_db_param,
            "--mongo_collection", mongodb_collection_param,
            "--workers", workers_param.to_string(),
        ]
    )

    # Create pipeline
    pipeline_name = f"DTIS-Taxonomy-Processing-Pipeline-{environment}"
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            processing_instance_count,
            instance_type,
            s3_bucket_param,
            s3_key_param,
            mongodb_uri_param,
            mongodb_db_param,
            workers_param,
            mongodb_collection_param
        ],
        steps=[step_taxonomy_processing],
        sagemaker_session=pipeline_session
    )

    # Get and print the pipeline definition
    definition = json.loads(pipeline.definition())
    _logger.info(f"Pipeline definition: {json.dumps(definition, indent=2)}")

    # Deploy the pipeline to AWS
    _logger.info("Creating/updating taxonomy processing pipeline in AWS...")
    pipeline.upsert(role_arn=role)

    # Optionally, start the pipeline execution
    start_execution = input("Start pipeline execution? (y/n): ")
    if start_execution.lower() == 'y':
        execution = pipeline.start()
        _logger.info(f"Pipeline execution started with ARN: {execution.arn}")
        _logger.info(f"Pipeline execution steps: {execution.list_steps()}")
        _logger.info(f"Pipeline execution status: {execution.describe()['PipelineExecutionStatus']}")
    else:
        _logger.info("Pipeline created but not started.")