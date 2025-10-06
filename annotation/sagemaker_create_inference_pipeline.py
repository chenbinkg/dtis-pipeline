import sys
import json
import os
import boto3
import sagemaker
import argparse
import logging
from sagemaker.local import LocalSession
from sagemaker.s3 import S3Downloader
from sagemaker.processing import ScriptProcessor
from sagemaker.estimator import Estimator
from sagemaker.sklearn.estimator import SKLearn
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.workflow.steps import ProcessingStep
from sagemaker.inputs import TrainingInput
from sagemaker.workflow.steps import TrainingStep
from sagemaker.workflow.functions import Join
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.parameters import (
    ParameterInteger,
    ParameterString,
    ParameterFloat,
)

from botocore.exceptions import NoCredentialsError, ClientError

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger()


def sanitize_log_input(value: str) -> str:
    """Sanitize input for logging to prevent log injection attacks."""
    if not isinstance(value, str):
        value = str(value)
    return value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

# Function to get parameters from SSM
def get_ssm_parameter(name, default_value=None):
    """Retrieve a parameter from AWS SSM Parameter Store."""
    try:
        ssm_client = boto3.client('ssm', region_name=os.environ.get('AWS_REGION', 'ap-southeast-2'))
        response = ssm_client.get_parameter(Name=name, WithDecryption=True)
        return response['Parameter']['Value']
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        if error_code == 'ParameterNotFound':
            _logger.warning(f"SSM parameter '{sanitize_log_input(name)}' not found, using default: {sanitize_log_input(str(default_value))}")
            return default_value
        elif error_code == 'AccessDenied':
            _logger.error(f"Access denied to SSM parameter '{sanitize_log_input(name)}': {sanitize_log_input(str(e))}")
            return default_value
        else:
            _logger.error(f"SSM client error for parameter '{sanitize_log_input(name)}': {sanitize_log_input(str(e))}")
            return default_value
    except NoCredentialsError as e:
        _logger.error(f"AWS credentials not found for SSM: {sanitize_log_input(str(e))}")
        return default_value


