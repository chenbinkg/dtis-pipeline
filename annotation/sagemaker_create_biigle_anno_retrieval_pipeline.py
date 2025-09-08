import sys
import os
import json
import logging
import boto3
import sagemaker
import argparse
from sagemaker.processing import ScriptProcessor
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.workflow.steps import ProcessingStep
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.parameters import (
    ParameterInteger,
    ParameterString,
)

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from code.docker.utils import get_ssm_parameter
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger()


if __name__ == "__main__":
    # Configuration
    parser = argparse.ArgumentParser(description="SageMaker Retrieval Pipeline Creation Script")
    parser.add_argument("--environment", type=str, default="dev", 
                        help="Environment for the pipeline (e.g., dev, prod)")
    parser.add_argument("--project_name", type=str, default="AnnotationProject_TAN0616_097_20250616T045329",
                        help="Name of the project")
    parser.add_argument("--project_id", type=int, default=3857,
                        help="ID of the project")
    parser.add_argument("--input_data_s3_uri", type=str, 
                        default="s3://data-platform-dtis-dev-443293291817-model-data/TAN0616/097/video/TAN0616_097/frames/",
                        help="S3 URI for the input data")

    args, unknown = parser.parse_known_args()
    environment = args.environment
    default_input_data_s3_uri = args.input_data_s3_uri
    default_project_name = args.project_name
    default_project_id = args.project_id

    # Create a session
    region = 'ap-southeast-2'  # Set explicit region
    session = boto3.session.Session(region_name=region)

    # Get the region from the session
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    _logger.info(f"Using AWS region: {region}")
    
    # ECR image URI
    # ssm_client = boto3.client('ssm', region_name=region)
    # response = ssm_client.get_parameter(Name="/dtis/pipeline/ecr-repository-url")
    # ecr_repo_url = response['Parameter']['Value']
    ecr_repo_url = get_ssm_parameter("/dtis/pipeline/ecr-repository-url", "")
    tag = "latest"
    default_ecr_image_uri = f"{ecr_repo_url}:{tag}"

    # Create standard SageMaker session with explicit region
    sagemaker_session = sagemaker.session.Session(boto_session=session)

    # Get role
    try:
        role = sagemaker.get_execution_role()
    except ValueError:
        project_name = "data-platform-dtis"
        role = f"arn:aws:iam::{account_id}:role/{project_name}-{environment}-sagemaker-pipeline-role"

    # Get SSM parameters
    api_url = get_ssm_parameter("/dtis/biigle/api-url", "https://biigle.de/api/v1")
    email = get_ssm_parameter("/dtis/biigle/api-email", "bryce.chen@niwa.co.nz")
    token = get_ssm_parameter("/dtis/biigle/api-token", "")
    mongodb_uri_ssm = get_ssm_parameter("/dtis/mongodb/uri", "")

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
    s3_input_uri = ParameterString(
        name="S3InputURI",
        default_value=default_input_data_s3_uri
    )
    project_id = ParameterInteger(
        name="ProjectId",
        default_value=default_project_id
    )
    project_name = ParameterString(
        name="ProjectName",
        default_value=default_project_name
    )
    biigle_api_url = ParameterString(
        name="BiigleApiUrl",
        default_value=api_url
    )
    biigle_api_email = ParameterString(
        name="BiigleApiEmail",
        default_value=email
    )
    biigle_api_token = ParameterString(
        name="BiigleApiToken",
        default_value=token
    )
    mongodb_uri_param = ParameterString(
        name="MongoDBURI",
        default_value=mongodb_uri_ssm
    )

    # Create processor for annotation retrieval
    processor_retrieval = ScriptProcessor(
        command=["python3"],
        image_uri=default_ecr_image_uri,
        role=role,
        instance_count=processing_instance_count,
        instance_type=instance_type,
        volume_size_in_gb=30,
        max_runtime_in_seconds=3600,
        sagemaker_session=sagemaker_session
    )

    # Define pipeline step for annotation retrieval
    step_annotation_retrieval = ProcessingStep(
        name="biigle_annotation_retrieval",
        processor=processor_retrieval,
        code="code/docker/biigle_annotation_retrieval.py",
        job_arguments=[
            "--project_id", project_id.to_string(),
            "--project_name", project_name,
            "--s3_input_uri", s3_input_uri,
        ]
    )

    # Create pipeline
    pipeline_name = f"DTIS-Annotation-Retrieval-Pipeline-{environment}"
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            processing_instance_count,
            instance_type,
            s3_input_uri,
            project_id,
            project_name,
            biigle_api_url,
            biigle_api_email,
            biigle_api_token,
            mongodb_uri_param
        ],
        steps=[step_annotation_retrieval],
        sagemaker_session=pipeline_session
    )

    # Get and print the pipeline definition
    definition = json.loads(pipeline.definition())
    _logger.info(f"Pipeline definition: {json.dumps(definition, indent=2)}")

    # Deploy the pipeline to AWS
    _logger.info("Creating/updating retrieval pipeline in AWS...")
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