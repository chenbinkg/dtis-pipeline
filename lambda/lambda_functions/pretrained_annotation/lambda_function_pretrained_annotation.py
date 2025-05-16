import os
import json
import boto3
from urllib.parse import urlparse
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create a SageMaker and S3 client
sagemaker_client = boto3.client("sagemaker")

def lambda_handler(event, context):
    pipeline_name = os.environ.get("PIPELINE_NAME")
    if not pipeline_name:
        logger.error("Environment variable PIPELINE_NAME is not set.")
        return {"statusCode": 500, "body": "Missing PIPELINE_NAME environment variable."}

    logger.info("Received event: %s", json.dumps(event, indent=2))

    try:
        event_detail = event.get('detail', {}) # Use .get() for safer access
        output_groups = event_detail.get('outputGroupDetails', []) # Use .get() for safer access

        frame_capture_output_url = None

        # Iterate through all output groups
        for group in output_groups:
            # Now find the output details within this specific group
            if 'outputDetails' in group:
                for output in group['outputDetails']:
                    if 'outputFilePaths' in output:
                        # This is the S3 URL for an output within the "Frame Capture Group"
                        first_file_path = output['outputFilePaths'][0] # Get the first output file path
                        parsed_url = urlparse(first_file_path)
                        bucket_name = parsed_url.netloc
                        object_key_with_filename = parsed_url.path.lstrip('/') # Remove leading slash

                        # Use os.path.dirname and os.path.basename
                        s3_base_key = os.path.dirname(object_key_with_filename)
                        file_name = os.path.basename(object_key_with_filename)
                        if '/frames' in s3_base_key:
                            # This is the S3 URL for the Frame Capture Group
                            frame_capture_output_url = f"s3://{bucket_name}/{s3_base_key}/"
                            logger.info(f"Extracted S3 Output URL for Frame Capture Group: {frame_capture_output_url}")
                            break

        if not frame_capture_output_url:
            logger.info("Could not find S3 output URL for 'Frame Capture Group' in MediaConvert event.")
            # If the specific output group wasn't found or had no S3 output URL,
            # DO NOT to trigger the SageMaker pipeline.
            return {
                'statusCode': 200, # Or 400 if it's an expected condition not to trigger
                'body': json.dumps('Did not trigger SageMaker pretrained annotation pipeline: Frame Capture Group output not found.')
            }

        # Define parameters for the SageMaker pipeline
        annotation_s3_url = frame_capture_output_url.replace("/frames", "/annotations")
        pipeline_parameters = [
            {"Name": "S3InputURI", "Value": frame_capture_output_url},
            {"Name": "S3OutputURI", "Value": annotation_s3_url},
            {"Name": "InferenceInstanceType", "Value": "ml.m5.xlarge"},
        ]

        # Start the SageMaker pipeline execution
        response = sagemaker_client.start_pipeline_execution(
            PipelineName= os.environ['PIPELINE_NAME'], # Get pipeline name from environment variable
            PipelineParameters=pipeline_parameters,
        )

        logger.info("SageMaker pretrained annotation pipeline execution started:", response)

        return {
            'statusCode': 200,
            'body': json.dumps('SageMaker pretrained annotation pipeline execution started successfully!')
        }

    except Exception as e:
        logger.error(f"Error processing event or starting SageMaker pretrained annotation pipeline: {e}")
        raise e # Re-raise the exception to signal failure