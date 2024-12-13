import os
import re
import sys
import time
import boto3
from datetime import datetime
from tqdm import tqdm
# import mimetypes
import subprocess
from botocore.exceptions import ClientError

# Initialize AWS Clients
s3_client = boto3.client('s3')
sts_client = boto3.client('sts')
lambda_client = boto3.client('lambda')

bucket_name = None
lambda_function_name = None

# Setting up the variables
images_dir = os.getenv("NIWA_IMAGES_DIR", "images")
videos_dir = os.getenv("NIWA_VIDEOS_DIR", "videos")
ofop_dir = os.getenv("NIWA_OFOP_DIR", "ofop")
NIWA_DRY_RUN = os.getenv("NIWA_DRY_RUN", "false").lower()
NIWA_ENVIRONMENT = os.getenv("NIWA_ENVIRONMENT")
NIWA_CRUISE_ID = os.getenv("NIWA_CRUISE_ID")
# Check NIWA cruise id configuration
if not NIWA_CRUISE_ID:
    print("NIWA_CRUISE_ID not set, please set it explicitly")
    sys.exit(1)
# Setup environment configurations
if not NIWA_ENVIRONMENT:
    print("Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production")
    sys.exit(1)
elif NIWA_ENVIRONMENT == "testing":
    bucket_name = f"dtis-ofop-{sts_client.get_caller_identity()['Account']}-raw-testing"
    lambda_function_name = "dtis-ofop-testing"
elif NIWA_ENVIRONMENT == "production":
    bucket_name = f"dtis-ofop-{sts_client.get_caller_identity()['Account']}-raw-production"
    lambda_function_name = "dtis-ofop-production"
else:
    raise ValueError("Invalid NIWA_ENVIRONMENT value. Please set it to 'testing' or 'production'")
# Check Dry Run configuration
if NIWA_DRY_RUN not in ["true", "false"]:
    print("Invalid NIWA_DRY_RUN value. Please set it to 'true' or 'false'")
    sys.exit(1)

success_file = "success.txt"
error_file = "error.txt"
sync_output_file = "sync_logs.txt"
plan_file = "plan.txt"
aws_region = "ap-southeast-2"

# Regex patterns
patterns = {
    "image": [
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.JPEG$", # e.g. TAN1802_160_DTIS__004.jpeg
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.JPG$", # e.g. TAN1802_160_DTIS__004.jpg
        r"^[A-Z]{3}[0-9]{4}_STN_[0-9]{3,}_[0-9]{3}\.JPEG$", # e.g. TAN1802_Stn_160_004.jpeg
        r"^[A-Z]{3}[0-9]{4}_STN_[0-9]{3,}_[0-9]{3}\.JPG$", # e.g. TAN1802_Stn_160_004.jpg
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_[0-9]{3}\.JPEG$", # e.g. TAN1802_160_004.jpg
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_[0-9]{3}\.JPG$", # e.g. TAN1802_160_004.jpeg
    ],
    "video": [
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}\.M2T[S]?$", # e.g. TAN1802_001.m2t or TAN1802_001.m2ts
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_[0-9]{1}\.M2T[S]?$", # e.g. TAN1802_001_1.m2t or TAN1802_001_2.m2ts
        r"^[0-9]{4,}\.M2T[S]?$", # e.g. 201012220153001.m2t or 201012220153001.m2ts (only digits)
    ],
    "ofop": [
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_POSI\.TXT$", # e.g. TAN1802_001_posi.txt
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_PROT\.TXT$", # e.g. TAN1802_001_prot.txt
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_OBSER\.TXT$", # e.g. TAN1802_001_obser.txt
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_RERUN.*_OBSER\.TXT$", # e.g. TAN1802_001.sth_rerun.sth_obser.txt
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_RERUN.*_PROT\.TXT$", # e.g. TAN1802_001.sth_rerun.sth_prot.txt
    ]
}

# Functions
def verify_s3_bucket(bucket_name):
    try:
        s3 = boto3.client("s3", region_name=aws_region)
        s3.head_bucket(Bucket=bucket_name)
        print(f"Bucket Exists: {bucket_name}")
    except ClientError as e:
        print(f"S3 bucket is not accessible or does not exist: {bucket_name}", file=sys.stderr)
        print(e, file=sys.stderr)
        with open(error_file, "a") as ef:
            ef.write(f"S3 bucket error: {bucket_name}\n")
        sys.exit(1)

