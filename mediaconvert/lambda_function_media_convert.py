import boto3
import os
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info('Starting MediaConvert job')
    # Assuming the event is an S3 creation event, extract the file key from the event
    logger.info(f"received event: {json.dumps(event)}")
    # Read json data
    unprocessed_files = []
    processed_files = []
    for record in event["Records"]:
        try:
            # Parse SQS message body
            if "body" in record.keys():
                message_body = json.loads(record["body"])
            else:
                message_body = record
            logger.info(f"Processing message body: {message_body}")

            # initialize
            bucket_names = []
            input_keys = []
            # If it's from S3 event notification
            if "Records" in message_body:
                for s3_event in message_body["Records"]:
                    bucket_name = s3_event["s3"]["bucket"]["name"]
                    input_key = s3_event["s3"]["object"]["key"]
                    bucket_names.append(bucket_name)
                    input_keys.append(input_key)
            else:
                # If it's from customised message
                bucket_name = message_body["s3"]["bucket"]["name"]
                input_key = message_body["s3"]["object"]["key"]
                bucket_names.append(bucket_name)
                input_keys.append(input_key)
            
            for bucket_name, input_key in zip(bucket_names, input_keys):
                if not bucket_name or not input_key:
                    logger.warning(
                        "Missing 'bucket' or 'key' in message body: %s",
                        message_body,
                    )
                    continue
                else:
                    logger.info(
                        "Processing S3 file - Bucket: %s, Key: %s",
                        bucket_name,
                        input_key,
                    )
                    # input_key = event['Records'][0]['s3']['object']['key']
                    # bucket_name = event['Records'][0]['s3']['bucket']['name']
                    # # Define the input and output settings
                    # input_file = 's3://dtis-ofop-851725470721-raw-testing/TAN2009/047/video/20200814115516.m2ts'  # or .m2ts
                    # output_file = 's3://dtis-ofop-851725470721-raw-testing/TAN2009/047/video/20200814115516'
                    # Check if the file is an M2TS file
                    if input_key.endswith('.m2ts') or input_key.endswith('.m2t'):
                        # Define the input and output settings
                        input_file = f's3://{bucket_name}/{input_key}'
                        input_filename = input_key.split("/")[-1]
                        output_filename = input_key.split("/")[-1].split(".")[0]
                        output_key = input_key.replace(input_filename, output_filename)
                        output_file = f's3://{bucket_name}/{output_key}'
                        
                        # Log the extracted input file (optional)
                        logger.info(f"Input file: {input_file}")
                        logger.info(f"Output file: {output_file}")
                        
                        # Create the MediaConvert job
                        create_video_convert_job(input_file, output_file)
                        processed_files.append(input_key)
                    else:
                        unprocessed_files.append(input_key)
        except Exception as e:
            logger.error(f"Error processing record: {str(e)}")
            # Optionally, handle failed records
            continue
    
    if len(processed_files)>0:
        return {
            "statusCode": 200,
            "body": f"Processing file: {processed_files}"
        }
    else:
        # If file type is unknown, log and exit
        logger.error(f"Unrecognized file type for key: {unprocessed_files}")
        return {
            "statusCode": 400,
            "body": f"Unsupported file type for key: {unprocessed_files}"
        }
    
def video_convert_job_setting(input_file, output_file):
    # Create the job settings
    job_settings = {
        'Role': 'arn:aws:iam::851725470721:role/dtis-mediaconvert-testing',
        'Settings': {
            'Inputs': [
                {
                    'FileInput': input_file,
                    'VideoSelector': {
                        'ColorSpace': 'FOLLOW'
                    },
                    'AudioSelectors': {
                        'Audio Selector 1': {
                            'DefaultSelection': 'DEFAULT'
                        }
                    }
                }
            ],
            'OutputGroups': [
                {
                    'Name': 'File Group',
                    'OutputGroupSettings': {
                        'Type': 'FILE_GROUP_SETTINGS',
                        'FileGroupSettings': {
                            'Destination': output_file,
                            'DestinationSettings': {
                                'S3Settings': {
                                    'StorageClass': 'STANDARD_IA'  # Set the storage class to Standard-IA
                                }
                            }
                        }
                    },
                    'Outputs': [
                        {
                            'ContainerSettings': {
                                'Container': 'MP4'
                            },
                            'VideoDescription': {
                                'CodecSettings': {
                                    'Codec': 'H_264',
                                    'H264Settings': {
                                        'RateControlMode': 'QVBR',
                                        'QualityTuningLevel': 'SINGLE_PASS',
                                        'MaxBitrate': 5000000
                                    }
                                }
                            },
                            'AudioDescriptions': [
                                {
                                    'CodecSettings': {
                                        'Codec': 'AAC',
                                        'AacSettings': {
                                            'Bitrate': 96000,
                                            'CodingMode': 'CODING_MODE_2_0',
                                            'SampleRate': 48000
                                        }
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
    return job_settings

def create_video_convert_job(input_file, output_file, region_name='ap-southeast-2'):
    # Initialize the MediaConvert client
    mediaconvert_client = boto3.client('mediaconvert', region_name=region_name)

    # Update the client with the endpoint URL
    # region = os.environ['AWS_DEFAULT_REGION']
    endpoints = boto3.client('mediaconvert', region_name=region_name) \
                .describe_endpoints()
    mediaconvert_client = boto3.client('mediaconvert', region_name=region_name, 
                                endpoint_url=endpoints['Endpoints'][0]['Url'], 
                                verify=False)

    # Get video job settings
    job_settings = video_convert_job_setting(input_file, output_file)
    
    # Create the MediaConvert job
    response = mediaconvert_client.create_job(
        Role=job_settings['Role'],
        Settings=job_settings['Settings']
    )

    logger.info(f"Job created: {response['Job']['Id']}")