import os
import re
import sys
import argparse
import yaml
import mimetypes
import logging
import logging.config
from pathlib import Path
import boto3
from botocore.config import Config
from datetime import datetime
from tqdm import tqdm
from typing import Optional, Dict, Any

from aws_credential_provider import AWSCredentialProvider
from aws_bucket_manager import AWSBucketManager

# import magic
# from botocore.exceptions import ClientError


# initialize bucket name, lambda function name, s3 client, s3 config and aws region
bucket_name = "dtis-ofop-851725470721-raw-testing"
lambda_function_name = "dtis-ofop-testing"
s3_client = None
aws_region = "ap-southeast-2"
s3_config = Config(
    region_name=aws_region,
    s3={
        "max_concurrent_requests": 20,
        "max_queue_size": 10000,
        "multipart_threshold": 64 * 1024 * 1024,  # 64 MB in bytes
        "multipart_chunksize": 16 * 1024 * 1024,  # 16 MB in bytes
        "max_bandwidth": 200 * 1024 * 1024,  # 200 MB/s in bytes per second
        "use_accelerate_endpoint": False,
        "addressing_style": "virtual",
    },
)

# Initialize log files
success_file = "success.txt"
error_file = "error.txt"
sync_output_file = "sync_logs.txt"
plan_file = "plan.txt"

# Initialize log patterns
patterns = {
    "images": [
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.JPEG$",  # e.g. TAN1802_160_DTIS__004.jpeg
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.JPG$",  # e.g. TAN1802_160_DTIS__004.jpg
        r"^[A-Z]{3}[0-9]{4}_STN_[0-9]{3,}_[0-9]{3}\.JPEG$",  # e.g. TAN1802_Stn_160_004.jpeg
        r"^[A-Z]{3}[0-9]{4}_STN_[0-9]{3,}_[0-9]{3}\.JPG$",  # e.g. TAN1802_Stn_160_004.jpg
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_[0-9]{3}\.JPEG$",  # e.g. TAN1802_160_004.jpeg
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3,}_[0-9]{3}\.JPG$",  # e.g. TAN1802_160_004.jpg
    ],
    "videos": [],
    # "video": [
    #     r"^[A-Z]{3}[0-9]{4}_[0-9]{3}\.(M2T[S]?|MPG)$", # e.g. TAN1802_001.m2t, TAN1802_001.m2ts, or TAN1802_001.mpg
    #     r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_[0-9]{1}\.(M2T[S]?|MPG)$", # e.g. TAN1802_001_1.m2t, TAN1802_001_2.m2ts, or TAN1802_001_1.mpg
    #     r"^[0-9]{4,}\.(M2T[S]?|MPG)$", # e.g. 201012220153001.m2t, 201012220153001.m2ts, or 201012220153001.mpg (only digits)
    # ],
    "ofop": [
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_POSI\.TXT$",  # e.g. TAN1802_001_posi.txt
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_PROT\.TXT$",  # e.g. TAN1802_001_prot.txt
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}_OBSER\.TXT$",  # e.g. TAN1802_001_obser.txt
    ],
    "ofop_rerun": [
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_OBSER.*\.TXT$",  # e.g. TAN1802_001.sth_obser.txt
        r"^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_PROT.*\.TXT$",  # e.g. TAN1802_001.sth_prot.txt
    ],
}

data_types_list = ["ofop", "ofop_rerun", "images", "videos"]


class Configs:
    def __init__(self, config_path: Optional[str] = None):
        self.if_validate_data: bool = True
        self.cruises: Optional[Any] = None
        self.file_suffix: Optional[str] = None
        self.patterns: Optional[Dict[str, Any]] = None
        self.config_path = config_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "conf/config.yml"
        )

    def read_config_file(self) -> None:
        try:
            with open(self.config_path, "r") as file:
                config = yaml.safe_load(file) or {}
                self.if_validate_data = config.get("if_validate_data", True)
                self.cruises = config.get("cruises")
                self.file_suffix = config.get("file_suffix")
                self.patterns = config.get("patterns")
        except Exception as e:
            logging.error(f"Error reading config file: {e}")
            sys.exit(1)


