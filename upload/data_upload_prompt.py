import os
import re
import sys
import boto3
from datetime import datetime
from tqdm import tqdm
import mimetypes
import subprocess
# import magic
# from botocore.exceptions import ClientError
import sys

def get_aws_credentials():
    # prompt for aws authentication
    print("Have You Set Up AWS Credentials In Your Environment Variables?")
    print("Or Set Up An AWS Profile With AWS Credentials?")
    auth_option = None
    while auth_option not in ["1", "2", "3"]:
        auth_option = input("Please Enter Your Authentication Options (1, 2, or 3):\n"+
                            "1 - by Environment Variables\n"+
                            "2 - by AWS profile\n"+
                            "3 - by Inputting AWS Credentials\n"+
                            "Enter Your Option: ")

    if auth_option == "1":
        # attempt to get environment variables for aws access key and secret
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_session_token = os.getenv("AWS_SESSION_TOKEN")
        if not aws_access_key_id or not aws_secret_access_key or not aws_session_token:
            print("AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY or AWS_SESSION_TOKEN was not set. Please set a correct value")
            sys.exit(1)
        return aws_access_key_id, aws_secret_access_key, aws_session_token
    
    if auth_option == "2":
        # attempt to get aws credentials from aws profile
        aws_profile = input("Enter your AWS profile name: ")
        if not aws_profile:
            print("AWS profile was not set. Please set a correct value")
            sys.exit(1)
        try:
            session = boto3.Session(profile_name=aws_profile)
            credentials = session.get_credentials()
            aws_access_key_id = credentials.access_key
            aws_secret_access_key = credentials.secret_key
            aws_session_token = credentials.token
            os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
            if aws_session_token is not None:
                os.environ["AWS_SESSION_TOKEN"] = aws_session_token
            return aws_access_key_id, aws_secret_access_key, aws_session_token
        except Exception as e:
            print(f"Failed to get AWS credentials from profile {aws_profile}", file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(1)
    
    if auth_option == "3":
        # prompt for aws access key
        aws_access_key_id = input("Enter your AWS Access Key ID: ")
        # attempt to get environment variables for aws access key and secret
        if not aws_access_key_id:
            print("AWS Access Key ID was not set. Please set a correct value")
            sys.exit(1)
        # prompt for aws secret access key
        aws_secret_access_key = input("Enter your AWS Secret Access Key: ")
        if not aws_secret_access_key:
            print("AWS Secret Access Key was not set. Please set a correct value")
            sys.exit(1)
        # prompt for aws session token
        aws_session_token = input("Enter your AWS Session Token: ")
        # if not aws_session_token:
        #     print("AWS Session Token was not set. Please set a correct value")
        #     sys.exit(1)
        os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
        os.environ["AWS_SESSION_TOKEN"] = aws_session_token
        return aws_access_key_id, aws_secret_access_key, aws_session_token

def get_data_upload_info():
    # prompt for data upload inputs
    cruise_id = None
    while not cruise_id:
        cruise_id = input("Enter cruise id: ")
    cruise_id = cruise_id.upper()
    # prompt for input directories
    images_dir = None
    videos_dir = None
    ofop_dir = None
    while (not images_dir) and (not videos_dir) and (not ofop_dir):
        images_dir = input("Enter image directory: ")
        videos_dir = input("Enter video directory: ")
        ofop_dir = input("Enter ofop directory: ")
        # Check input directories
        if (not images_dir) and (not videos_dir) and (not ofop_dir):
            print("At least one of the directories must be set for image/video/ofop. Please set it explicitly")
    # Setup environment configurations
    environment = None
    while environment not in ["testing", "production"]:
        environment = input("Enter ENVIRONMENT (testing or production): ")
        environment = environment.lower()
    # Set up Dry Run configuration
    dry_run = None
    while dry_run not in ["true", "false"]:
        dry_run = input("Enter DRY_RUN (true or false), setting it to false will directly upload files to S3: ")
        dry_run = dry_run.lower()

    return cruise_id, images_dir, videos_dir, ofop_dir, environment, dry_run

def get_data_upload_confirmation(cruise_id):
    # prompt for data upload confirmation
    confirmation = None
    print(f"Ready to upload for cruise id {cruise_id}?")
    while confirmation not in ["yes", "no"]:
        confirmation = input("Enter yes or no: ")
        confirmation = confirmation.lower()
    return confirmation

def get_file_type(file_path):
    # file type check for windows OS
    # Initialize the magic object
    # mine = magic.Magic()
    # file_type = mine.from_file(file_path)
    file_type, _ = mimetypes.guess_type(file_path)
    return file_type

# def get_station_id(file_path, cruise_id):
#     # Make the file path fully upper case
#     file_path_upper_case = file_path.upper()

#     # Check if the file path matches the NIWA_CRUISE_ID
#     if cruise_id not in file_path_upper_case:
#         error_message = f"Error: File: {file_path} does not come from the cruise of ID: {cruise_id}"
#         print(error_message)
#         with open(error_file, 'a') as ef:
#             ef.write(error_message + '\n')
#         return ""

#     # Method 1
#     # e.g. Video/TAN0616/TAN0616_003/TAN0616_045.m2ts
#     # this gives, e.g. /TAN0616_003/
#     match = re.search(rf"/{cruise_id}_[0-9]{{3,}}/", file_path_upper_case)
#     if match:
#         station_id = match.group(0).split('_')[1].strip('/')
#         return station_id

#     # Method 2
#     # e.g. images/dir with space/TAN1802_Stn_160_001.jpg
#     # this gives, e.g. /TAN1802_Stn_160
#     match = re.search(rf"/{cruise_id}_STN_[0-9]{{3,}}_", file_path_upper_case)
#     if match:
#         station_id = match.group(0).split('_')[2].strip()
#         return station_id

#     # Method 3
#     # e.g. images/dir with space/TAN1802_160_DTIS__004.jpeg
#     # this gives, e.g. /TAN1802_160_
#     match = re.search(rf"/{cruise_id}_[0-9]{{3,}}_", file_path_upper_case)
#     if match:
#         station_id = match.group(0).split('_')[1].strip()
#         return station_id

#     # Method 4
#     # e.g. text/TAN2203/OFOP text files/TAN2203_001.sth_rerun.sth_obser.txt
#     # this gives, e.g. /TAN2203_001.sth_rerun
#     match = re.search(rf"/{cruise_id}_[0-9]{{3,}}.*_RERUN", file_path_upper_case)
#     if match:
#         station_id = match.group(0).split('_')[1].split('.')[0].strip()
#         return station_id

#     # Method 5
#     # e.g. TAN2203/Stn003/1234.m2t
#     # this gives, e.g. /TAN1802/STN003/
#     match = re.search(rf"/{cruise_id}/STN[0-9]{{3,}}/", file_path_upper_case)
#     if match:
#         station_id = re.search(r"[0-9]{3,}", match.group(0).split('/')[2]).group(0).strip()
#         return station_id

#     # Method 6
#     # e.g. /Stn002/11-04-2022/20220411191258.m2ts
#     # this gives, e.g. /STN002/11-04-2022/
#     match = re.search(rf"/STN[0-9]{{3,}}/[0-9]{{2}}-[0-9]{{2}}-[0-9]{{4}}/.*\.M", file_path_upper_case)
#     if match:
#         station_id = re.search(r"[0-9]{3,}", match.group(0).split('/')[1]).group(0).strip()
#         return station_id

#     # Method 7
#     # e.g. /STN_002/1234.m2t
#     # this gives, e.g. /STN_002/
#     match = re.search(r"/STN_[0-9]{3,}/", file_path_upper_case)
#     if match:
#         station_id = re.search(r"[0-9]{3,}", match.group(0).split('/')[1]).group(0).strip()
#         return station_id

#     error_message = f"Error: Could not get station id for the file: {file_path} (file path matches no pattern, potential cruise ID mismatch)"
#     print(error_message)
#     with open(error_file, 'a') as ef:
#         ef.write(error_message + '\n')
#     return ""

def get_station_id(file_path, cruise_id, error_file):
    # Normalize the file path to use the correct separator for the OS
    file_path_normalized = os.path.normpath(file_path).upper()
    cruise_id_normalized = cruise_id.upper()

    # Check if the file path matches the cruise ID
    if cruise_id_normalized not in file_path_normalized:
        error_message = f"Error: File: {file_path} does not come from the cruise of ID: {cruise_id}"
        print(error_message)
        with open(error_file, 'a') as ef:
            ef.write(error_message + '\n')
        return ""
    
    # Method 1
    # e.g. Video/TAN0616/TAN0616_003/TAN0616_045.m2ts
    # this gives, e.g. /TAN0616_003/
    match = re.search(rf"{re.escape(cruise_id_normalized)}_[0-9]{{3,}}", file_path_normalized)
    if match:
        station_id = match.group(0).split('_')[1].strip()
        return station_id

    # Method 2
    # e.g. images/dir with space/TAN1802_Stn_160_001.jpg
    # this gives, e.g. /TAN1802_Stn_160
    match = re.search(rf"{re.escape(cruise_id_normalized)}_STN_[0-9]{{3,}}_", file_path_normalized)
    if match:
        station_id = match.group(0).split('_')[2].strip()
        return station_id

    # Method 3
    # e.g. images/dir with space/TAN1802_160_DTIS__004.jpeg
    # this gives, e.g. /TAN1802_160_
    match = re.search(rf"{re.escape(cruise_id_normalized)}_[0-9]{{3,}}_", file_path_normalized)
    if match:
        station_id = match.group(0).split('_')[1].strip()
        return station_id

    # # Method 4
    # match = re.search(rf"{re.escape(cruise_id_normalized)}_[0-9]{{3,}}.*_RERUN", file_path_normalized)
    # if match:
    #     station_id = match.group(0).split('_')[1].split('.')[0].strip()
    #     return station_id

    # Method 5
    # e.g. TAN2203/Stn003/1234.m2t
    # this gives, e.g. /TAN1802/STN003/
    match = re.search(rf"{re.escape(cruise_id_normalized)}[\\/]STN[0-9]{{3,}}[\\/]", file_path_normalized)
    if match:
        station_id = match.group(0).split(os.sep)[1].split("STN")[-1].strip()
        return station_id

    # Method 6
    # e.g. /Stn002/11-04-2022/20220411191258.m2ts
    # this gives, e.g. /STN002/11-04-2022/
    match = re.search(rf"STN[0-9]{{3,}}[\\/]", file_path_normalized)
    if match:
        station_id = match.group(0).split(os.sep)[0].split("STN")[-1].strip()
        return station_id

    # Method 7
    # e.g. /STN_002/1234.m2t
    # this gives, e.g. /STN_002/
    match = re.search(rf"STN_[0-9]{{3,}}[\\/]", file_path_normalized)
    if match:
        station_id = match.group(0).split(os.sep)[0].split("_")[-1].strip()
        return station_id

    error_message = f"Error: Could not get station id for the file: {file_path} (file path matches no pattern, potential cruise ID mismatch)"
    print(error_message)
    with open(error_file, 'a') as ef:
        ef.write(error_message + '\n')
    return ""

# Function to verify image files
def check_image_files(dir, error_file, image_patterns):
    print(f"Checking {dir} for image files...")

    if not dir or dir == "ignore":
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

        # file_type = subprocess.run(['file', '--mime-type', '-b', file_no_trailing_whitespace], 
        #                            capture_output=True, text=True, shell=True).stdout.strip()
        file_type = get_file_type(file_no_trailing_whitespace)
        if file_type != "image/jpeg":
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File is not a valid JPEG: {file_no_trailing_whitespace} (Detected type: {file_type})\n")
            print(f"Error: File is not a valid JPEG: {file_no_trailing_whitespace} (Detected type: {file_type})")
        else:
            image_files_to_copy.append(file_no_trailing_whitespace)

    return image_files_to_copy

# Function to verify video files
def check_video_files(dir, error_file, video_patterns, dry_run):
    print(f"Checking {dir} for video files...")

    if not dir or dir == "ignore":
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

        if dry_run == "true":
            print("DRY_RUN is set, so skipping video file type verification")
            video_files_to_copy.append(file_no_trailing_whitespace)
            continue

        # file_type = subprocess.run(['file', '--mime-type', '-b', file_no_trailing_whitespace], 
        #                            capture_output=True, text=True, shell=True).stdout.strip()
        file_type = get_file_type(file_no_trailing_whitespace)
        if file_type not in ["video/MP2T", "application/octet-stream"]:
            with open(error_file, 'a') as ef:
                ef.write(f"Error: File is not a valid .m2t or .m2ts file: {file_no_trailing_whitespace} (Detected type: {file_type})\n")
            print(f"Error: File is not a valid .m2t or .m2ts file: {file_no_trailing_whitespace} (Detected type: {file_type})")
        else:
            video_files_to_copy.append(file_no_trailing_whitespace)

    return video_files_to_copy

# Function to verify text files
def check_ofop_files(dir, error_file, ofop_patterns):
    print(f"Checking {dir} for text files...")
    if not dir or dir == "ignore":
        print("OFOP directory was set to 'ignore', cancelling the check")
        return []

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
        print(file_no_trailing_whitespace)

        # file_type = subprocess.run(['file', '--mime-type', '-b', file_no_trailing_whitespace], 
        #                            capture_output=True, text=True, shell=True).stdout.strip()
        file_type = get_file_type(file_no_trailing_whitespace)
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

def enable_lambda(lambda_client, lambda_function_name, success_file, error_file):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Enabling Lambda event source mapping for the function: {lambda_function_name}...")

    # # Initialize boto3 client
    # lambda_client = boto3.client('lambda')

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

def write_validated_file_paths(file_type, files_list, cruise_id, plan_file, success_file, error_file):
    passed_file_count = 0
    with open(plan_file, "a") as plan_f:
        plan_f.write(f"The following {file_type} files passed local verification:\n")
        plan_f.write("FILE_PATH;STATION_ID\n")
        for file in files_list:
            station_id = get_station_id(file, cruise_id, error_file)  # Replace with actual implementation
            if station_id:
                passed_file_count+=1
                with open(success_file, 'a') as sf:
                    sf.write(f"Station ID for the file: {file} is: {station_id}\n")
                plan_f.write(f"{file};{station_id}\n")
        plan_f.write(f"End of {file_type} files that passed local verification\n\n")
    print(f"{passed_file_count} {file_type} files passed location verification")
    return passed_file_count

def verify_s3_bucket(s3_client, bucket_name):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"S3 bucket {bucket_name} exists and is accessible.")
    except Exception as e:
        print(f"Error verifying S3 bucket {bucket_name}: {e}")
        raise

