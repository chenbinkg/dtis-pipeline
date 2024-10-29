#!/usr/bin/env bash

# Fail fast on any error
set -Eeo pipefail

# Enable case-insensitive pattern matching
shopt -s nocasematch

##############################################
# Section: setting the variables
##############################################

# Directory paths
if [ -z "${NIWA_IMAGES_DIR}" ]; then
  # NIWA_IMAGES_DIR not set, so let's set it explicitly
  images_dir="images"
else
  images_dir="${NIWA_IMAGES_DIR}"
fi
ofop_dir="ofop"
videos_dir="videos"
success_file="success.txt"
error_file="error.txt"
sync_output_file="sync_logs.txt"
aws_region="ap-southeast-2"

if [ -z "${NIWA_DRY_RUN}" ]; then
  # dry run not set, so let's set it explicitly to false
  NIWA_DRY_RUN="false"
fi

if [ -z "${NIWA_ENVIRONMENT}" ]; then
  echo "Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production"
  exit 1
else
  if [ "${NIWA_ENVIRONMENT}" == "testing" ]; then
    # S3 bucket details
    bucket_name="dtis-ofop-851725470721-raw-testing"

    # Lambda function URL
    lambda_function_url=https://abcdefg.lambda-url.us-east-1.on.aws/
  elif [ "${NIWA_ENVIRONMENT}" == "production" ]; then
    # S3 bucket details
    bucket_name="dtis-ofop-851725470721-raw-testing"

    # Lambda function URL
    lambda_function_url=https://TODO.lambda-url.us-east-1.on.aws/
  else
    echo "Variable NIWA_ENVIRONMENT was not set to a supported value. Please set it to either testing or production"
    exit 1
  fi
fi

##############################################
# Subsection: Regex patterns based on naming conventions
##############################################
# e.g. TAN1802_160_DTIS__004.jpeg
image_pattern1="^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.jpeg$"
# e.g. TAN1802_160_DTIS__004.jpg
image_pattern2="^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.jpg$"
# e.g. TAN1802_Stn_160_004.jpeg
image_pattern3="^[A-Z]{3}[0-9]{4}_Stn_[0-9]{3,}_[0-9]{3}\.jpeg$"
# e.g. TAN1802_Stn_160_004.jpg
image_pattern4="^[A-Z]{3}[0-9]{4}_Stn_[0-9]{3,}_[0-9]{3}\.jpg$"

ofop_posi_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}_posi\.txt$"
ofop_prot_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}_prot\.txt$"
ofop_obser_rerun_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_rerun.*_obser\.txt$"
ofop_prot_rerun_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_rerun.*_prot\.txt$"
video_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}\.m2t[s]?$"

##############################################
# Section: functions
##############################################

# Function to verify if the S3 bucket is accessible
verify_s3_bucket() {
    if aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
        echo "Bucket Exists: $bucket_name"
    else
        echo "S3 bucket is not accessible or does not exist: $bucket_name" >> "$error_file"
        exit 1  # Exit if the bucket doesn't exist or isn't accessible
    fi
}

