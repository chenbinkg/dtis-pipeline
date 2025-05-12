import boto3
import sagemaker
from sagemaker.processing import Processor, ProcessingInput, ProcessingOutput
from sagemaker import get_execution_role

def create_processing_job(
    image_uri,
    model_s3_uri,
    input_data_s3_uri,
    output_data_s3_uri,
    instance_type="ml.m5.xlarge",
    instance_count=1,
    volume_size_gb=30,
    max_runtime_seconds=3600  # 1 hour
):
    """
    Create a SageMaker Processing job to run RFDETR inference on images.
    
    Args:
        image_uri: ECR image URI for the container
        model_s3_uri: S3 URI for model weights file
        input_data_s3_uri: S3 URI for input images
        output_data_s3_uri: S3 URI for output predictions
        instance_type: EC2 instance type to use
        instance_count: Number of instances to use
        volume_size_gb: Size of EBS volume in GB
        max_runtime_seconds: Maximum runtime in seconds
    """
    # Get SageMaker session and role
    session = sagemaker.Session()
    # role = get_execution_role()
    role = "arn:aws:iam::851725470721:role/service-role/AmazonSageMaker-ExecutionRole-20240711T130963"
    
    # Configure the processor
    processor = Processor(
        image_uri=image_uri,
        role=role,
        instance_count=instance_count,
        instance_type=instance_type,
        volume_size_in_gb=volume_size_gb,
        max_runtime_in_seconds=max_runtime_seconds,
        env={"MODEL_S3_URI": model_s3_uri},
        sagemaker_session=session
    )
    
    # Run the processing job
    processor.run(
        inputs=[
            ProcessingInput(
                source=input_data_s3_uri,
                destination="/opt/ml/processing/input",
                s3_data_type="S3Prefix",
                s3_input_mode="File",
                s3_data_distribution_type="FullyReplicated"
            )
        ],
        outputs=[
            ProcessingOutput(
                source="/opt/ml/processing/output",
                destination=output_data_s3_uri,
                s3_upload_mode="EndOfJob"
            )
        ],
        arguments=["python", "inference.py"],
        wait=True,  # Set to True if you want to wait for job completion
        logs=True
    )
    
    return processor

if __name__ == "__main__":
    # Configuration
    region = "ap-southeast-2"  # Update with your region
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    
    # ECR image URI
    ecr_repository = "dtis-annotation-container"
    tag = "latest"
    image_uri = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{ecr_repository}:{tag}"
    
    # S3 paths
    model_s3_uri = "s3://dtis-model-851725470721-testing/models/RF-DETR/checkpoint_best_regular.pth"
    input_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/001/video/TAN0616_001/frames/"
    output_data_s3_uri = "s3://dtis-model-851725470721-testing/TAN0616/001/video/TAN0616_001/annotations/"
    
    # Create and run the processing job
    print(f"Creating processing job with image: {image_uri}")
    processor = create_processing_job(
        image_uri=image_uri,
        model_s3_uri=model_s3_uri,
        input_data_s3_uri=input_data_s3_uri,
        output_data_s3_uri=output_data_s3_uri,
        instance_type="ml.m5.xlarge",  # Choose an appropriate instance type
        instance_count=1
    )
    
    print(f"Processing job created: {processor.latest_job.name}")
    print(f"Check status at: https://{region}.console.aws.amazon.com/sagemaker/home?region={region}#/processing-jobs/{processor.latest_job.name}")