def get_aws_credentials():
    # prompt for aws authentication
    print("Have You Set Up AWS Credentials In Your Environment Variables?")
    print("Or Set Up An AWS Profile With AWS Credentials?")
    auth_option = None
    while auth_option not in ["1", "2", "3"]:
        auth_option = input(
            "Please Enter Your Authentication Options (1, 2, or 3):\n"
            + "1 - by Environment Variables\n"
            + "2 - by AWS profile\n"
            + "3 - by Inputting AWS Credentials\n"
            + "Enter Your Option: "
        )

    if auth_option == "1":
        # attempt to get environment variables for aws access key and secret
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_session_token = os.getenv("AWS_SESSION_TOKEN")
        if not aws_access_key_id or not aws_secret_access_key or not aws_session_token:
            print(
                "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY or AWS_SESSION_TOKEN was not set. Please set a correct value"
            )
            # sys.exit(1)
        return aws_access_key_id, aws_secret_access_key, aws_session_token

    if auth_option == "2":
        # attempt to get aws credentials from aws profile
        aws_profile = input("Enter your AWS profile name: ")
        if not aws_profile:
            print("AWS profile was not set. Please set a correct value")
            # sys.exit(1)
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
            print(
                f"Failed to get AWS credentials from profile {aws_profile}",
                file=sys.stderr,
            )
            print(e, file=sys.stderr)
            # sys.exit(1)

    if auth_option == "3":
        # prompt for aws access key
        aws_access_key_id = input("Enter your AWS Access Key ID: ")
        # attempt to get environment variables for aws access key and secret
        if not aws_access_key_id:
            print("AWS Access Key ID was not set. Please set a correct value")
            # sys.exit(1)
        # prompt for aws secret access key
        aws_secret_access_key = input("Enter your AWS Secret Access Key: ")
        if not aws_secret_access_key:
            print("AWS Secret Access Key was not set. Please set a correct value")
            # sys.exit(1)
        # prompt for aws session token
        aws_session_token = input("Enter your AWS Session Token: ")
        # if not aws_session_token:
        #     print("AWS Session Token was not set. Please set a correct value")
        #     sys.exit(1)
        os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
        os.environ["AWS_SESSION_TOKEN"] = aws_session_token
        return aws_access_key_id, aws_secret_access_key, aws_session_token


def get_dirs(cruise_id, data_types, cruises):
    dirs_dict = {i_data_type: None for i_data_type in data_types}
    if cruises is None:
        logging.warning(
            "config.yml file not found in the current directory, or no cruises information found in the file."
        )
        for i_data_type in data_types:
            dirs_dict[i_data_type] = get_dirs_from_interactive_input(i_data_type)
        return dirs_dict

    # check if cruise_id exists in config
    if cruise_id not in cruises:
        logging.warning(
            f"Cruise ID {cruise_id} not found in config file(config.yml)."
        )
        for i_data_type in data_types:
            dirs_dict[i_data_type] = get_dirs_from_interactive_input(i_data_type)
        return dirs_dict
    else:
        # get dirs from the config file
        dirs = cruises[cruise_id]
        for i_data_type in data_types:
            dirs_dict[i_data_type] = dirs.get(f"{i_data_type}_dir", None)
            if dirs_dict[i_data_type] is not None:
                logging.info(f"  {i_data_type}_dir: '{dirs_dict[i_data_type]}'")
            else:
                dirs_dict[i_data_type] = get_dirs_from_interactive_input(
                    i_data_type
                )
    return dirs_dict