# Extract cruise ID (e.g., TAN0616) from the file name
extract_cruise_id() {
    local file_name=$(basename "$1")
    if [[ "$file_name" =~ ^([A-Z]{3}[0-9]{4})_ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "UNKNOWN"
    fi
}

upload_to_s3() {
    local file=$1  # This will be used for logging
    local dir=$(dirname "$file")  # Directory extracted from the file path
    local cruise_id=$(extract_cruise_id "$(ls "$dir" | head -n 1)")

    if [ "$cruise_id" != "UNKNOWN" ]; then
        # Run the sync command and capture the output
        sync_output=$(aws s3 sync "$dir" "s3://$bucket_name/$cruise_id/" --exclude ".DS_Store" --exclude "*/.DS_Store")

        # Check if the sync was successful
        if [ $? -eq 0 ]; then
            # Log each uploaded file to the success file
            echo "$sync_output" >> "$sync_output_file"
            echo "Sync to S3: $file" >> "$success_file"
        else
            # If sync fails, log the error
            echo "Error uploading directory to S3: $dir" >> "$error_file"
        fi
    else
        echo "Could not extract cruise ID for directory: $dir" >> "$error_file"
    fi
}


# Function to check files against a pattern and their actual type (Images)
check_image_files() {
    local dir=$1
    echo "Checking ${dir} for image files..."

    # Find all the files, in the images directory, with the selected
    # file extensions.
    # Write the file names into an bash array.
    readarray files_with_matching_extension < <(find "${dir}" -name '*.jpg' -o -name '*.jpeg')

    for file in "${files_with_matching_extension[@]}"; do
      #echo "file is ${file}"
      file_no_trailing_whitespace="$(echo -e "${file}" | sed -e 's/[[:space:]]*$//')"
      #echo "file_no_trailing_whitespace is ${file_no_trailing_whitespace}"

      file_name=$(basename "$file")
        if [[ ! "${file_name}" =~ ${image_pattern1} ]] && [[ ! "${file_name}" =~ ${image_pattern2} ]] && [[ ! "${file_name}" =~ ${image_pattern3} ]] && [[ ! "${file_name}" =~ ${image_pattern4} ]]; then
            echo "File does not match image naming convention: ${file_no_trailing_whitespace}" | tee -a "$error_file"
        else
          file_type=$(file --mime-type -b "${file_no_trailing_whitespace}")
          if [[ "$file_type" != "image/jpeg" ]]; then
              echo "File is not a valid JPEG: ${file_no_trailing_whitespace} (Detected type: $file_type)" | tee -a "$error_file"
          else
            image_files_to_copy+=("${file_no_trailing_whitespace}")
          fi
      fi
    done
}

# Function to check files against a pattern and their actual type (Videos)
check_video_files() {
    local dir=$1
    echo "Checking $dir for video files..."

    for file in "$dir"/*; do
        if [[ ! $(basename "$file") =~ $video_pattern ]]; then
            echo "File does not match video naming convention: $(basename "$file")" >> "$error_file"
        else
            file_type=$(file --mime-type -b "$file")
            if [[ "$file_type" != "video/MP2T" ]]; then
                echo "File is not a valid .m2t or .m2ts file: $(basename "$file") (Detected type: $file_type)" >> "$error_file"
            else
                echo "Uploading valid video file to S3: $(basename "$file")"
                upload_to_s3 "$file"
            fi
        fi
    done
}

# Function to check ofop text files against specific patterns and upload valid files to S3
check_ofop_files() {
    local dir=$1

    echo "Checking $dir for text files with specific patterns..."

    for file in "$dir"/*; do
        if [[ $(basename "$file") =~ $ofop_posi_pattern || \
              $(basename "$file") =~ $ofop_prot_pattern || \
              $(basename "$file") =~ $ofop_obser_rerun_pattern || \
              $(basename "$file") =~ $ofop_prot_rerun_pattern ]]; then
            echo "File matches a valid pattern: $(basename "$file")"
            # Upload the matching file to S3
            upload_to_s3 "$file"
        else
            echo "File does not match any pattern: $(basename "$file")" >> "$error_file"
        fi
    done
}

# Trigger Lambda function via Lambda Function URL
trigger_lambda_function() {
    echo "Triggering Lambda function via URL..."

    # Make a POST request to the Lambda function URL
    response=$(curl -s -w "%{http_code}" -o /dev/null -X POST "$lambda_function_url")

    if [ "$response" == "200" ]; then
        echo "Lambda function triggered successfully." >> "$success_file"
    else
        echo "Failed to trigger Lambda function. HTTP response code: $response" >> "$error_file"
    fi
}

##############################################
# Section: the actual run
##############################################

##############################################
# SubSection: Initialize the log files
##############################################
# 1. Cleanup the contents of the log files (truncate them)
true > "${error_file}"
true > "${success_file}"
true > "${sync_output_file}"

# 2. Write informative headers to the log files
echo "File Upload Success Report - $(date)" > "$success_file"
echo "----------------------------" >> "$success_file"
echo "File Upload Error Report - $(date)" > "$error_file"
echo "----------------------------" >> "$error_file"
echo "File Sync Report - $(date)" > "$sync_output_file"
echo "----------------------------" >> "$sync_output_file"
echo "Environment Name: ${NIWA_ENVIRONMENT}" >> "$sync_output_file"
echo "S3 Bucket Name: ${bucket_name}" >> "$sync_output_file"
echo "Region: ${aws_region}" >> "$sync_output_file"

##############################################
# SubSection: Verify the local files with dtis data
##############################################

# This array will contain the set of image files, which passed
# the local verification steps
declare -a image_files_to_copy=()

# Check Images directory for naming convention and file type
if [ -d "$images_dir" ]; then
    check_image_files "$images_dir"
else
    echo "Images directory: $images_dir does not exist." | tee -a "$error_file"
    exit 1
fi

echo "The following images will be copied to S3:"
echo "${image_files_to_copy[@]}"

if [[ "${NIWA_DRY_RUN}" == "true" ]]; then
  echo "Exit, because dry run is set"
  exit 0
fi

##############################################
# SubSection: Verify the S3 bucket
##############################################


# Set AWS configurations in the script (for S3 specifically)
aws configure set region "${aws_region}"
aws configure set output json
aws configure set s3.max_concurrent_requests 20
aws configure set s3.max_queue_size 10000
aws configure set s3.multipart_threshold 64MB
aws configure set s3.multipart_chunksize 16MB
aws configure set s3.max_bandwidth 200MB/s
aws configure set s3.use_accelerate_endpoint false
aws configure set s3.addressing_style virtual

# Verify the S3 bucket
verify_s3_bucket

# Check ofop directory for text file patterns
if [ -d "$ofop_dir" ]; then
    check_ofop_files "$ofop_dir"
else
    echo "$ofop_dir does not exist." >> "$error_file"
fi

# Check Videos directory for naming convention and file type
if [ -d "$videos_dir" ]; then
    check_video_files "$videos_dir"
else
    echo "$videos_dir does not exist." >> "$error_file"
fi

# Final notification after upload completion
echo "File check and upload completed."

# Trigger the Lambda function after upload completes
# trigger_lambda_function
