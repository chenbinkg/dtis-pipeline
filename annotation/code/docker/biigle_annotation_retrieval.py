import logging
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse
import numpy as np
import requests
from botocore.exceptions import NoCredentialsError, ClientError

from .utils import (
    get_ssm_parameter,
    list_all_objects,
    read_json_from_s3,
    write_json_to_s3,
    sanitize_log_input,
)

from .mongodb import MongoDBOps
from .biigle_api import Api

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger(__name__)


def main(
        project_id: int,
        project_name: str,
        s3_input_uri: str,
):
    """
    Main function to retrieve human validated BIIGLE annotations.
    This function is triggered by eventbridge event for detecting "Completed" biigle annotation session.
    The eventbridge event triggers the sagemaker pipeline to run this script.
    The trigger contains biigle project id, project name and s3 input uri which contains the video frame images.
    It fetches the annotations by image, convert the annotation to AWS Reckongnition format. 
    It then saves the converted annottion format to S3 bucket and finally update MongoDB project job status to "Retrieved".

    Args:
        project_id (int): The BIIGLE project ID.
        project_name (str): The name of the BIIGLE project.
        s3_input_uri (str): The S3 URI where the input images are stored.
        example: s3://dtis-model-851725470721-testing/TAN0616/092/video/TAN0616_092/frames/
    """
    try:
        # Get configuration from SSM parameters
        biigle_api_url = get_ssm_parameter("dtis/biigle/api-url", "https://biigle.de/api/v1")
        email = get_ssm_parameter("dtis/biigle/api-email", "bryce.chen@niwa.co.nz")
        token = get_ssm_parameter("dtis/biigle/api-token", "")
        region = get_ssm_parameter("dtis/aws/region", "ap-southeast-2")
        # bucket name corresponds to netloc (network location) and 
        # the key is the path (with the leading / stripped)
        bucket_name, frames_prefix = urlparse(s3_input_uri).path.lstrip('/')
        ssm_param_mongodb_uri = get_ssm_parameter("dtis/mongodb/mongo-uri", "")
        _logger.info(
            f"Using S3 bucket: {sanitize_log_input(bucket_name)} "
            f"with prefix: {sanitize_log_input(frames_prefix)}")
        
        _logger.info(f"Starting annotation retrieval for project: {sanitize_log_input(project_name)}")
        matched_anno_prefix = frames_prefix.replace("/frames", "/matched_annotations")
        validated_anno_prefix = frames_prefix.replace("/frames", "/validated_annotations")
        _logger.info(f"Validated annotations will be saved to: {sanitize_log_input(validated_anno_prefix)}")
        api_client = Api(
            email=email, 
            token=token,
            base_url=biigle_api_url
            )
        
        process_annotations(
            api_client=api_client, 
            bucket_name=bucket_name, 
            frames_prefix=frames_prefix, 
            matched_anno_prefix=matched_anno_prefix, 
            validated_anno_prefix=validated_anno_prefix, 
            region=region
            )
        mongodb = MongoDBOps(mongodb_uri=ssm_param_mongodb_uri)
        # Update MongoDB project job status to "Retrieved"
        query_filter = mongodb.gen_query_filter(
            columns=["project_id", "project_name"],
            values=[project_id, project_name]
        )
        update_data = {"job_status": "Retrieved"}
        mongodb.write_to_mongodb(
            db_name="dtis_projects",
            collection_name="projects",
            data=update_data,
            query_filter=query_filter
        )
        _logger.info(f"Updated MongoDB project job status to 'Retrieved' for project: {sanitize_log_input(project_name)}")
    except NoCredentialsError:
        _logger.error("AWS credentials not found. Please configure your AWS credentials.")
        raise
    except ClientError as e:
        _logger.error(f"Client error occurred: {sanitize_log_input(str(e))}")
        raise
    except requests.exceptions.RequestException as e:
        _logger.error(f"API request failed: {sanitize_log_input(str(e))}")
        raise
    except Exception as e:
        _logger.error(f"Error in main execution: {sanitize_log_input(str(e))}")
        raise