def get_data_upload_info_from_args(cruises):
    p = argparse.ArgumentParser(
        description="""
    Upload DTIS data to AWS S3 bucket.
    Example usage:
    python data_upload_prompt.py TAN0906
    python data_upload_prompt.py TAN0906 --data_types images videos ofop --environment dev --dry_run
    """,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("cruise_id", type=str, help="Cruise ID")
    p.add_argument(
        "--data_types",
        nargs="+",
        choices=data_types_list,
        default=data_types_list,
        help="List of data types to upload",
    )
    p.add_argument(
        "--environment",
        type=str,
        choices=["dev", "test", "prod", "development", "testing", "production"],
        default="dev",
        help="Environment type",
    )
    p.add_argument(
        "--dry_run",
        action="store_true",
        help="Dry run",
    )
    args = p.parse_args()

    args.cruise_id = args.cruise_id.upper()
    logging.info(f"Uploading Cruise ID: {args.cruise_id}")
    source_dirs_dict = get_dirs(args.cruise_id, args.data_types, cruises)

    for i_key, i_value in source_dirs_dict.items():
        if i_value is not None:
            break
        logging.error(
            "At least one of the directories must be set for image/video/ofop/rerun. Please set it explicitly"
        )
        exit(1)
    args.environment = args.environment.lower()
    return (
        args.cruise_id,
        source_dirs_dict,
        args.environment,
        args.dry_run,
    )


def get_dirs_from_interactive_input(data_type):
    input_str = input(f"Enter {data_type} directory (press enter to skip): ").strip()
    if input_str == "":
        return None
    else:
        return re.sub(r"[\"']", "", input_str)


def get_data_upload_confirmation(cruise_id):
    # prompt for data upload confirmation
    confirmation = None
    print(f"Ready to upload for cruise id {cruise_id}?")
    while confirmation not in ["yes", "no"]:
        confirmation = input("Enter yes or no: ")
        confirmation = confirmation.lower()
    return confirmation


def get_exit_confirmation():
    # prompt for exit confirmation
    confirmation = None
    print(f"Exit the program now?")
    while confirmation not in ["yes", "no"]:
        confirmation = input("Enter yes or no: ")
        confirmation = confirmation.lower()
    return confirmation


def get_file_type(file_path):
    # file type check for windows OS
    return mimetypes.guess_type(file_path)[0]


def get_station_id(data_type, file_path, cruise_id):
    # Normalize the file path to use the correct separator for the OS
    file_path_normalized = file_path.resolve().name.upper()
    cruise_id_normalized = cruise_id.upper()

    # Check if the file path matches the cruise ID
    if cruise_id_normalized not in file_path_normalized:
        logging.error(f"File: {file_path} does not come from the cruise of ID: {cruise_id}")
        return None

    if data_type == "images":
        # e.g. TAN1802_160_DTIS__004.jpeg
        # e.g. TAN1802_160_DTIS__004.jpg
        # e.g. TAN1802_Stn_160_004.jpeg
        # e.g. TAN1802_Stn_160_004.jpg
        # e.g. TAN1802_160_004.jpeg
        # e.g. TAN1802_160_004.jpg
        # this gives, e.g. '160'
        patterns = [r"[A-Z]{3}[0-9]{4}_(?:Stn_)?(?P<station_id>[0-9]{3,})_"]
    if data_type == "videos":
        # e.g. Video/TAN0616/TAN0616_003/TAN0616_045.m2ts, this gives 003
        # e.g. TAN2203/Stn003/1234.m2t, this gives 003
        # e.g. /Stn002/11-04-2022/20220411191258.m2ts, this gives 002
        # e.g. /STN_002/1234.m2t, this gives 002
        # e.g. tan0906_059\tan0906_059 - Clip 001.avi, this gives 059
        patterns = [
            r"STN_(?P<station_id>[0-9]{3,})[\\/]",
            r"tan[0-9]{4}_(?P<station_id>[0-9]{3,})",
        ]
    elif data_type == "ofop":
        # e.g. TAN1802_001_posi.txt
        # e.g.TAN1802_001_prot.txt
        # e.g. TAN1802_001_obser.txt
        # this gives, e.g. '001'
        patterns = [r"[A-Z]{3}[0-9]{4}_(?P<station_id>[0-9]{3,})_"]
    elif data_type == "ofop_rerun":
        # e.g. TAN1802_001.sth_obser.txt
        # e.g. TAN1802_001.sth_prot.txt
        patterns = [r"[A-Z]{3}[0-9]{4}_(?P<station_id>[0-9]{3,})."]

    # Try each pattern
    for pattern in patterns:
        match = re.search(pattern, file_path_normalized, re.IGNORECASE)
        if match:
            station_id = match.group("station_id").strip()
            logging.info(
                f"Extracted station ID: {file_path} -> {station_id}"
            )
            return station_id
    # If no match found, log an error and return None
    logging.error(f"Could not extract station ID from file path: {file_path}")

    error_message = f"Error: Could not get station id for the file: {file_path} (file path matches no pattern, potential cruise ID mismatch)"
    print(error_message)
    with open(error_file, "a") as ef:
        ef.write(error_message + "\n")
    return None


# Function to verify files
def check_files(data_type, dir, image_patterns, file_suffix_list):
    logging.info(f"Checking '{dir}' for {data_type} ...")

    if not dir.exists():
        logging.error(f"{data_type} directory: {dir} does not exist.")
        return []

    # Find all the files in the images directory with the selected file extensions
    filenames = [f for f in dir.rglob("*") if f.suffix.lower() in file_suffix_list]

    if data_type == "videos":
        # For videos, we don't need to check the filename patterns
        return filenames

    files_to_copy = []
    for file in tqdm(
        filenames, total=len(filenames)
    ):
        if any(
            re.match(pattern, file.name.upper())
            for pattern in image_patterns
        ):
            # # needed?
            # file_type = get_file_type(file) #? Needed?
            # if file_type != "image/jpeg":
            #     logging.error(f"File is not a valid JPEG: '{file}' (Detected type: {file_type})")
            #     continue
            # else:
            #     files_to_copy.append(file)
            files_to_copy.append(file)
        else:
            logging.error(
                f"File does not match '{data_type}' naming convention: '{file}'"
            )
            continue
    return files_to_copy


def enable_lambda(lambda_client, lambda_function_name, success_file, error_file):
    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Enabling Lambda event source mapping for the function: {lambda_function_name}..."
    )

    # # Initialize boto3 client
    # lambda_client = boto3.client('lambda')

    # Get event source mapping information
    event_source_mapping_info = lambda_client.list_event_source_mappings(
        FunctionName=lambda_function_name
    )

    # Check if the event source mapping is already enabled
    if any(
        mapping["State"] == "Enabled"
        for mapping in event_source_mapping_info["EventSourceMappings"]
    ):
        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping was already enabled. Nothing to do"
        )
        with open(success_file, "a") as sf:
            sf.write(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping was already enabled. Nothing to do\n"
            )
    else:
        # Extract UUID
        uuid = next(
            mapping["UUID"]
            for mapping in event_source_mapping_info["EventSourceMappings"]
            if "UUID" in mapping
        )

        # Update event source mapping to enable it
        try:
            lambda_client.update_event_source_mapping(UUID=uuid, Enabled=True)
            print(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping enabled successfully"
            )
            with open(success_file, "a") as sf:
                sf.write(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Lambda event source mapping enabled successfully\n"
                )
        except Exception as e:
            print(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Failed to enable Lambda event source mapping: {str(e)}"
            )
            with open(error_file, "a") as ef:
                ef.write(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Failed to enable Lambda event source mapping: {str(e)}\n"
                )