# def get_station_id(file_path):
#     file_path_upper_case = file_path.upper()
#     if NIWA_CRUISE_ID not in file_path_upper_case:
#         print(f"Error: File {file_path} does not come from the cruise ID: {NIWA_CRUISE_ID}", file=sys.stderr)
#         return None
    
#     patterns = [
#         rf"/{NIWA_CRUISE_ID}_[0-9]{{3,}}/",
#         rf"/{NIWA_CRUISE_ID}_STN_[0-9]{{3,}}_",
#         rf"/{NIWA_CRUISE_ID}_[0-9]{{3,}}_",
#         rf"/{NIWA_CRUISE_ID}_[0-9]{{3,}}.*_RERUN",
#         rf"/{NIWA_CRUISE_ID}/STN[0-9]{{3,}}/",
#         rf"/STN_[0-9]{{3,}}/",
#     ]
#     for pattern in patterns:
#         match = re.search(pattern, file_path_upper_case)
#         if match:
#             station_id = re.search(r"[0-9]{3,}", match.group()).group()
#             return station_id.strip()
#     print(f"Error: Could not get station ID for the file {file_path} (potential cruise ID mismatch)", file=sys.stderr)
#     return None

def get_station_id(file_path):
    # Make the file path fully upper case
    file_path_upper_case = file_path.upper()

    # Check if the file path matches the NIWA_CRUISE_ID
    if NIWA_CRUISE_ID not in file_path_upper_case:
        error_message = f"Error: File: {file_path} does not come from the cruise of ID: {NIWA_CRUISE_ID}"
        print(error_message)
        with open(error_file, 'a') as ef:
            ef.write(error_message + '\n')
        return ""

    # Method 1
    # e.g. Video/TAN0616/TAN0616_003/TAN0616_045.m2ts
    # this gives, e.g. /TAN0616_003/
    match = re.search(rf"/{NIWA_CRUISE_ID}_[0-9]{{3,}}/", file_path_upper_case)
    if match:
        station_id = match.group(0).split('_')[1].strip('/')
        return station_id

    # Method 2
    # e.g. images/dir with space/TAN1802_Stn_160_001.jpg
    # this gives, e.g. /TAN1802_Stn_160
    match = re.search(rf"/{NIWA_CRUISE_ID}_STN_[0-9]{{3,}}_", file_path_upper_case)
    if match:
        station_id = match.group(0).split('_')[2].strip()
        return station_id

    # Method 3
    # e.g. images/dir with space/TAN1802_160_DTIS__004.jpeg
    # this gives, e.g. /TAN1802_160_
    match = re.search(rf"/{NIWA_CRUISE_ID}_[0-9]{{3,}}_", file_path_upper_case)
    if match:
        station_id = match.group(0).split('_')[1].strip()
        return station_id

    # Method 4
    # e.g. text/TAN2203/OFOP text files/TAN2203_001.sth_rerun.sth_obser.txt
    # this gives, e.g. /TAN2203_001.sth_rerun
    match = re.search(rf"/{NIWA_CRUISE_ID}_[0-9]{{3,}}.*_RERUN", file_path_upper_case)
    if match:
        station_id = match.group(0).split('_')[1].split('.')[0].strip()
        return station_id

    # Method 5
    # e.g. TAN2203/Stn003/1234.m2t
    # this gives, e.g. /TAN1802/STN003/
    match = re.search(rf"/{NIWA_CRUISE_ID}/STN[0-9]{{3,}}/", file_path_upper_case)
    if match:
        station_id = re.search(r"[0-9]{3,}", match.group(0).split('/')[2]).group(0).strip()
        return station_id

    # Method 6
    # e.g. /Stn002/11-04-2022/20220411191258.m2ts
    # this gives, e.g. /STN002/11-04-2022/
    match = re.search(rf"/STN[0-9]{{3,}}/[0-9]{{2}}-[0-9]{{2}}-[0-9]{{4}}/.*\.M", file_path_upper_case)
    if match:
        station_id = re.search(r"[0-9]{3,}", match.group(0).split('/')[1]).group(0).strip()
        return station_id

    # Method 7
    # e.g. /STN_002/1234.m2t
    # this gives, e.g. /STN_002/
    match = re.search(r"/STN_[0-9]{3,}/", file_path_upper_case)
    if match:
        station_id = re.search(r"[0-9]{3,}", match.group(0).split('/')[1]).group(0).strip()
        return station_id

    error_message = f"Error: Could not get station id for the file: {file_path} (file path matches no pattern, potential cruise ID mismatch)"
    print(error_message)
    with open(error_file, 'a') as ef:
        ef.write(error_message + '\n')
    return ""