def upload_to_s3(
        plan_file_to_read_from, 
        environment, 
        dry_run, 
        cruise_id, 
        s3_client,
        bucket_name,
        aws_region,
        sync_output_file,
        success_file,
        error_file
        ):
    # Check if the plan file exists
    if not os.path.isfile(plan_file_to_read_from):
        print(f"Error: Plan file does not exist: {plan_file_to_read_from}")
        sys.exit(1)
    if dry_run == "false":
        dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(sync_output_file, 'a') as syf:
            syf.write(f"Environment Name: {environment}\n")
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
    # s3_client = boto3.client('s3')
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
        s3_destination = f"s3://{bucket_name}/{cruise_id}/{station_id.strip()}/{file_type}/{file_basename}"

        # Run the upload command and capture the output
        if dry_run == "true":
            upload_log = f"Pretending to be uploading {file_path.strip()} to {s3_destination}"
            with open(success_file, 'a') as sf:
                sf.write(upload_log + "\n")
        else:
            upload_log = f"Really uploading {file_path.strip()} to {s3_destination}"
            with open(success_file, 'a') as sf:
                sf.write(upload_log + "\n")
            try:
                # try list the object
                res = s3_client.head_object(Bucket=bucket_name, Key=f"{cruise_id}/{station_id.strip()}/{file_type}/{file_basename}")
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
                        f"{cruise_id}/{station_id.strip()}/{file_type}/{file_basename}",
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
    
    if dry_run == "false":
        dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(sync_output_file, 'a') as syf:
            syf.write("----------------------------\n")
            syf.write(f"Upload ended: {dt}\n")