def write_validated_file_paths(data_type, files_list, cruise_id, plan_file):
    logging.info(f"local verification for {data_type} files")
    passed_file_count = 0
    with open(plan_file, "a") as plan_f, open(success_file, "a") as sf:
        plan_f.write(f"The following {data_type} files passed local verification:\n")
        plan_f.write("FILE_PATH;STATION_ID\n")
        for file in files_list:
            station_id = get_station_id(data_type,
                file, cruise_id
            )  # Replace with actual implementation
            if station_id:
                passed_file_count += 1
                # with open(success_file, 'a') as sf:
                sf.write(f"Station ID for the file: '{file}' is: {station_id}\n")
                plan_f.write(f"'{file}';{station_id}\n")
        plan_f.write(f"End of {data_type} files that passed local verification\n\n")
    logging.info(f"{passed_file_count} {data_type} files passed location verification")
    return passed_file_count


def upload_to_s3(
    plan_file_to_read_from=None,
    environment=None,
    dry_run=None,
    cruise_id=None,
    s3_client=None,
    bucket_name=None,
    aws_region=None,
    sync_output_file=None,
):
    # Check if the plan file exists
    if not os.path.isfile(plan_file_to_read_from):
        logging.error(f"Plan file does not exist: {plan_file_to_read_from}")
        sys.exit(1)
    else:
        # Read the plan file into a list
        with open(plan_file_to_read_from, "r") as file:
            plan_file_as_array = file.readlines()

    if not dry_run:
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(sync_output_file, "a") as syf:
            syf.write(f"Environment Name: {environment}\n")
            syf.write(f"S3 Bucket Name: {bucket_name}\n")
            syf.write(f"Region: {aws_region}\n")
            syf.write("----------------------------\n")
            syf.write(f"Upload started: {dt}\n")

    # Initialize variables
    file_type = ""

    # Initialize S3 client
    # s3_client = boto3.client('s3')
    print(f"Writing files to S3...")
    for plan_file_line in tqdm(plan_file_as_array, total=len(plan_file_as_array)):
        if "The following image files passed local verification:" in plan_file_line:
            file_type = "images"
        elif "The following ofop files passed local verification:" in plan_file_line:
            file_type = "text"
        elif (
            "The following ofop_rerun files passed local verification:"
            in plan_file_line
        ):
            file_type = "text"
        elif "The following video files passed local verification:" in plan_file_line:
            file_type = "video"

        if "." not in plan_file_line or ";" not in plan_file_line:
            # Ignore the lines with comments
            continue

        file_path, station_id = plan_file_line.split(";")
        file_basename = os.path.basename(file_path.strip())
        # print(f"try uploading file: {file_basename}")
        s3_destination = f"s3://{bucket_name}/{cruise_id}/{station_id.strip()}/{file_type}/{file_basename}"

        # Run the upload command and capture the output
        if dry_run == "true":
            logging.info(f"Pretending to be uploading {file_path.strip()} to {s3_destination}")
        else:
            logging.info(f"Really uploading {file_path.strip()} to {s3_destination}")
            try:
                # try list the object
                res = s3_client.head_object(
                    Bucket=bucket_name,
                    Key=f"{cruise_id}/{station_id.strip()}/{file_type}/{file_basename}",
                )
            except Exception as e:
                res = None
                sync_output = (
                    f"{file_path.strip()} not found from S3 {s3_destination}: {e}"
                )
                sync_output_exit_status = 1

            if res is None:
                try:
                    # try upload the file
                    sync_output = s3_client.upload_file(
                        file_path.strip(),
                        bucket_name,
                        f"{cruise_id}/{station_id.strip()}/{file_type}/{file_basename}",
                        ExtraArgs={"StorageClass": "STANDARD_IA"},
                    )
                    if sync_output is None:
                        sync_output_exit_status = 0
                        sync_output = f"Success uploading to S3: {file_path.strip()}"
                    else:
                        sync_output_exit_status = 1
                except Exception as e:
                    sync_output = (
                        f"Error uploading {file_path.strip()} to {s3_destination}: {e}"
                    )
                    sync_output_exit_status = 1
            else:
                sync_output = f"{file_path.strip()} exists already in S3 {s3_destination}, not uploading"
                sync_output_exit_status = 0

            with open(sync_output_file, "a") as syf:
                syf.write(sync_output + "\n")

            if sync_output_exit_status == 0:
                # Upload successful, write the output to the success file
                with open(success_file, "a") as sf:
                    sf.write(sync_output + "\n")
            else:
                # Upload failed, write the output to the error file
                with open(error_file, "a") as ef:
                    ef.write(f"Error uploading to S3: {file_path.strip()}\n")

    if dry_run == "false":
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(sync_output_file, "a") as syf:
            syf.write("----------------------------\n")
            syf.write(f"Upload ended: {dt}\n")


