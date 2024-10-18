#!/bin/bash

# Set AWS configurations in the script (for S3 specifically)
aws configure set region ap-southeast-2
aws configure set output json
aws configure set s3.max_concurrent_requests 20
aws configure set s3.max_queue_size 10000
aws configure set s3.multipart_threshold 64MB
aws configure set s3.multipart_chunksize 16MB
aws configure set s3.max_bandwidth 200MB/s
aws configure set s3.use_accelerate_endpoint false
aws configure set s3.addressing_style virtual

# Enable case-insensitive pattern matching
shopt -s nocasematch

# Directory paths
images_dir="images"
ofop_dir="ofop"
videos_dir="videos"
success_file="success.txt"
error_file="error.txt"
sync_output_file="sync_logs.txt"

if [ -z "${NIWA_ENVIRONMENT}" ]; then
  echo "Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production"
  exit 1
else
  if [ "${NIWA_ENVIRONMENT}" == "testing" ]; then
    # S3 bucket details
    bucket_name="dtis-ofop-851725470721-raw-testing"
    region="ap-southeast-2"

    # Lambda function URL
    lambda_function_url=https://abcdefg.lambda-url.us-east-1.on.aws/
  elif [ "${NIWA_ENVIRONMENT}" == "production" ]; then
    # S3 bucket details
    bucket_name="TODO"
    region="ap-southeast-2"

    # Lambda function URL
    lambda_function_url=https://TODO.lambda-url.us-east-1.on.aws/
  else
    echo "Variable NIWA_ENVIRONMENT was not set to a supported value. Please set it to either testing or production"
    exit 1
  fi
fi

# Regex patterns based on naming conventions
image_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.jpeg$"
ofop_posi_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}_posi\.txt$"
ofop_prot_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}_prot\.txt$"
ofop_obser_rerun_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_rerun.*_obser\.txt$"
ofop_prot_rerun_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_rerun.*_prot\.txt$"
video_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}\.m2t[s]?$"

# Initialize the success and error files
echo "File Upload Success Report - $(date)" > "$success_file"
echo "----------------------------" >> "$success_file"
echo "File Upload Error Report - $(date)" > "$error_file"
echo "----------------------------" >> "$error_file"
echo "File Sync Report - $(date)" > "$sync_output_file"
echo "----------------------------" >> "$sync_output_file"

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
    echo "Checking $dir for image files..."

    for file in "$dir"/*; do
        if [[ ! $(basename "$file") =~ $image_pattern ]]; then
            echo "File does not match image naming convention: $(basename "$file")" >> "$error_file"
        else
            file_type=$(file --mime-type -b "$file")
            if [[ "$file_type" != "image/jpeg" ]]; then
                echo "File is not a valid JPEG: $(basename "$file") (Detected type: $file_type)" >> "$error_file"
            else
                echo "Uploading valid image file to S3: $(basename "$file")"
                upload_to_s3 "$file"
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

# Verify the S3 bucket
verify_s3_bucket

# Check Images directory for naming convention and file type
if [ -d "$images_dir" ]; then
    check_image_files "$images_dir"
else
    echo "$images_dir does not exist." >> "$error_file"
fi

# Check ofop directory for text file patterns and upload valid files
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