if __name__ == "__main__":
    # initialize bucket name, lambda function name, s3 client and aws region
    bucket_name = "dtis-ofop-851725470721-raw-testing"
    lambda_function_name = "dtis-ofop-testing"
    s3_client = None
    aws_region = "ap-southeast-2"

    # Initialize log files
    success_file = "success.txt"
    error_file = "error.txt"
    sync_output_file = "sync_logs.txt"
    plan_file = "plan.txt"

    # Initialize log patterns
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

    # get upload info
    cruise_id, images_dir, videos_dir, ofop_dir, environment, dry_run = get_data_upload_info()

    if dry_run == "false":
        # get aws access key and secret key
        aws_access_key_id, aws_secret_access_key, aws_session_token = get_aws_credentials()

        # Initialize AWS Clients
        if aws_session_token:
            session = boto3.Session(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
                region_name=aws_region
            )
        else:
            session = boto3.Session(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=aws_region
            )
        sts_client = session.client('sts')
        lambda_client = session.client('lambda')
        s3_client = session.client('s3')
        print("Successfully Authenticated IAM User: ", sts_client.get_caller_identity())
    
        # set bucket_name and lambda_function_name according to environment
        bucket_name = f"dtis-ofop-{sts_client.get_caller_identity()['Account']}-raw-{environment}"
        lambda_function_name = f"dtis-ofop-{environment}"

    # Start the program here:
    dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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
    image_files_to_copy = check_image_files(
        dir=images_dir, 
        error_file=error_file, 
        image_patterns=patterns["image"]
        )
    video_files_to_copy = check_video_files(
        dir=videos_dir, 
        error_file=error_file, 
        video_patterns=patterns["video"],
        dry_run=dry_run
        )
    text_files_to_copy = check_ofop_files(
        dir=ofop_dir, 
        error_file=error_file, 
        ofop_patterns=patterns["ofop"]
        )

    passed_image_file_count = write_validated_file_paths(
        file_type="image", 
        files_list=image_files_to_copy, 
        cruise_id=cruise_id, 
        plan_file=plan_file, 
        success_file=success_file,
        error_file=error_file
        )
    passed_video_file_count = write_validated_file_paths(
        file_type="video", 
        files_list=video_files_to_copy, 
        cruise_id=cruise_id, 
        plan_file=plan_file, 
        success_file=success_file,
        error_file=error_file
        )
    passed_text_file_count = write_validated_file_paths(
        file_type="text", 
        files_list=text_files_to_copy, 
        cruise_id=cruise_id, 
        plan_file=plan_file, 
        success_file=success_file,
        error_file=error_file
        )
    total_passed_file_counts = passed_image_file_count+passed_video_file_count+passed_text_file_count
    print(f"{total_passed_file_counts} files in total passed location verification for S3 upload")
    print(f"Please check plan.txt file contents for the files ready to be uploaded to S3...")
    
    # Verify S3 bucket
    if dry_run == "false":
        verify_s3_bucket(
            s3_client=s3_client,
            bucket_name=bucket_name
            )
    
    # Upload to S3
    upload_to_s3(
        plan_file_to_read_from=plan_file, 
        environment=environment, 
        dry_run=dry_run, 
        cruise_id=cruise_id, 
        s3_client=s3_client,
        bucket_name=bucket_name,
        aws_region=aws_region,
        sync_output_file=sync_output_file,
        success_file=success_file,
        error_file=error_file
    )

    if dry_run == "false":
        # Enable Lambda
        enable_lambda(
            lambda_client=lambda_client, 
            lambda_function_name=lambda_function_name, 
            success_file=success_file, 
            error_file=error_file
        )

    if dry_run == "true":
        # prompt for data upload
        confirmation = get_data_upload_confirmation(cruise_id)
        if confirmation == "yes":
            # get aws access key and secret key
            aws_access_key_id, aws_secret_access_key, aws_session_token = get_aws_credentials()

            # Initialize AWS Clients
            if aws_session_token:
                session = boto3.Session(
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    aws_session_token=aws_session_token,
                    region_name=aws_region
                )
            else:
                session = boto3.Session(
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    region_name=aws_region
                )
            sts_client = session.client('sts')
            lambda_client = session.client('lambda')
            s3_client = session.client('s3')
            print("Successfully Authenticated IAM User: ", sts_client.get_caller_identity())
        
            # set bucket_name and lambda_function_name according to environment
            bucket_name = f"dtis-ofop-{sts_client.get_caller_identity()['Account']}-raw-{environment}"
            lambda_function_name = f"dtis-ofop-{environment}"
            
            # Verify S3 bucket
            verify_s3_bucket(
                s3_client=s3_client,
                bucket_name=bucket_name
                )
            # Upload to S3
            upload_to_s3(
                plan_file_to_read_from=plan_file, 
                environment=environment, 
                dry_run="false", 
                cruise_id=cruise_id, 
                s3_client=s3_client,
                bucket_name=bucket_name,
                aws_region=aws_region,
                sync_output_file=sync_output_file,
                success_file=success_file,
                error_file=error_file
            )
            # Enable Lambda
            enable_lambda(
                lambda_client=lambda_client, 
                lambda_function_name=lambda_function_name, 
                success_file=success_file, 
                error_file=error_file
            )
        else:
            sys.exit("Dry run completed, exiting...")
            