# # Function to upload files to S3
# def upload_to_s3(plan_file_to_read_from, bucket_name, cruise_id, dry_run=False):
#     if not os.path.isfile(plan_file_to_read_from):
#         raise FileNotFoundError(f"Plan file does not exist: {plan_file_to_read_from}")
    
#     with open(plan_file_to_read_from, 'r') as file:
#         plan_file_as_array = file.readlines()
    
#     file_type = ""
#     for line in plan_file_as_array:
#         line = line.strip()
#         if "The following image files passed local verification:" in line:
#             file_type = "images"
#         elif "The following text files passed local verification:" in line:
#             file_type = "text"
#         elif "The following video files passed local verification:" in line:
#             file_type = "video"
        
#         if "." not in line or ";" not in line:
#             continue
        
#         file_path, station_id = line.split(';')
#         file_basename = os.path.basename(file_path)
#         s3_destination = f"{cruise_id}/{station_id}/{file_type}/{file_basename}"

#         if dry_run:
#             print(f"Pretending to upload {file_path} to s3://{bucket_name}/{s3_destination}")
#         else:
#             try:
#                 # Check if the file exists on S3
#                 s3_client.head_object(Bucket=bucket_name, Key=s3_destination)
#                 print(f"S3 object exists already, not uploading: {s3_destination}")
#             except ClientError:
#                 # Upload if not exists
#                 s3_client.upload_file(file_path, bucket_name, s3_destination, ExtraArgs={'StorageClass': 'STANDARD_IA'})
#                 print(f"Uploaded {file_path} to s3://{bucket_name}/{s3_destination}")

# Function to verify image files
def check_image_files(dir, error_file, image_patterns):
    print(f"Checking {dir} for image files...")

    if dir == "ignore":
        print("Images directory was set to 'ignore', cancelling the check")
        return []

    if not os.path.isdir(dir):
        with open(error_file, 'a') as ef:
            ef.write(f"Error: Images directory: {dir} does not exist.\n")
        print(f"Error: Images directory: {dir} does not exist.")
        exit(1)

    # Find all the files in the images directory with the selected file extensions
    files_with_matching_extension = []
    for root, _, files in os.walk(dir):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg')):
                files_with_matching_extension.append(os.path.join(root, file))

    image_files_to_copy = []

    for file in tqdm(files_with_matching_extension, total=len(files_with_matching_extension)):
        file_no_trailing_whitespace = file.rstrip()

        file_name = os.path.basename(file)
        file_path_upper_case = file_name.upper()

        if not any(re.match(pattern, file_path_upper_case) for pattern in image_patterns):
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File does not match image naming convention: {file_no_trailing_whitespace}\n")
            print(f"Error: File does not match image naming convention: {file_no_trailing_whitespace}")
            continue

        file_type = subprocess.run(['file', '--mime-type', '-b', file_no_trailing_whitespace], 
                                   capture_output=True, text=True).stdout.strip()
        if file_type != "image/jpeg":
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File is not a valid JPEG: {file_no_trailing_whitespace} (Detected type: {file_type})\n")
            print(f"Error: File is not a valid JPEG: {file_no_trailing_whitespace} (Detected type: {file_type})")
        else:
            image_files_to_copy.append(file_no_trailing_whitespace)

    return image_files_to_copy

