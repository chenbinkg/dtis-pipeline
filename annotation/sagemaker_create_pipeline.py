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


def initialize_command():
    # Initialize the command variable with a default value
    command = ["python3"]
    return command

def set_entrypoint(command, user_script_location):
    # Ensure that command is not None
    if command is None:
        command = initialize_command()
    
    # Set the entrypoint by concatenating command and user_script_location
    entrypoint = command + [user_script_location]
    return entrypoint


if __name__ == "__main__":
    # Configuration
    region = "ap-southeast-2"  # Update with your region
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    # ECR image URI
    ecr_repository = "dtis-annotation-container"
    tag = "latest"
    default_ecr_image_uri = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{ecr_repository}:{tag}"

    # S3 paths
    default_model_s3_uri = "s3://dtis-model-851725470721-testing/models/RF-DETR/checkpoint_best_regular.pth"
    # default_input_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/001/video/TAN0616_001/frames/"
    # default_output_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/001/video/TAN0616_001/annotations/"
    # default_matched_anno_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/001/video/TAN0616_001/matched_annotations/"
    default_input_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/095/video/TAN0616_095/frames_test/"
    default_output_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/095/video/TAN0616_095/annotations/"
    default_matched_anno_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/095/video/TAN0616_095/matched_annotations/"
    # image_uri = ParameterString(
    #     name="ECRImageURI", 
    #     default_value=f"{account_id}.dkr.ecr.{region}.amazonaws.com/{ecr_repository}:{tag}"
    #     )
    
    # Create standard SageMaker session (not local)
    sagemaker_session = sagemaker.session.Session()
    region = sagemaker_session.boto_region_name

    # Get role from environment or hardcode it for local testing
    try:
        role = sagemaker.get_execution_role()
    except ValueError:
        # Fallback for local execution
        role = "arn:aws:iam::851725470721:role/DTIS-SageMakerPipelineExecutionRole-testing"

    # Use PipelineSession for defining the pipeline
    pipeline_session = PipelineSession()
    # default_bucket = sagemaker_session.default_bucket()

    # Define parameters
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
    db_name = ParameterString(
        name="DBName",
        default_value="dtistest"
        )
    video_collection_name = ParameterString(
        name="VideoCollectionName",
        default_value="dtis_videos"
        )
    master_collection_name = ParameterString(
        name="MasterCollectionName",
        default_value="dtis_master"
        )
    ofop_obser_collection_name = ParameterString(
        name="OFOPObserCollectionName",
        default_value="dtis_ofop_obser"
        )
    dtis_biigle_anno_collection_name = ParameterString(
        name="DTISBiigleAnnoCollectionName",
        default_value="dtis_biigle_annotation_session"
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

    # inference_args = processor.run(
    #     code="code/docker/inference.py",
    #     # source_dir="code",
    #     inputs=[
    #         ProcessingInput(
    #             source=default_input_data_s3_uri,
    #             destination="/opt/ml/processing/input"
    #         )
    #     ],
    #     outputs=[
    #         ProcessingOutput(
    #             source="/opt/ml/processing/output",
    #             destination=default_output_data_s3_uri,
    #             s3_upload_mode="Continuous"
    #         )
    #     ]
    # )

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
            "--s3_input_uri", s3_input_uri,
            "--db_name", db_name,
            "--video_collection_name", video_collection_name,
            "--master_collection_name", master_collection_name,
            "--ofop_obser_collection_name", ofop_obser_collection_name
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
            "--s3_input_uri", s3_input_uri,
            "--db_name", db_name,
            "--dtis_biigle_anno_collection_name", dtis_biigle_anno_collection_name
        ]
    )

    # Create pipeline
    pipeline_name = f"DTIS-Annotation-Pipeline-testing"
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            processing_instance_count,
            instance_type,
            s3_input_uri,
            s3_output_uri,
            s3_matched_anno_uri,
            model_s3_uri,
            db_name,
            video_collection_name,
            master_collection_name,
            ofop_obser_collection_name,
            dtis_biigle_anno_collection_name
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