def process_annotations(api_client, bucket_name, frames_prefix, matched_anno_prefix, validated_anno_prefix, region):
    """Process annotations from BIIGLE and save validated annotations to S3."""
    try:
        # Get project ID - should come from MongoDB in production
        new_project_id = 3856
        
        # Get volume ID
        response = api_client.get(f"projects/{new_project_id}/volumes")
        response.raise_for_status()
        data = response.json()
        
        if not data:
            _logger.warning(f"No volumes found for project {new_project_id}")
            return
            
        volume_id = data[0]['id']
        _logger.info(f"Found volume id {volume_id} for project: {new_project_id}")
        
        # Get image names mapping
        image_names = api_client.fetch_image_data_from_api(volume_id=volume_id)
        _logger.info(f"Retrieved {len(image_names)} images from volume {volume_id}")
        
        # Read matched annotation files from S3
        json_files = list_all_objects(bucket_name, matched_anno_prefix)
        _logger.info(f"Found {len(json_files)} annotation files to process")
        
        processed_count = 0
        for json_file in json_files:
            try:
                if process_single_annotation(api_client, json_file, bucket_name, frames_prefix, 
                                           validated_anno_prefix, region, image_names):
                    processed_count += 1
            except Exception as e:
                _logger.error(f"Error processing {sanitize_log_input(json_file)}: {sanitize_log_input(str(e))}")
                continue
                
        _logger.info(f"Successfully processed {processed_count} annotation files")
        
    except requests.exceptions.RequestException as e:
        _logger.error(f"API request failed: {sanitize_log_input(str(e))}")
        raise
    except Exception as e:
        _logger.error(f"Error in process_annotations: {sanitize_log_input(str(e))}")
        raise


def process_single_annotation(api_client, json_file, bucket_name, frames_prefix, 
                            validated_anno_prefix, region, image_names):
    """Process a single annotation file."""
    json_data = read_json_from_s3(bucket_name, json_file)
    file_name = json_data['source-ref'].split('/')[-1]
    
    # Find image ID
    image_id = None
    for img_id, img_name in image_names.items():
        if img_name == file_name:
            image_id = img_id
            break
            
    if image_id is None:
        _logger.warning(f"Image ID not found for file: {sanitize_log_input(file_name)}")
        return False
    
    # Get updated annotations from BIIGLE
    response = api_client.get(f"images/{image_id}/annotations")
    response.raise_for_status()
    annos = response.json()
    
    _logger.debug(f"File {sanitize_log_input(file_name)} has {len(annos)} annotations")
    
    if not annos:
        return False

    # Process annotations
    image_path = f"{frames_prefix}/{file_name}"
    manifest_data = {"source-ref": image_path}
    class_map = {}
    anno = []
    confs = []
    
    label_ids = [e['labels'][0]['label_id'] for e in annos]
    
    for class_id in np.unique(label_ids):
        idx = [i for i, e in enumerate(label_ids) if e == class_id]
        label = annos[idx[0]]['labels'][0]['label']['name']
        class_map[str(class_id)] = label
        
        for i in idx:
            [x1, y1, x2, _, x2, y2, x1, _] = annos[i]['points']
            top = y1
            left = x1
            width = x2 - x1
            height = y2 - y1
            
            anno.append({
                "class_id": str(class_id),
                "top": int(top),
                "left": int(left),
                "height": int(height),
                "width": int(width)
            })
            confs.append({"confidence": 1.0})
    
    label_data = {
        "bounding-box": {
            "image_size": [{
                "width": json_data['bounding-box']['image_size'][0]['width'],
                "height": json_data['bounding-box']['image_size'][0]['height'],
                "depth": json_data['bounding-box']['image_size'][0]['depth']
            }],
            "annotations": anno
        },
        "bounding-box-metadata": {
            "objects": confs,
            "class-map": class_map,
            "type": "groundtruth/object-detection",
            "human-annotated": "yes",
            "creation-date": datetime.now(timezone.utc).isoformat(),
            "job-name": "labeling-job/biigle-validation"
        }
    }
    
    manifest_data.update(label_data)
    
    # Save to S3
    json_file_name_output = json_file.split("/")[-1]
    output_key = f"{validated_anno_prefix}{json_file_name_output}"
    
    write_json_to_s3(
        bucket_name=bucket_name,
        file_key=output_key,
        data=manifest_data,
        region_name=region
    )
    
    _logger.debug(f"Saved validated annotations to {sanitize_log_input(output_key)}")
    return True


if __name__ == '__main__':
    main()