# Function to verify video files
def check_video_files(dir, error_file, video_patterns):
    print(f"Checking {dir} for video files...")

    if dir == "ignore":
        print("Videos directory was set to 'ignore', cancelling the check")
        return []

    if not os.path.isdir(dir):
        with open(error_file, 'a') as ef:
            ef.write(f"Error: Videos directory: {dir} does not exist.\n")
        print(f"Error: Videos directory: {dir} does not exist.")
        exit(1)

    # Find all the files in the videos directory with the selected file extensions
    files_with_matching_extension = []
    for root, _, files in os.walk(dir):
        for file in files:
            if file.lower().endswith(('.m2t', '.m2ts')):
                files_with_matching_extension.append(os.path.join(root, file))

    video_files_to_copy = []

    for file in tqdm(files_with_matching_extension, total=len(files_with_matching_extension)):
        file_no_trailing_whitespace = file.rstrip()

        file_name = os.path.basename(file)
        file_path_upper_case = file_name.upper()

        if not any(re.match(pattern, file_path_upper_case) for pattern in video_patterns):
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File does not match video naming convention: {file_no_trailing_whitespace}\n")
            print(f"Error: File does not match video naming convention: {file_no_trailing_whitespace}")
            continue

        if NIWA_DRY_RUN == "true":
            print("NIWA_DRY_RUN is set, so skipping video file type verification")
            video_files_to_copy.append(file_no_trailing_whitespace)
            continue

        file_type = subprocess.run(['file', '--mime-type', '-b', file_no_trailing_whitespace], 
                                   capture_output=True, text=True).stdout.strip()
        if file_type != "video/MP2T":
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File is not a valid .m2t or .m2ts file: {file_no_trailing_whitespace} (Detected type: {file_type})\n")
            print(f"Error: File is not a valid .m2t or .m2ts file: {file_no_trailing_whitespace} (Detected type: {file_type})")
        else:
            video_files_to_copy.append(file_no_trailing_whitespace)

    return video_files_to_copy

# Function to verify text files
def check_ofop_files(dir, error_file, ofop_patterns):
    print(f"Checking {dir} for text files...")

    # Find all the files in the directory with the selected file extensions
    files_with_matching_extension = []
    for root, _, files in os.walk(dir):
        for file in files:
            if file.lower().endswith(('.txt')):
                files_with_matching_extension.append(os.path.join(root, file))

    text_files_to_copy = []

    for file in tqdm(files_with_matching_extension, total=len(files_with_matching_extension)):
        file_no_trailing_whitespace = file.rstrip()

        file_name = os.path.basename(file)
        file_path_upper_case = file_name.upper()

        file_type = subprocess.run(['file', '--mime-type', '-b', file_no_trailing_whitespace], 
                                   capture_output=True, text=True).stdout.strip()
        if file_type != "text/plain":
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File is not a valid text file: {file_no_trailing_whitespace} (Detected type: {file_type})\n")
            print(f"Error: File is not a valid text file: {file_no_trailing_whitespace} (Detected type: {file_type})")
            continue

        if any(re.match(pattern, file_path_upper_case) for pattern in ofop_patterns):
            text_files_to_copy.append(file_no_trailing_whitespace)
        else:
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File does not match any pattern: {file_name}\n")
            print(f"Error: File does not match any pattern: {file_name}")

    return text_files_to_copy

# def enable_lambda_event_source_mapping():
#     print(f"{datetime.now()} Enabling Lambda event source mapping for the function: {lambda_function_name}...")
#     event_source_mappings = lambda_client.list_event_source_mappings(FunctionName=lambda_function_name)

#     for mapping in event_source_mappings['EventSourceMappings']:
#         if mapping['State'] == 'Enabled':
#             print(f"{datetime.now()} Lambda event source mapping is already enabled. Nothing to do.")
#             return

#         uuid = mapping['UUID']
#         lambda_client.update_event_source_mapping(UUID=uuid, Enabled=True)
#         print(f"{datetime.now()} Lambda event source mapping enabled successfully.")

