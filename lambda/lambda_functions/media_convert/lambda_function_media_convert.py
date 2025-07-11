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
    # read output bucket name from environment variable
    output_bucket = os.environ['OUTPUT_BUCKET']
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
                    # after mp4 conversion, the output file will be:
                    # 's3://dtis-ofop-851725470721-raw-testing/TAN2009/047/video/20200814115516.mp4'
                    
                    # Define the input and output settings
                    input_file = f's3://{bucket_name}/{input_key}'
                    # Define the output location for frames
                    base_output_key = os.path.splitext(input_key)[0] # Remove the file extension
                    output_frames_key = f'{base_output_key}/frames'
                    output_frames_dir = f's3://{output_bucket}/{output_frames_key}'
                    # Check if the file is an M2TS file
                    if input_key.endswith('.m2ts') or input_key.endswith('.m2t'):
                        # input_filename = input_key.split("/")[-1] # Get the filename from the key
                        # output_filename = input_key.split("/")[-1].split(".")[0] # Remove the file extension
                        # output_key = input_key.replace(input_filename, output_filename) # Remove the file extension from the key
                        # output_file = f's3://{bucket_name}/{output_key}' # output key has file name only without extension

                        output_file = f's3://{output_bucket}/{base_output_key}'
                        
                        # Log the extracted input file (optional)
                        logger.info(f"Input file: {input_file}")
                        logger.info(f"Output file: {output_file}")
                        logger.info(f"Output frames location: {output_frames_dir}")
                        
                        # Create the MediaConvert job for M2TS to MP4 conversion and frame extraction
                        create_video_convert_job(
                            input_file=input_file, 
                            output_file=output_file,
                            output_frames_dir=output_frames_dir,
                            frame_rate=1
                            )
                        processed_files.append(input_key)
                    elif input_key.endswith('.mp4'):
                        # Process MP4 files for frame extraction
                        input_file = f's3://{bucket_name}/{input_key}'
                        
                        # Define the output location for frames
                        base_output_key = os.path.splitext(input_key)[0] # Remove the file extension
                        # Create a directory for frames
                        # output_frames_key = f'{base_output_key}/frames'
                        # output_frames = f's3://{bucket_name}/{output_frames_key}'
                        output_video_prefix = f's3://{output_bucket}/{base_output_key}'

                        logger.info(f"Input file: {input_file}")
                        logger.info(f"Output frames location: {output_frames_dir}")
                        logger.info(f"Minimal output video prefix: {output_video_prefix}")
                        
                        # Extract frames from the video
                        extract_video_frames(
                            input_file=input_file, 
                            output_frames_dir=output_frames_dir, 
                            output_video_prefix=output_video_prefix
                            )
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


def video_convert_job_setting(input_file, output_file, output_frames_dir, frame_rate=1):
    # Create the job settings
    job_settings = {
        'Role': os.environ['MEDIA_CONVERT_ROLE'],
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
                                        'QualityTuningLevel': 'MULTI_PASS_HQ',#'SINGLE_PASS',
                                        'MaxBitrate': 10000000
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
                },
                {
                    'Name': 'Frame Capture Group',
                    'OutputGroupSettings': {
                        'Type': 'FILE_GROUP_SETTINGS',
                        'FileGroupSettings': {
                            'Destination': f'{output_frames_dir}/',
                            'DestinationSettings': {
                                'S3Settings': {
                                    'StorageClass': 'STANDARD_IA'
                                }
                            }
                        }
                    },
                    'Outputs': [
                        {
                            'Extension': 'jpg',
                            'NameModifier': '_frame_',
                            'ContainerSettings': {
                                'Container': 'RAW'
                            },
                            'VideoDescription': {
                                'ScalingBehavior': 'DEFAULT',
                                'TimecodeInsertion': 'DISABLED',
                                'AntiAlias': 'ENABLED',
                                'CodecSettings': {
                                    'Codec': 'FRAME_CAPTURE',
                                    'FrameCaptureSettings': {
                                        'FramerateNumerator': frame_rate,
                                        'FramerateDenominator': 1,
                                        'MaxCaptures': 10000,  # Adjust as needed
                                        'Quality': 100  # JPEG quality (1-100)
                                    }
                                }
                            }
                        }
                    ]
                }
            ]
        }
    }
    return job_settings


def create_video_convert_job(
        input_file, output_file, output_frames_dir, 
        frame_rate=1, region_name='ap-southeast-2'
        ):
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
    job_settings = video_convert_job_setting(
        input_file=input_file, 
        output_file=output_file,
        output_frames_dir=output_frames_dir, 
        frame_rate=frame_rate
        )
    
    # Create the MediaConvert job
    response = mediaconvert_client.create_job(
        Role=job_settings['Role'],
        Settings=job_settings['Settings']
    )

    logger.info(f"Job created: {response['Job']['Id']}")