if __name__ == "__main__":
    # Configuration
    parser = argparse.ArgumentParser(description="SageMaker Pipeline Creation Script")
    parser.add_argument("--cruise", type=str, default="TAN0616",
                        help="cruise name, e.g. TAN0616")
    parser.add_argument("--station", type=str, default="095",
                        help="station name, e.g. 095")
    parser.add_argument("--environment", type=str, default="prod",
                        help="Environment for the pipeline (e.g., dev, prod)")
    parser.add_argument("--model_s3_uri", type=str, default="s3://data-platform-dtis-prod-851725470721-model-data/models/RF-DETR/checkpoint_best_regular.pth",
                        help="S3 URI for the model file")
    parser.add_argument("--input_data_s3_uri", type=str, default="s3://data-platform-dtis-prod-851725470721-model-data/pipeline_testdata/TAN0616/095/video/TAN0616_095/frames/",
                        help="S3 URI for the input data")
    parser.add_argument("--output_data_s3_uri", type=str, default="s3://data-platform-dtis-prod-851725470721-model-data/pipeline_testdata/TAN0616/095/video/TAN0616_095/annotations/",
                        help="S3 URI for the output data")
    parser.add_argument("--matched_anno_s3_uri", type=str, default="s3://data-platform-dtis-prod-851725470721-model-data/pipeline_testdata/TAN0616/095/video/TAN0616_095/matched_annotations/",
                        help="S3 URI for the matched annotations")

    args, unknown = parser.parse_known_args()
    cruise = args.cruise
    station = args.station
    environment = args.environment
    default_model_s3_uri = args.model_s3_uri
    default_input_data_s3_uri = args.input_data_s3_uri
    default_output_data_s3_uri = args.output_data_s3_uri
    default_matched_anno_s3_uri = args.matched_anno_s3_uri

    # Parse the S3 URI to get bucket and key
    parts = default_input_data_s3_uri.replace("s3://", "").split("/", 1)
    bucket_name = parts[0]
    object_key = parts[1] if len(parts) > 1 else ""
    _logger.info(f"Parsed S3 bucket: {bucket_name}, key: {object_key}")

    # Create a session
    session = boto3.session.Session()

    # Get the region from the session
    region = session.region_name
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    _logger.info(f"Using AWS region: {region}")
    # ECR image URI
    ssm_client = boto3.client('ssm', region_name=region)
    response = ssm_client.get_parameter(Name="/dtis/pipeline/ecr-repository-url")
    ecr_repo_url = response['Parameter']['Value']
    tag = "latest"
    default_ecr_image_uri = f"{ecr_repo_url}:{tag}"

    # Create standard SageMaker session (not local)
    sagemaker_session = sagemaker.session.Session()

    # Get role from environment or hardcode it for local testing
    try:
        role = sagemaker.get_execution_role()
    except ValueError:
        # Fallback for local execution
        project_name = "data-platform-dtis"
        role = f"arn:aws:iam::{account_id}:role/{project_name}-{environment}-sagemaker-pipeline-role"

    # Find SSM parameters
    api_url = get_ssm_parameter("/dtis/biigle/api-url", "https://biigle.de/api/v1")
    email = get_ssm_parameter("/dtis/biigle/api-email", "bryce.chen@niwa.co.nz")
    token = get_ssm_parameter("/dtis/biigle/api-token", "")
    label_tree_to_add_id = get_ssm_parameter("/dtis/biigle/label-tree-id", "3270")
    storage_disk_id = get_ssm_parameter("/dtis/biigle/disk-id", "84")
    user_pattern = get_ssm_parameter("/dtis/biigle/user-pattern", "Caroline")
    user_lastname = get_ssm_parameter("/dtis/biigle/user-lastname", "Chin")
    create_disk_secret_name = get_ssm_parameter("/dtis/biigle/create-user-disk-secret-name", "aws-credentials/biigle/create-user-disk")
    mongodb_uri = get_ssm_parameter("/dtis/mongodb/mongo-uri", "")
    mongodb_db = get_ssm_parameter("/dtis/mongodb/mongo-db", "dtis-data")
    mongodb_biigle_anno_sess_collection = get_ssm_parameter("/dtis/mongodb/biigle-anno-session-collection", "dtis_biigle_annotation_session")
    mongodb_video_collection = get_ssm_parameter("/dtis/mongodb/dtis-video-collection", "dtis_video")
    mongodb_ofop_obser_collection = get_ssm_parameter("/dtis/mongodb/dtis-ofop-obser-collection", "dtis_ofop_obser")
    mongodb_master_collection = get_ssm_parameter("/dtis/mongodb/dtis-master-collection", "dtis_master")

    # Use PipelineSession for defining the pipeline
    pipeline_session = PipelineSession()
    # default_bucket = sagemaker_session.default_bucket()

    # Define parameters
    cruise_param = ParameterString(
        name="Cruise",
        default_value=cruise
    )
    station_param = ParameterString(
        name="Station",
        default_value=station
    )
    bucket_name_param = ParameterString(
        name="BucketName",
        default_value=bucket_name
    )
    frames_prefix_param = ParameterString(
        name="FramesPrefix",
        default_value=object_key
    )
    region_param = ParameterString(
        name="AWSRegion",
        default_value=region
    )
    processing_instance_count = ParameterInteger(
        name="ProcessingInstanceCount", 
        default_value=1
        )
    instance_type = ParameterString(
        name="InferenceInstanceType", 
        default_value="ml.m5.xlarge"
        ) #m6g.xlarge for graviton ARM
    # instance_type = ParameterString(name="InferenceInstanceType", default_value="ml.m5.xlarge") #m5.xlarge for x86
    model_s3_uri =  ParameterString(
        name="ModelS3URI",
        default_value=default_model_s3_uri
        )
    mongodb_uri_ssm = ParameterString(
        name="MongoDBURI",
        default_value="/dtis/mongodb/mongo-uri"  # SSM parameter for MongoDB
        )
    db_name = ParameterString(
        name="DBName",
        default_value=mongodb_db
        )
    video_collection_name = ParameterString(
        name="VideoCollectionName",
        default_value=mongodb_video_collection
        )
    master_collection_name = ParameterString(
        name="MasterCollectionName",
        default_value=mongodb_master_collection
        )
    ofop_obser_collection_name = ParameterString(
        name="OFOPObserCollectionName",
        default_value=mongodb_ofop_obser_collection
        )
    dtis_biigle_anno_collection_name = ParameterString(
        name="DTISBiigleAnnoCollectionName",
        default_value=mongodb_biigle_anno_sess_collection
        )
    biigle_create_disk_secret_name = ParameterString(
        name="BiigleCreateDiskSecretName",
        default_value=create_disk_secret_name
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
    biigle_label_tree_id = ParameterString(
        name="BiigleLabelTreeId",
        default_value=label_tree_to_add_id
        )
    biigle_storage_disk_id = ParameterString(
        name="BiigleStorageDiskId",
        default_value=storage_disk_id
        )
    biigle_user_pattern = ParameterString(
        name="BiigleUserPattern",
        default_value=user_pattern
        )
    biigle_user_lastname = ParameterString(
        name="BiigleUserLastname",
        default_value=user_lastname
        )

    # # Create a local session
    # local_session = LocalSession()
    # local_session.config = {'local': {'local_code': True}}

    # Use the local session when creating processors/estimators
    processor_inference = ScriptProcessor(
        command=["python3"],
        image_uri=default_ecr_image_uri,
        role=role,
        instance_count=1,
        instance_type="ml.m5.xlarge",
        volume_size_in_gb=30,
        max_runtime_in_seconds=3600,
        env={"MODEL_S3_URI": default_model_s3_uri},
        sagemaker_session=sagemaker_session
    )

    # define processor for annotation matching
    processor_annotation_matching = ScriptProcessor(
        command=["python3"],
        image_uri=default_ecr_image_uri,
        role=role,
        instance_count=1,
        instance_type="ml.m5.xlarge",
        sagemaker_session=sagemaker_session
    )

    # Define pipeline step
    # step_inference = ProcessingStep(name="inference", step_args=inference_args)
    
    # define processor for inference
    s3_input_uri = ParameterString(
        name="S3InputURI",
        default_value=default_input_data_s3_uri
    )
    s3_output_uri = ParameterString(
        name="S3OutputURI",
        default_value=default_output_data_s3_uri
    )
    s3_matched_anno_uri = ParameterString(
        name="S3MatchedAnnoURI",
        default_value=default_matched_anno_s3_uri
    )

    # Define pipeline step directly with processor
    step_inference = ProcessingStep(
        name="inference",
        processor=processor_inference,
        code="code/docker/inference.py",
        inputs=[
            ProcessingInput(
                source=s3_input_uri,
                destination="/opt/ml/processing/input"
            )
        ],
        outputs=[
            ProcessingOutput(
                source="/opt/ml/processing/output",
                destination=s3_output_uri,
                s3_upload_mode="Continuous",
                output_name="anno_data"
            )
        ]
    )

    # Define pipeline step directly with processor
    step_annotation_matching = ProcessingStep(
        name="annotation_matching",
        processor=processor_annotation_matching,
        code="code/docker/annotation_matching.py",
        inputs=[
            ProcessingInput(
                source=step_inference.properties.ProcessingOutputConfig.Outputs["anno_data"].S3Output.S3Uri,
                destination="/opt/ml/processing/pretrained_annotations"
            )
        ],
        outputs=[
            ProcessingOutput(
                source="/opt/ml/processing/matched_annotations",
                destination=s3_matched_anno_uri,
                s3_upload_mode="Continuous",
                output_name="matched_anno_data"
            )
        ],
        job_arguments=[
            "--cruise", cruise_param,
            "--station", station_param,
            "--db_name", db_name,
            "--video_collection_name", video_collection_name,
            "--master_collection_name", master_collection_name,
            "--ofop_obser_collection_name", ofop_obser_collection_name,
            "--ssm_param_mongodb_uri", mongodb_uri_ssm,
        ]
    )

    # Define pipeline step directly with processor
    step_biigle_annotation = ProcessingStep(
        name="biigle_annotation_session",
        processor=processor_annotation_matching,
        code="code/docker/biigle_annotation_session.py",
        inputs=[
            ProcessingInput(
                source=step_annotation_matching.properties.ProcessingOutputConfig.Outputs["matched_anno_data"].S3Output.S3Uri,
                destination="/opt/ml/processing/matched_annotations"
            )
        ],
        job_arguments=[
            "--bucket_name", bucket_name_param,
            "--frames_prefix", frames_prefix_param,
            "--cruise", cruise_param,
            "--station", station_param,
            "--aws_region", region_param,
            "--secret_name", biigle_create_disk_secret_name,
            "--api_url", biigle_api_url,
            "--api_email", biigle_api_email,
            "--api_token", biigle_api_token,
            "--label_tree_id", biigle_label_tree_id,
            "--storage_disk_id", biigle_storage_disk_id,
            "--user_pattern", biigle_user_pattern,
            "--user_lastname", biigle_user_lastname,
            "--ssm_param_mongodb_uri", mongodb_uri_ssm,
            "--mongodb_db", db_name,
            "--dtis_biigle_anno_sess_collection", dtis_biigle_anno_collection_name
        ]
    )

    # Create pipeline
    pipeline_name = f"DTIS-Annotation-Pipeline-{environment}"
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            bucket_name_param,
            cruise_param,
            station_param,
            frames_prefix_param,
            region_param,
            processing_instance_count,
            instance_type,
            s3_input_uri,
            s3_output_uri,
            s3_matched_anno_uri,
            model_s3_uri,
            mongodb_uri_ssm,
            db_name,
            video_collection_name,
            master_collection_name,
            ofop_obser_collection_name,
            dtis_biigle_anno_collection_name,
            biigle_create_disk_secret_name,
            biigle_api_url,
            biigle_api_email,
            biigle_api_token,
            biigle_label_tree_id,
            biigle_storage_disk_id,
            biigle_user_pattern,
            biigle_user_lastname
        ],
        steps=[
            step_inference,
            step_annotation_matching,
            step_biigle_annotation
            ],

    )

    # Get and print the pipeline definition
    definition = json.loads(pipeline.definition())
    print(f"Pipeline definition: {json.dumps(definition, indent=2)}")

    # Deploy the pipeline to AWS
    print("Creating/updating pipeline in AWS...")
    pipeline.upsert(role_arn=role)

    # Optionally, start the pipeline execution
    start_execution = input("Start pipeline execution? (y/n): ")
    if start_execution.lower() == 'y':
        execution = pipeline.start()
        print(f"Pipeline execution started with ARN: {execution.arn}")
        print(f"Pipeline execution steps: {execution.list_steps()}")
        print(f"Pipeline execution status: {execution.describe()['PipelineExecutionStatus']}")
    else:
        print("Pipeline created but not started.")