def set_up_log():
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    yml_file_path = os.path.join(current_file_dir, "conf/logging.yml")
    with open(yml_file_path, "r") as stream:
        config = yaml.safe_load(stream)
        logging.config.dictConfig(config)
        logger = logging.getLogger(__name__)


def validate_local_files(source_dirs_dict, patterns, file_suffix,):

    files_to_copy_dict = {}
    for i_data_type in source_dirs_dict.keys():
        files_to_copy_dict[i_data_type] = None
        if source_dirs_dict[i_data_type] is None:
            logging.warning(
                f"{i_data_type} directory was not set, skipping the check"
            )
            continue
        files_to_copy_dict[i_data_type] = check_files(
            i_data_type,
            dir=Path(source_dirs_dict[i_data_type]),
            image_patterns=patterns[i_data_type],
            file_suffix_list=file_suffix[i_data_type],
        )
        logging.info(
            f"Found {len(files_to_copy_dict[i_data_type])} available {i_data_type} files"
        )

    # Start the program here:
    dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(sync_output_file, "w") as syf, open(plan_file, "w") as pf:
        syf.write(f"File Sync Report - {dt}\n")
        syf.write("----------------------------\n")
        pf.write(f"Data Upload Plan - {dt}\n")
        pf.write("----------------------------\n")

    # 5, Write the plan file with validated file paths
    # write ofop files first, video upload will trigger lambda function
    # which processes video files and will need ofop obser data for annotation
    # ofop is needed by video?
    passed_file_count = {}
    for i_data_type in data_types_list:
        if i_data_type in files_to_copy_dict.keys():
            passed_file_count[i_data_type] = write_validated_file_paths(
                data_type=i_data_type,
                files_list=files_to_copy_dict[i_data_type],
                cruise_id=cruise_id,
                plan_file=plan_file,
            )
    total_passed_file_counts = 0
    for i_data_type in files_to_copy_dict.keys():
        total_passed_file_counts += passed_file_count[i_data_type]
    logging.info(
        f"{total_passed_file_counts} files in total passed location verification for S3 upload"
    )
    logging.info(
        f"Please check plan.txt file contents for the files ready to be uploaded to S3..."
    )