def enable_lambda(lambda_function_name):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Enabling Lambda event source mapping for the function: {lambda_function_name}...")

    # Initialize boto3 client
    lambda_client = boto3.client('lambda')

    # Get event source mapping information
    event_source_mapping_info = lambda_client.list_event_source_mappings(FunctionName=lambda_function_name)

    # Check if the event source mapping is already enabled
    if any(mapping['State'] == 'Enabled' for mapping in event_source_mapping_info['EventSourceMappings']):
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping was already enabled. Nothing to do")
        with open(success_file, 'a') as sf:
            sf.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping was already enabled. Nothing to do\n")
    else:
        # Extract UUID
        uuid = next(mapping['UUID'] for mapping in event_source_mapping_info['EventSourceMappings'] if 'UUID' in mapping)

        # Update event source mapping to enable it
        try:
            lambda_client.update_event_source_mapping(UUID=uuid, Enabled=True)
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping enabled successfully")
            with open(success_file, 'a') as sf:
                sf.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping enabled successfully\n")
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Failed to enable Lambda event source mapping: {str(e)}")
            with open(error_file, 'a') as ef:
                ef.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Failed to enable Lambda event source mapping: {str(e)}\n")

def write_validated_file_paths(file_type, files_list):
    with open(plan_file, "a") as plan_f:
        plan_f.write(f"The following {file_type} files passed local verification:\n")
        plan_f.write("FILE_PATH;STATION_ID\n")
        for file in files_list:
            station_id = get_station_id(file)  # Replace with actual implementation
            if station_id:
                with open(success_file, 'a') as sf:
                    sf.write(f"Station ID for the file: {file} is: {station_id}\n")
                plan_f.write(f"{file};{station_id}\n")
        plan_f.write(f"End of {file_type} files that passed local verification\n\n")

def verify_s3_bucket():
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"S3 bucket {bucket_name} exists and is accessible.")
    except Exception as e:
        print(f"Error verifying S3 bucket {bucket_name}: {e}")
        raise

# def upload_to_s3(plan_file_path):
#     if not os.path.isfile(plan_file_path):
#         print(f"Error: Plan file does not exist: {plan_file_path}")
#         return

#     with open(plan_file_path, "r") as plan_file:
#         lines = plan_file.readlines()

#     file_type = None
#     for line in lines:
#         if "The following image files passed local verification:" in line:
#             file_type = "images"
#         elif "The following text files passed local verification:" in line:
#             file_type = "text"
#         elif "The following video files passed local verification:" in line:
#             file_type = "video"

#         if ";" in line:
#             file_path, station_id = line.strip().split(";")
#             file_basename = os.path.basename(file_path)
#             s3_destination = f"s3://{bucket_name}/{station_id}/{file_type}/{file_basename}"

#             if NIWA_DRY_RUN:
#                 print(f"Pretending to upload {file_path} to {s3_destination}")
#             else:
#                 try:
#                     s3_client.upload_file(file_path, bucket_name, f"{station_id}/{file_type}/{file_basename}")
#                     print(f"Successfully uploaded {file_path} to {s3_destination}")
#                 except Exception as e:
#                     print(f"Error uploading {file_path} to {s3_destination}: {e}")

