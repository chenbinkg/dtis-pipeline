import argparse
import logging
import sys
import json
from datetime import datetime
import boto3
import pandas as pd
import requests
from botocore.exceptions import NoCredentialsError, ClientError

# Add parent directory to path for imports when running from /opt/ml/processing/input/code/
sys.path.insert(0, '/opt/ml/processing')

from mongodb import MongoDBOps
from biigle_api import Api
from utils import (
    sanitize_log_input,
    get_ssm_parameter,
    update_ssm_parameter,
    list_all_objects,
    read_json_from_s3
)

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger()


def get_aws_credentials_from_secrets_manager(secret_name, region_name='ap-southeast-2'):
    """
    Retrieves AWS access key ID and secret access key from Secrets Manager.

    Args:
        secret_name (str): The name or ARN of the secret in Secrets Manager.

    Returns:
        tuple: A tuple containing (access_key_id, secret_access_key)
               Returns (None, None) if the secret is not found or an error occurs.
    """
    # Create a Secrets Manager client
    # boto3 will automatically use credentials from environment variables,
    # shared credential files (~/.aws/credentials), or IAM roles if available.
    # session = boto3.session.Session()
    client = boto3.client(
        'secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name,
        )
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'DecryptionFailureException':
            _logger.error(f"KMS decryption failed for secret '{sanitize_log_input(secret_name)}': {sanitize_log_input(str(e))}")
            raise PermissionError(f"Cannot decrypt secret '{secret_name}' - check KMS permissions") from e
        elif error_code == 'InternalServiceErrorException':
            _logger.error(f"AWS Secrets Manager internal error: {sanitize_log_input(str(e))}")
            raise RuntimeError(f"Secrets Manager service error for '{secret_name}'") from e
        elif error_code == 'InvalidParameterException':
            _logger.error(f"Invalid parameter for secret '{sanitize_log_input(secret_name)}': {sanitize_log_input(str(e))}")
            raise ValueError(f"Invalid secret name or parameter: '{secret_name}'") from e
        elif error_code == 'InvalidRequestException':
            _logger.error(f"Invalid request for secret '{sanitize_log_input(secret_name)}': {sanitize_log_input(str(e))}")
            raise ValueError(f"Invalid request state for secret '{secret_name}'") from e
        elif error_code == 'ResourceNotFoundException':
            _logger.error(f"Secret '{sanitize_log_input(secret_name)}' not found: {sanitize_log_input(str(e))}")
            raise FileNotFoundError(f"Secret '{secret_name}' does not exist") from e
        else:
            _logger.error(f"Unexpected AWS error for secret '{sanitize_log_input(secret_name)}': {sanitize_log_input(str(e))}")
            raise RuntimeError(f"Secrets Manager error: {error_code}") from e
    else:
        # Decrypts secret using the associated KMS key.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString'].strip()
            try:
                secret_dict = json.loads(secret)
            except json.JSONDecodeError as e:
                _logger.error(f"Invalid JSON format in secret '{sanitize_log_input(secret_name)}': {sanitize_log_input(str(e))}")
                raise ValueError(f"Secret '{secret_name}' contains invalid JSON") from e

            access_key_id = secret_dict.get("access_key_id")
            secret_access_key = secret_dict.get("secret_access_key")

            if access_key_id and secret_access_key:
                return access_key_id, secret_access_key
            else:
                _logger.error(f"Missing credentials in secret '{sanitize_log_input(secret_name)}' - expected 'access_key_id' and 'secret_access_key'")
                raise ValueError(f"Incomplete credentials in secret '{secret_name}'")
        else:
            _logger.error(f"Secret '{sanitize_log_input(secret_name)}' is in binary format, not supported")
            raise ValueError(f"Binary secret format not supported: '{secret_name}'")

