from typing import List
import os
import json
import sys
import boto3
import logging
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

# Function to update parameters to SSM
def update_ssm_parameter(name, value):
    """Update an SSM parameter with the given name and value."""
    try:
        ssm_client = boto3.client('ssm', region_name=os.environ.get('AWS_REGION', 'ap-southeast-2'))
        ssm_client.put_parameter(Name=name, Value=value, Type='String', Overwrite=True)
        _logger.info(f"Successfully updated SSM parameter {name}")
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        if error_code == 'ParameterLimitExceeded':
            _logger.error(f"Parameter limit exceeded for '{sanitize_log_input(name)}': {sanitize_log_input(str(e))}")
            raise RuntimeError(f"SSM parameter limit exceeded: {name}") from e
        elif error_code == 'AccessDenied':
            _logger.error(f"Access denied updating parameter '{sanitize_log_input(name)}': {sanitize_log_input(str(e))}")
            raise PermissionError(f"No permission to update SSM parameter: {name}") from e
        else:
            _logger.error(f"SSM client error updating '{sanitize_log_input(name)}': {sanitize_log_input(str(e))}")
            raise RuntimeError(f"Failed to update SSM parameter: {name}") from e
    except NoCredentialsError as e:
        _logger.error(f"AWS credentials not found for SSM update: {sanitize_log_input(str(e))}")
        raise ValueError("AWS credentials not configured for SSM") from e

def list_all_objects(bucket_name: str, prefix: str) -> List[str]:
    """Lists all objects in an S3 bucket with a given prefix."""
    s3 = boto3.client('s3')
    paginator = s3.get_paginator('list_objects_v2')
    objects = []
    
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        if 'Contents' in page:
            objects.extend([obj['Key'] for obj in page['Contents']])
    
    return objects

def read_json_from_s3(bucket_name: str, file_key: str, s3_client=None) -> dict:
    """
    Reads a JSON file from an AWS S3 bucket and returns its content as a dictionary.

    Args:
        bucket_name (str): The name of the S3 bucket.
        file_key (str): The S3 object key (path to the file within the bucket).
        s3_client: Optional boto3 S3 client to reuse. If None, creates a new one.

    Returns:
        dict | None: The content of the JSON file as a dictionary if successful,
                     otherwise None.
    """
    if s3_client is None:
        s3_client = boto3.client('s3')
    
    try:
        # Get the object from S3
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        
        # Read the content of the object
        file_content = response['Body'].read().decode('utf-8')
        
        # Parse the content as JSON
        json_data = json.loads(file_content)
        
        # print(f"Successfully read and parsed '{file_key}' from bucket '{bucket_name}'.")
        return json_data
        
    except NoCredentialsError as e:
        _logger.error(f"AWS credentials not found: {e}")
        raise ValueError("AWS credentials not configured") from e
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == "NoSuchKey":
            _logger.error(f"File '{file_key}' not found in bucket '{bucket_name}'")
            raise FileNotFoundError(f"S3 object not found: {file_key}") from e
        elif error_code == "AccessDenied":
            _logger.error(f"Access denied to bucket '{bucket_name}' or file '{file_key}'")
            raise PermissionError(f"Access denied to S3 resource: {bucket_name}/{file_key}") from e
        else:
            _logger.error(f"AWS client error: {e}")
            raise RuntimeError(f"S3 operation failed: {error_code}") from e
    except json.JSONDecodeError as e:
        _logger.error(f"Invalid JSON format in file '{file_key}': {e}")
        raise ValueError(f"Invalid JSON in S3 object: {file_key}") from e
    except UnicodeDecodeError as e:
        _logger.error(f"Unable to decode file content from '{file_key}': {e}")
        raise ValueError(f"File encoding error: {file_key}") from e

def write_json_to_s3(
    bucket_name: str,
    file_key: str,
    data: dict,
    region_name: str = 'ap-southeast-2'
):
    """
    Writes a Python dictionary (or list) as a JSON file to an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        file_key (str): The S3 object key (path to the file in the bucket), e.g., 'folder/data.json'.
        data (dict): The Python dictionary or list to be written as JSON.
        region_name (str, optional): The AWS region of your S3 bucket (e.g., 'us-east-1'). If None, boto3 will
                                     look for the region in environment variables (AWS_REGION) or other configurations.
    """
    try:
        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            region_name=region_name
        )

        # Convert Python dictionary to a JSON string
        json_string = json.dumps(data, indent=4) # indent for pretty-printing in S3

        # Upload the JSON string to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=file_key,
            Body=json_string,
            ContentType='application/json' # Set the content type to JSON
        )

        print(f"Successfully wrote JSON data to s3://{bucket_name}/{file_key}")

    except Exception as e:
        print(f"Error writing JSON to S3: {e}")

def get_aws_credentials_from_secrets_manager(secret_name):
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
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=session.region_name # Use the default region of the session
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name,
            region_name=session.region_name
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
            secret = get_secret_value_response['SecretString']
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