def frame_extraction_job_settings(input_file, output_frames_dir, base_output_video, frame_rate=1):
    """
    Create MediaConvert job settings for frame extraction AND a minimal video output.

    Args:
        input_file: S3 URI of the input video
        output_frames_dir: S3 URI of the output directory for frames
        base_output_video: S3 URI prefix for a minimal video output (e.g., 's3://your-bucket/output/video_')
        frame_rate: Number of frames to extract per second (default: 1 frame per second)

    Returns:
        Job settings dictionary for MediaConvert
    """
    job_settings = {
        'Role': os.environ['MEDIA_CONVERT_ROLE'],
        'Settings': {
            'Inputs': [
                {
                    'FileInput': input_file,
                    'VideoSelector': {
                        'ColorSpace': 'FOLLOW'
                    },
                    'AudioSelectors': {
                        'Audio Selector 1': {
                            'SelectorType': 'TRACK',  # Specify the selector type as TRACK
                            'Tracks': [1]             # Select the first audio track
                        }
                    }
                }
            ],
            'OutputGroups': [
                {
                    'Name': 'Frame Capture Group',
                    'OutputGroupSettings': {
                        'Type': 'FILE_GROUP_SETTINGS',
                        'FileGroupSettings': {
                            'Destination': f'{output_frames_dir}/',
                            'DestinationSettings': {
                                'S3Settings': {
                                    'StorageClass': 'STANDARD_IA'
                                }
                            }
                        }
                    },
                    'Outputs': [
                        {
                            'Extension': 'jpg',
                            'NameModifier': '_frame-$dt$',
                            'ContainerSettings': {
                                'Container': 'RAW'
                            },
                            'VideoDescription': {
                                'ScalingBehavior': 'DEFAULT',
                                'TimecodeInsertion': 'DISABLED',
                                'AntiAlias': 'ENABLED',
                                'CodecSettings': {
                                    'Codec': 'FRAME_CAPTURE',
                                    'FrameCaptureSettings': {
                                        'FramerateNumerator': frame_rate,
                                        'FramerateDenominator': 1,
                                        'MaxCaptures': 10000,  # Adjust as needed
                                        'Quality': 100  # JPEG quality (1-100)
                                    }
                                }
                            }
                        }
                    ]
                },
                {
                    'Name': 'Minimal Video Output Group',
                    'OutputGroupSettings': {
                        'Type': 'FILE_GROUP_SETTINGS',
                        'FileGroupSettings': {
                            'Destination': f'{base_output_video}',
                            'DestinationSettings': {
                                'S3Settings': {
                                    'StorageClass': 'STANDARD_IA'
                                }
                            }
                        }
                    },
                    'Outputs': [
                        {
                            'ContainerSettings': {
                                'Container': 'MOV' # or 'MP4'
                            },
                            'VideoDescription': {
                                'CodecSettings': {
                                    'Codec': 'H_264',
                                    'H264Settings': {
                                        'RateControlMode': 'QVBR',
                                        'QualityTuningLevel': 'SINGLE_PASS',
                                        'MaxBitrate': 1000000
                                    }
                                },
                                'Width': 640,   # Minimal width
                                'Height': 360  # Minimal height
                            },
                            'AudioDescriptions': [
                                {
                                    'CodecSettings': {
                                        'Codec': 'AAC',
                                        'AacSettings': {
                                            'Bitrate': 64000, # Minimal bitrate
                                            'CodingMode': 'CODING_MODE_2_0',
                                            'SampleRate': 48000
                                        }
                                    },
                                    # 'AudioSelectorName': 'Audio Selector 1'
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }

    return job_settings


def extract_video_frames(
        input_file, output_frames_dir, output_video_prefix, 
        frame_rate=1, region_name='ap-southeast-2'
        ):
    """
    Create a MediaConvert job to extract frames from a video.
    
    Args:
        input_file: S3 URI of the input video
        output_frames_dir: S3 URI of the output directory for frames
        frame_rate: Number of frames to extract per second (default: 1)
        region_name: AWS region name
    
    Returns:
        MediaConvert job ID
    """
    # Initialize the MediaConvert client
    mediaconvert_client = boto3.client('mediaconvert', region_name=region_name)

    # Update the client with the endpoint URL
    endpoints = boto3.client('mediaconvert', region_name=region_name).describe_endpoints()
    mediaconvert_client = boto3.client('mediaconvert', 
                                      region_name=region_name, 
                                      endpoint_url=endpoints['Endpoints'][0]['Url'], 
                                      verify=False)

    # Get frame extraction job settings
    job_settings = frame_extraction_job_settings(
        input_file=input_file, 
        output_frames_dir=output_frames_dir, 
        base_output_video=output_video_prefix,
        frame_rate=frame_rate
    )
    
    # Create the MediaConvert job
    response = mediaconvert_client.create_job(
        Role=job_settings['Role'],
        Settings=job_settings['Settings']
    )

    logger.info(f"Frame extraction job created: {response['Job']['Id']}")
    return response['Job']['Id']