def upload_to_s3(plan_file_to_read_from):
    # Check if the plan file exists
    if not os.path.isfile(plan_file_to_read_from):
        print(f"Error: Plan file does not exist: {plan_file_to_read_from}")
        sys.exit(1)
    if NIWA_DRY_RUN == "false":
        dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(sync_output_file, 'a') as syf:
            syf.write(f"Environment Name: {NIWA_ENVIRONMENT}\n")
            syf.write(f"S3 Bucket Name: {bucket_name}\n")
            syf.write(f"Region: {aws_region}\n")
            syf.write("----------------------------\n")
            syf.write(f"Upload started: {dt}\n")

    # Read the plan file into a list
    with open(plan_file_to_read_from, 'r') as file:
        plan_file_as_array = file.readlines()

    # Initialize variables
    file_type = ""

    # Initialize S3 client
    s3_client = boto3.client('s3')
    print(f"Writing files to S3...")
    for plan_file_line in tqdm(plan_file_as_array, total=len(plan_file_as_array)):
        if "The following image files passed local verification:" in plan_file_line:
            file_type = "images"
        elif "The following text files passed local verification:" in plan_file_line:
            file_type = "text"
        elif "The following video files passed local verification:" in plan_file_line:
            file_type = "video"

        if "." not in plan_file_line or ";" not in plan_file_line:
            # Ignore the lines with comments
            continue

        file_path, station_id = plan_file_line.split(';')
        file_basename = os.path.basename(file_path.strip())
        # print(f"try uploading file: {file_basename}")
        s3_destination = f"s3://{bucket_name}/{NIWA_CRUISE_ID}/{station_id.strip()}/{file_type}/{file_basename}"

        # Run the upload command and capture the output
        if NIWA_DRY_RUN == "true":
            upload_log = f"Pretending to be uploading {file_path.strip()} to {s3_destination}"
            with open(success_file, 'a') as sf:
                sf.write(upload_log + "\n")
        else:
            upload_log = f"Really uploading {file_path.strip()} to {s3_destination}"
            with open(success_file, 'a') as sf:
                sf.write(upload_log + "\n")
            try:
                # try list the object
                res = s3_client.head_object(Bucket=bucket_name, Key=f"{NIWA_CRUISE_ID}/{station_id.strip()}/{file_type}/{file_basename}")
            except Exception as e:
                res = None
                sync_output = f"{file_path.strip()} not found from S3 {s3_destination}: {e}"
                sync_output_exit_status = 1

            if res is None:
                try:
                    # try upload the file
                    sync_output = s3_client.upload_file(
                        file_path.strip(), 
                        bucket_name, 
                        f"{NIWA_CRUISE_ID}/{station_id.strip()}/{file_type}/{file_basename}",
                        ExtraArgs={'StorageClass': 'STANDARD_IA'}
                        )
                    if sync_output is None:
                        sync_output_exit_status = 0 
                        sync_output = f"Success uploading to S3: {file_path.strip()}"
                    else: 
                        sync_output_exit_status = 1
                except Exception as e:
                    sync_output = f"Error uploading {file_path.strip()} to {s3_destination}: {e}"
                    sync_output_exit_status = 1
            else:
                sync_output = f"{file_path.strip()} exists already in S3 {s3_destination}, not uploading"
                sync_output_exit_status = 0
            
            with open(sync_output_file, 'a') as syf:
                syf.write(sync_output + "\n")

            if sync_output_exit_status == 0:
                # Upload successful, write the output to the success file
                with open(success_file, 'a') as sf:
                    sf.write(sync_output + "\n")
            else:
                # Upload failed, write the output to the error file
                with open(error_file, 'a') as ef:
                    ef.write(f"Error uploading to S3: {file_path.strip()}\n")
    
    if NIWA_DRY_RUN == "false":
        dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(sync_output_file, 'a') as syf:
            syf.write("----------------------------\n")
            syf.write(f"Upload ended: {dt}\n")


if __name__ == "__main__":
    # Initialize log files
    dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if NIWA_DRY_RUN == "true":
        with open(success_file, "w") as sf, open(error_file, "w") as ef, open(sync_output_file, "w") as syf, open(plan_file, "w") as pf:
            sf.write(f"File Upload Success Report - {dt}\n")
            sf.write("----------------------------\n")
            ef.write(f"File Upload Error Report - {dt}\n")
            ef.write("----------------------------\n")
            syf.write(f"File Sync Report - {dt}\n")
            syf.write("----------------------------\n")
            pf.write(f"Data Upload Plan - {dt}\n")
            pf.write("----------------------------\n")

        # Check and validate local files
        image_files_to_copy = []  # Populate with validated image files
        video_files_to_copy = []  # Populate with validated video files
        text_files_to_copy = []  # Populate with validated text files
        image_files_to_copy = check_image_files(images_dir, error_file, patterns["image"])
        video_files_to_copy = check_video_files(videos_dir, error_file, patterns["video"])
        text_files_to_copy = check_ofop_files(ofop_dir, error_file, patterns["ofop"])

        write_validated_file_paths("image", image_files_to_copy)
        write_validated_file_paths("video", video_files_to_copy)
        write_validated_file_paths("text", text_files_to_copy)

    # Verify S3 bucket
    if NIWA_DRY_RUN == "false":
        verify_s3_bucket()
    
    # Upload to S3
    upload_to_s3(plan_file)

    if NIWA_DRY_RUN == "false":
        # Enable Lambda
        enable_lambda(lambda_function_name)