if __name__ == "__main__":
    # 0, Set up logging
    set_up_log()

    # 1, read the config file
    config = Configs()
    config.read_config_file()

    # 2, get upload files
    try:
        (
            cruise_id,
            source_dirs_dict,
            environment,
            dry_run,
        ) = get_data_upload_info_from_args(config.cruises)
    except Exception as e:
        logging.error(f"Error getting data upload info: {e}")
        sys.exit(1)

    # 3, Check and validate local files and get the station IDs
    if config.if_validate_data:
        try:
            validate_local_files(
                source_dirs_dict,
                config.patterns,
                config.file_suffix,
            )
        except Exception as e:
            logging.exception(f"Error validating local files: {e}")
            sys.exit(1)
    else:
        logging.warning(
            "if_validate_data==false. Skipping local file validation. Please ensure files are ready for upload."
        )
        input("Press Enter to confirm and continue...")

    # 5, Set up AWS credentials
    provider = AWSCredentialProvider()
    manager = AWSBucketManager(
        environment=environment,
        aws_region="ap-southeast-2",
        credential_provider=provider.get_credentials_from_interaction,
        bucket_name=f"data-platform-dtis-{environment}-AWSACCOUNT-raw-data",
        lambda_function_name=f"dtis-ofop-{environment}",
    )
    aws_resources = manager.setup()

    # # 5 upload to S3 if not dry_run
    # confirmation = get_data_upload_confirmation(cruise_id)
    # if confirmation == "yes":

    # 6, Upload to S3
    upload_to_s3(
        plan_file_to_read_from=plan_file,
        environment=environment,
        dry_run=dry_run,
        cruise_id=cruise_id,
        s3_client=aws_resources['s3_client'],
        bucket_name=aws_resources['bucket_name'],
        aws_region=aws_region,
        sync_output_file=sync_output_file,
    )
    # Enable Lambda
    enable_lambda(
        lambda_client=lambda_client,
        lambda_function_name=lambda_function_name,
        success_file=success_file,
        error_file=error_file,
    )

        # # exit program
        # exit_confirmation = get_exit_confirmation()
        # if exit_confirmation == "yes":
        #     sys.exit("Closing down now, exiting...")
        # else:
        #     print("Sorry, please try again by setting DRY_RUN to true first...")
        #     sys.exit("Exiting the program now...")
