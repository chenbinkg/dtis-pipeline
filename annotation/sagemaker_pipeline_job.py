import sys
import json
import os
import boto3
import sagemaker
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

if __name__ == "__main__":
    # Configuration
    region = "ap-southeast-2"  # Update with your region
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    
    # ECR image URI
    ecr_repository = "dtis-annotation-container"
    tag = "latest"
    image_uri = ParameterString(
        name="ECRImageURI", 
        default_value=f"{account_id}.dkr.ecr.{region}.amazonaws.com/{ecr_repository}:{tag}"
        )
    
    # S3 paths
    default_model_s3_uri = "s3://dtis-model-851725470721-testing/models/RF-DETR/checkpoint_best_regular.pth"
    default_input_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/001/video/TAN0616_001/frames/"
    default_output_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/001/video/TAN0616_001/annotations/"
    
    # Create and run the processing job
    print(f"Creating processing job with image: {image_uri}")

    sagemaker_session = sagemaker.session.Session()
    region = sagemaker_session.boto_region_name
    role = sagemaker.get_execution_role()
    pipeline_session = PipelineSession()
    default_bucket = sagemaker_session.default_bucket()

    processing_instance_count = ParameterInteger(name="ProcessingInstanceCount", default_value=1)
    instance_type = ParameterString(name="InferenceInstanceType", default_value="ml.m5.xlarge")
    volume_size_gb = ParameterInteger(name="ProcessingInstanceVolume", default_value=30)
    max_runtime_seconds = ParameterInteger(name="ProcessingInstanceTimeout", default_value=3600)
    model_s3_uri =  ParameterString(
        name="ModelS3URI",
        default_value=default_model_s3_uri
        )

    # # Create a local session
    # local_session = LocalSession()
    # local_session.config = {'local': {'local_code': True}}

    # Use the local session when creating processors/estimators
    processor = ScriptProcessor(
        image_uri=image_uri,
        role=role,
        instance_count=processing_instance_count,
        instance_type=instance_type,
        volume_size_in_gb=volume_size_gb,
        max_runtime_in_seconds=max_runtime_seconds,
        env={"MODEL_S3_URI": model_s3_uri},
        sagemaker_session=sagemaker_session
    )

    # define processor for inference
    s3_input_uri = ParameterString(
        name="S3InputURI",
        default_value=default_input_data_s3_uri
    )
    s3_output_uri = ParameterString(
        name="S3OutputURI",
        default_value=default_output_data_s3_uri
    )
    inference_args = processor.run(
        code="inference.py",
        source_dir="code",
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
                s3_upload_mode="Continuous"
            )
        ],
    )

    # define pipeline step: data query
    step_inference = ProcessingStep(name="inference", step_args=inference_args)

    pipeline_name = f"DTIS-Annotation-Pipeline-testing"
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            processing_instance_count,
            instance_type,
            s3_input_uri,
            s3_output_uri,
            model_s3_uri
        ],
        steps=[step_inference],
    )

    definition = json.loads(pipeline.definition())
    print(f"Pipeline definition: {json.dumps(definition, indent=2)}")

    pipeline.upsert(role_arn=role)

    execution = pipeline.start()
    print(f"Pipeline execution steps: {execution.list_steps()}")
    print(f"Pipeline execution status: {execution.describe()['PipelineExecutionStatus']}")