def main(
        bucket_name,
        frames_prefix,
        cruise,
        station,
        aws_region,
        secret_name,
        api_email,
        api_token,
        api_url,
        storage_disk_id,
        user_pattern,
        user_lastname,
        label_tree_id,
        ssm_param_mongodb_uri,
        mongodb_db,
        mongodb_collection
):
    """
    Main function to process BIIGLE annotation session.

    Args:
        bucket_name (str): S3 bucket name
        frames_prefix (str): S3 prefix for video frames
        cruise (str): Cruise identifier
        station (str): Station identifier
        aws_region (str): AWS region
        secret_name (str): Secret name to fetch access key and id to create user storage disk
        api_email (str): Email address for biigle API
        api_token (str): Token for biigle API
        api_url (str): Base URL for biigle API
        storage_disk_id: saved storage disk id, if already created
        user_pattern: user pattern to search
        user_lastname: user last name to search for job permission
        label_tree_id: label tree id to add to the project
        ssm_param_mongodb_uri: ssm param for mongodb uri
        mongodb_db: mongodb database name
        mongodb_collection: mongodb collection name to store the biigle anno session
    """
    _logger.info("Starting RFDETR annotation matching job")
    _logger.info(
        f"Processing images for cruise: {sanitize_log_input(cruise)}, "
        f"station: {sanitize_log_input(station)}, at bucket: {sanitize_log_input(bucket_name)}")

    # SageMaker paths
    input_data_path = '/opt/ml/processing/matched_annotations'
    _logger.info(f"Input data path: {input_data_path}")

    # generate key for the file
    _logger.info(f"frame prefix: {sanitize_log_input(frames_prefix)}")
    # e.g. "TAN0616/095/video/TAN0616_095/frames/"

    project_name = f'{cruise}_{station}'
    # TO-DO: use cruise as the project name and stations as volume names
    try:
        # Attempt to get AWS credentials from Secrets Manager
        _logger.info(
            f"Attempting to retrieve AWS credentials from "
            f"Secrets Manager with secret name: {secret_name}"
            )
        access_key, access_secret = get_aws_credentials_from_secrets_manager(secret_name, aws_region)
    except Exception as e:
        _logger.error(f"Error retrieving AWS credentials from Secrets Manager: {sanitize_log_input(str(e))}")
        access_key = None
        access_secret = None

    endpoint = f'https://{bucket_name}.s3.{aws_region}.amazonaws.com'
    img_files = list_all_objects(bucket_name, frames_prefix)
    matched_anno_prefix = frames_prefix.replace("/frames", "/matched_annotations")
    # s3_base_url = f"s3://{bucket_name}/{frames_prefix}"
    image_files_from_s3 = [e.split("/")[-1] for e in img_files]
    api_client = Api(
        email=api_email,
        token=api_token,
        base_url=api_url
    )
    _logger.info("\n--- API Function ---")
    
    # Create S3 User Disk if disk does not exist
    _logger.info("\nAttempting to create an S3 user disk...")
    try:
        # IMPORTANT: Replace these with your actual S3 credentials and bucket info
        storage_disk_response = api_client.create_user_disk(
            type="s3",
            name=bucket_name,
            key=access_key,
            secret=access_secret,
            bucket=bucket_name,
            region=aws_region,
            endpoint=endpoint
        )
        storage_disk_response.raise_for_status()
        storage_disk_data = storage_disk_response.json()
        storage_disk_id = storage_disk_data.get('id')
        disk_path = f'disk-{storage_disk_id}'
        _logger.info(
            f"S3 Disk created. ID: {storage_disk_data.get('id')}, "
            f"Name: {storage_disk_data.get('name')}, Path: {disk_path}, "
            f"Status Code: {storage_disk_response.status_code}"
            )
        update_ssm_parameter("/dtis/biigle/disk-id", str(storage_disk_id))
    except requests.exceptions.RequestException as e:
        _logger.error(f"Error creating S3 disk: {sanitize_log_input(str(e))}")
        if e.response is not None:
            _logger.info(f"Response Content: {e.response.text}")
    except ValueError as e:
        _logger.error(f"Validation error for S3 disk: {sanitize_log_input(str(e))}")
    except Exception as e:
        disk_path = f'disk-{storage_disk_id}'
        _logger.warning(f"An unexpected error occurred during S3 disk creation: {sanitize_log_input(str(e))}")
        _logger.info(f"Use existing disk id {storage_disk_id}, Disk path: {disk_path}")

    # Example: Find a user
    _logger.info(f"\nAttempting to find users with pattern '{user_pattern}'...")
    try:
        find_user_response = api_client.find_user(pattern=user_pattern)
        find_user_response.raise_for_status()
        users_found = find_user_response.json()
        _logger.info(f"Users found (first 10 matches): {users_found}. Status Code: {find_user_response.status_code}")
        user_found = [e for e in users_found if e['lastname'] == user_lastname]
        if user_found:
            user_id = user_found[0]['id']
            user_role_id = user_found[0]['role_id']
            _logger.info(f"User found: {user_found}.")
    except requests.exceptions.RequestException as e:
        _logger.error(f"Error finding user: {sanitize_log_input(str(e))}")
        if e.response is not None:
            _logger.error(f"Response Content: {e.response.text}")
    except Exception as e:
        _logger.error(f"An unexpected error occurred during user search: {sanitize_log_input(str(e))}")

    # --- Step 1: Create a New Project ---
    _logger.info(f"\n--- Step 1: Creating a New Project ---")
    new_project_id = None
    dt_str = datetime.now().strftime("%Y%m%dT%H%M%S")
    project_name = f"AnnotationProject_{project_name}_{dt_str}" # Unique name to avoid conflicts
    project_description = f"Annotation project created for {project_name}."
    _logger.info(f"\nAttempting to create new project '{project_name}'...")

    try:
        project_response = api_client.create_project(name=project_name, description=project_description)
        project_response.raise_for_status()
        project_data = project_response.json()
        new_project_id = project_data.get('id')
        _logger.info(f"Project '{project_name}' created. ID: {new_project_id}, Status Code: {project_response.status_code}")
        _logger.info(f"Response Body: {project_data}")
    except requests.exceptions.RequestException as e:
        _logger.error(f"Error creating project: {e}")
        if e.response is not None:
            _logger.error(f"Response Content: {e.response.text}")
    except Exception as e:
        _logger.error(f"An unexpected error occurred during project creation: {e}")

    _logger.info(f"\n--- Step 2: Adding a Member to Project ID: {new_project_id} ---")

    try:
        member_response = api_client.add_member_to_project(
            project_id=new_project_id,
            user_id=user_id,
            project_role_id=1
        )
        member_response.raise_for_status()
        _logger.info(
            f"User {user_pattern} successfully added to project {new_project_id} "
            f"with role ID {user_id}. Status Code: {member_response.status_code}"
            )
    except requests.exceptions.RequestException as e:
        _logger.error(f"Error adding member: {e}")
        if e.response is not None:
            _logger.error(f"Response Content: {e.response.text}")
        _logger.error("Warning: Could not add member. Subsequent steps might continue but the member won't be assigned.")
    except Exception as e:
        _logger.error(f"An unexpected error occurred during member addition: {e}")

    # --- Step 3: Authorize Project on Label Tree ---
    _logger.info(f"\n--- Step 3: Authorizing Project {new_project_id} on Label Tree {label_tree_id} ---")
    try:
        # Note: This API requires 'labelTreeAdmin' permission.
        auth_response = api_client.authorize_project_on_label_tree(
            label_tree_id=label_tree_id,
            project_id_to_authorize=new_project_id
        )
        auth_response.raise_for_status()
        _logger.info(
            f"Project {new_project_id} successfully authorized on label tree {label_tree_id}. "
            f"Status Code: {auth_response.status_code}"
            )
    except requests.exceptions.RequestException as e:
        _logger.error(f"Error authorizing project on label tree: {e}")
        if e.response is not None:
            _logger.error(f"Response Content: {e.response.text}")
        _logger.error(
            f"Warning: Could not authorize project on label tree. "
            f"This might indicate permission issues or that the label tree is already public."
            )
    except Exception as e:
        _logger.error(f"An unexpected error occurred during project authorization on label tree: {e}")

    # --- Step 4: Add a Label Tree to the Project ---
    _logger.info(f"\n--- Step 4: Adding a Label Tree to Project ID: {new_project_id} ---")
    # IMPORTANT: Replace 123 with a valid label tree ID from your BIIGLE instance.
    # This label tree must be public or authorized for your project.

    try:
        label_tree_response = api_client.add_label_tree_to_project(
            project_id=new_project_id,
            label_tree_id=label_tree_id
        )
        label_tree_response.raise_for_status()
        _logger.info(
            f"Label tree {label_tree_id} successfully added to project {new_project_id}. "
            f"Status Code: {label_tree_response.status_code}"
            )
    except requests.exceptions.RequestException as e:
        _logger.error(f"Error adding label tree: {e}")
        if e.response is not None:
            _logger.error(f"Response Content: {e.response.text}")
        _logger.error("Warning: Could not add label tree. Subsequent steps might fail if a label tree is required.")
    except Exception as e:
        _logger.error(f"An unexpected error occurred during label tree addition: {e}")

    # --- Step 5: Create a Pending Volume within the new project ---
    _logger.info(f"\n--- Step 5: Creating a Pending Image Volume in Project ID: {new_project_id} ---")
    pending_volume_id = None
    try:
        _logger.info("\nCreating pending volume without metadata...")
        pending_volume_response = api_client.create_pending_volume(
            project_id=new_project_id,
            media_type="image"
        )
        pending_volume_response.raise_for_status()
        pending_volume_data = pending_volume_response.json()
        pending_volume_id = pending_volume_data.get('id')
        _logger.info(f"Pending volume created. ID: {pending_volume_id}, Status Code: {pending_volume_response.status_code}")
        _logger.info(f"Response Body: {pending_volume_data}")

    except requests.exceptions.RequestException as e:
        _logger.error(f"Error creating pending volume: {e}")
        if e.response is not None:
            _logger.error(f"Response Content: {e.response.text}")
    except FileNotFoundError as e:
        _logger.error(f"File not found error: {e}")
    except Exception as e:
        _logger.error(f"An unexpected error occurred during pending volume creation: {e}")

    # --- Step 6: Activate Pending Volume within the new project ---
    _logger.info(f"\n--- Step 6: Activating a Pending Image Volume: {pending_volume_id} ---")
    try:
        url = f"{disk_path}://{frames_prefix}"
        final_volume_response = api_client.create_volume(
            pending_volume_id=pending_volume_id,
            name=f"S3 Images Volume for {project_name}",
            url=url,
            files=image_files_from_s3,
            handle=None,
            import_annotations=True,
            import_file_labels=True
        )
        final_volume_response.raise_for_status()
        _logger.info(f"Final volume created for ID {pending_volume_id}. Status Code: {final_volume_response.status_code}")
        _logger.info(f"Response Body: {final_volume_response.json()}")
    except requests.exceptions.RequestException as e:
        _logger.error(f"Error activating volume {pending_volume_id}: {e}")
        if e.response is not None:
            _logger.error(f"Response Content: {e.response.text}")
    except Exception as e:
        _logger.error(f"An unexpected error occurred during volume activation for ID {pending_volume_id}: {e}")

    # --- Step 7: Convert Annotation from Rekognition to BIIGLE Format ---
    _logger.info(f"\n--- Step 7: Convert Annotation from Rekognition to BIIGLE Format for Image Volume ---")
    # get created volume id
    response = api_client.get(f"projects/{new_project_id}/volumes")
    response.raise_for_status()
    data = response.json()
    if data:
        volume_id = data[0]['id']
        _logger.info(f"Found volume id {volume_id} for new project: {new_project_id}")
    image_names = api_client.fetch_image_data_from_api(volume_id=volume_id)
    _logger.info(f"Total image data retrieved with image id: {len(image_names)}, from volume {volume_id}")

    # Read annotations
    json_files = list_all_objects(bucket_name, matched_anno_prefix)
    _logger.info(f"Matched annotation json files found: {len(json_files)}")
    
    # Create a single S3 client for reuse
    s3_client = boto3.client('s3')
    
    # Create a list to hold the resulting data structure
    annotations = []
    for json_file in json_files:
        json_data = read_json_from_s3(bucket_name, json_file, s3_client)
        annos = json_data['bounding-box']['annotations']
        file_name = json_data['source-ref'].split('/')[-1]
        image_id = [i for i, e in image_names.items() if e == file_name][0]
        for k, anno in enumerate(annos):
            top = anno['top']
            left = anno['left']
            height = anno['height']
            width = anno['width']
            y1 = top
            x1 = left
            x2 = width + x1
            y2 = height + y1
            # Construct the points as [xmin, ymin, xmax, ymin, xmax, ymax, xmin, ymax]
            points = [x1, y1, x2, y1, x2, y2, x1, y2]
            label_id = anno['class_id']
            confidence = json_data['bounding-box-metadata']['objects'][k]['confidence']
            # Create the annotation dictionary
            annotation = {
                "image_id": int(image_id),
                "shape_id": 5,
                "label_id": int(label_id),  # Now mapped from class_id to label_id
                "confidence": float(confidence),
                "points": points
            }
            # Append to annotations list
            if len(str(int(label_id))) == 6:
                annotations.append(annotation)
    _logger.info(f"Annotation json files converted: {len(annotations)}")

    # --- Step 8: Update annotation for the new volume using image id and converted annotations ---
    _logger.info(f"\n--- Step 8: Update Annotation for Image Volume: {volume_id} ---")

    # Define headers
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    # Split annotations into batches with adaptive batch size
    def split_annotation(df, batch_size=None):
        if batch_size is None:
            # Adaptive batch size based on dataset size
            total_annotations = len(df)
            if total_annotations <= 100:
                batch_size = 50
            elif total_annotations <= 1000:
                batch_size = 100
            else:
                batch_size = 200
        
        return [df[i:i + batch_size] for i in range(0, len(df), batch_size)]
    
    # Convert annotations for batching
    annotations_df = pd.DataFrame(annotations)
    batches = split_annotation(annotations_df)
    
    # Upload each batch
    for batch in batches:
        try:
            # Make the POST request for current batch
            response = api_client.post('image-annotations', json=batch.to_dict(orient='records'), headers=headers)
            response.raise_for_status()  # Will raise HTTPError for bad responses
    
            # Process the response
            response_json = response.json()  # Parse JSON if needed
            _logger.info("Batch uploaded successfully!")
            _logger.info(f"Response JSON: {response_json}")
    
        except requests.exceptions.HTTPError as err:
            _logger.error(f"Failed to upload annotations batch. Status code: {err.response.status_code}")
            _logger.error(f"Response content: {sanitize_log_input(err.response.text)}")
            continue  # Continue with next batch
    
        except requests.exceptions.ConnectionError as e:
            _logger.error(f"Connection error during batch upload: {sanitize_log_input(str(e))}")
            continue
            
        except requests.exceptions.Timeout as e:
            _logger.error(f"Timeout error during batch upload: {sanitize_log_input(str(e))}")
            continue
    
        except requests.exceptions.RequestException as e:
            _logger.error(f"Request error occurred: {sanitize_log_input(str(e))}")
            continue
    
        except Exception as e:
            _logger.error(f"Unexpected error during batch upload: {sanitize_log_input(str(e))}")
            continue

    # write to MongoDB (dtis_biigle_annotation_session) for BIIGLE annotation info
    mongodb_uri = get_ssm_parameter(ssm_param_mongodb_uri, "")
    mongo_ops = MongoDBOps(mongodb_uri=mongodb_uri)
    s3_input_uri = f"s3://{bucket_name}/{frames_prefix}"
    biigle_info = {
        "s3_input_uri": s3_input_uri,
        "storage_disk_id": storage_disk_id,
        "biigle_project_id": new_project_id,
        "biigle_project_name": project_name,
        "biigle_project_description": project_description,
        "biigle_volume_id": volume_id,
        "biigle_volume_name": f"S3 Images Volume for {project_name}",
        "biigle_volume_description": f"S3 Images Volume for {project_name}",
        "biigle_volume_url": f"{disk_path}://{frames_prefix}",
        "biigle_volume_files": image_files_from_s3,
        "biigle_annotation_user_id": user_id,
        "biigle_annotation_user_name": f"{user_pattern} {user_lastname}",
        "biigle_annotation_job_status": "Created",
        "biigle_annotation_job_start_time": str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        "biigle_annotation_job_end_time": None,
        "biigle_annotation_job_duration": None,
        "biigle_annotation_job_output": None,
    }
    mongo_ops.write_to_mongodb(
        db_name=mongodb_db,
        collection_name=mongodb_collection,
        data=biigle_info
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket_name", type=str, default=None)
    parser.add_argument("--frames_prefix", type=str, default=None)
    parser.add_argument("--cruise", type=str, default=None)
    parser.add_argument("--station", type=str, default=None)
    parser.add_argument("--aws_region", type=str, default="ap-southeast-2")
    parser.add_argument("--secret_name", type=str, default="/dtis/biigle/create-user-disk-secret-name")
    parser.add_argument("--api_email", type=str, default="")
    parser.add_argument("--api_token", type=str, default="")
    parser.add_argument("--api_url", type=str, default="")
    parser.add_argument("--storage_disk_id", type=str, default="")
    parser.add_argument("--user_pattern", type=str, default="")
    parser.add_argument("--user_lastname", type=str, default="")
    parser.add_argument("--label_tree_id", type=str, default="")
    parser.add_argument("--ssm_param_mongodb_uri", type=str, default="")
    parser.add_argument("--mongodb_db", type=str, default="")
    parser.add_argument("--dtis_biigle_anno_sess_collection", type=str, default="")

    args, _ = parser.parse_known_args()

    _logger.info(f"Received arguments {args}")
    main(
        bucket_name=args.bucket_name,
        frames_prefix=args.frames_prefix,
        cruise=args.cruise,
        station=args.station,
        aws_region=args.aws_region,
        secret_name=args.secret_name,
        api_email=args.api_email,
        api_token=args.api_token,
        api_url=args.api_url,
        storage_disk_id=args.storage_disk_id,
        user_pattern=args.user_pattern,
        user_lastname=args.user_lastname,
        label_tree_id=args.label_tree_id,
        ssm_param_mongodb_uri=args.ssm_param_mongodb_uri,
        mongodb_db=args.mongodb_db,
        mongodb_collection=args.dtis_biigle_anno_sess_collection
    )
