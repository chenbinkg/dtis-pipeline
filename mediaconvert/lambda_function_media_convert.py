import boto3
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info('Starting MediaConvert job')
    # Assuming the event is an S3 creation event, extract the file key from the event
    input_key = event['Records'][0]['s3']['object']['key']
    bucket_name = event['Records'][0]['s3']['bucket']['name']
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
        
        return {
            "statusCode": 200,
            "body": f"Processing file: {input_file}"
        }
    else:
        # If file type is unknown, log and exit
        logger.error(f"Unrecognized file type for key: {input_key}")
        return {
            "statusCode": 400,
            "body": f"Unsupported file type for key: {input_key}"
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