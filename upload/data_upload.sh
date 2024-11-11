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
if [ -z "${NIWA_VIDEOS_DIR}" ]; then
  # NIWA_VIDEOS_DIR not set, so let's set it explicitly
  videos_dir="videos"
else
  videos_dir="${NIWA_VIDEOS_DIR}"
fi
if [ -z "${NIWA_OFOP_DIR}" ]; then
  # NIWA_OFOP_DIR not set, so let's set it explicitly
  ofop_dir="ofop"
else
  ofop_dir="${NIWA_OFOP_DIR}"
fi

if [ -z "${NIWA_CRUISE_ID}" ]; then
  echo "NIWA_CRUISE_ID not set, please set it explicitly"
  exit 1
fi

success_file="success.txt"
error_file="error.txt"
sync_output_file="sync_logs.txt"
plan_file="plan.txt"
aws_region="ap-southeast-2"
lambda_function_response_file="lambda_function_response.json"


if [ -z "${NIWA_DRY_RUN}" ]; then
  # dry run not set, so let's set it explicitly to false
  NIWA_DRY_RUN="false"
fi

if [ -z "${NIWA_ENVIRONMENT}" ]; then
  echo "Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production"
  exit 1
fi

if [ "${NIWA_ENVIRONMENT}" == "testing" ]; then
  # S3 bucket details
  bucket_name="dtis-ofop-851725470721-raw-testing"

  # Lambda function name
  lambda_function_name="test-dtis-ofop-mongodb_sync"
elif [ "${NIWA_ENVIRONMENT}" == "production" ]; then
  # S3 bucket details
  bucket_name="dtis-ofop-851725470721-raw-production"

  # Lambda function name
  lambda_function_name="prod-dtis-ofop-mongodb_sync"
else
  echo "Variable NIWA_ENVIRONMENT was not set to a supported value. Please set it to either testing or production"
  exit 1
fi

##############################################
# Subsection: Regex patterns based on file naming conventions
##############################################
# e.g. TAN1802_160_DTIS__004.jpeg
image_pattern1="^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.JPEG$"
# e.g. TAN1802_160_DTIS__004.jpg
image_pattern2="^[A-Z]{3}[0-9]{4}_[0-9]{3,}_DTIS__[0-9]{3}\.JPG$"
# e.g. TAN1802_Stn_160_004.jpeg
image_pattern3="^[A-Z]{3}[0-9]{4}_STN_[0-9]{3,}_[0-9]{3}\.JPEG$"
# e.g. TAN1802_Stn_160_004.jpg
image_pattern4="^[A-Z]{3}[0-9]{4}_STN_[0-9]{3,}_[0-9]{3}\.JPG$"
# e.g. TAN1802_160_004.jpg
image_pattern5="^[A-Z]{3}[0-9]{4}_[0-9]{3,}_[0-9]{3}\.JPG$"
# e.g. TAN1802_160_004.jpeg
image_pattern6="^[A-Z]{3}[0-9]{4}_[0-9]{3,}_[0-9]{3}\.JPEG$"

# e.g. TAN1802_001.m2t or TAN1802_001.m2ts
video_pattern1="^[A-Z]{3}[0-9]{4}_[0-9]{3}\.M2T[S]?$"
# e.g. 201012220153001.m2t or 201012220153001.m2ts (only digits)
video_pattern2="^[0-9]{4,}\.M2T[S]?$"

# e.g. TAN1802_001_posi.txt
ofop_posi_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}_POSI\.TXT$"
# e.g. TAN1802_001_prot.txt
ofop_prot_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}_PROT\.TXT$"
# e.g. TAN1802_001_obser.txt
ofop_obser_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}_OBSER\.TXT$"
# e.g. TAN1802_001.sth_rerun.sth_obser.txt
ofop_obser_rerun_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_RERUN.*_OBSER\.TXT$"
# e.g. TAN1802_001.sth_rerun.sth_prot.txt
ofop_prot_rerun_pattern="^[A-Z]{3}[0-9]{4}_[0-9]{3}.*_RERUN.*_PROT\.TXT$"

##############################################
# Section: functions
##############################################

# Function to verify if the S3 bucket is accessible
verify_s3_bucket() {
    if aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
        echo "Bucket Exists: $bucket_name"
    else
        echo "S3 bucket is not accessible or does not exist: $bucket_name" | tee -a "$error_file"
        exit 1  # Exit if the bucket doesn't exist or isn't accessible
    fi
}

function get_station_id() {
  local file_path=$1
  # make it fully upper case letters
  file_path_upper_case="${file_path^^}"

  set +e

  # First let's check if the file path matches the NIWA_CRUISE_ID;
  # if it does not, we exit the function. This file will not
  # be uploaded.
  if ! echo "${file_path_upper_case}" | grep -q "${NIWA_CRUISE_ID}" ; then
    echo "Error: File: ${file_path} does not come from the cruise of ID: ${NIWA_CRUISE_ID}" | tee -a "${error_file}"
    station_id=""
    return
  fi

  # Method 1 - extract station id from a directory name,
  # It works for files such as:
  # e.g. Video/TAN0616/TAN0616_003/TAN0616_045.m2ts

  # this gives, e.g. /TAN0616_003/
  local temp_parse
  temp_parse=$(echo "${file_path_upper_case}" | grep -oF "/${NIWA_CRUISE_ID}_[0-9]{3,}/")
  if [ $? -eq 0 ]; then
    # this gives, e.g. 003/
    temp_parse=$(echo "${temp_parse}" | awk -F '_' '{print $2}')
    # Remove possible trailing /
    temp_parse=${temp_parse%/}
    station_id="${temp_parse}"
  else
    # Method 1 did not work, let's try method 2.
    # It works for files such as:
    # e.g. images/dir with space/TAN1802_Stn_160_001.jpg

    # this gives, e.g. /TAN1802_Stn_160
    temp_parse=$(echo "${file_path_upper_case}" | grep -oE "/${NIWA_CRUISE_ID}_STN_[0-9]{3,}_")
    if [ $? -eq 0 ]; then
      # this gives, e.g. 160
      temp_parse=$(echo "${temp_parse}" | awk -F '_' '{print $3}')
      station_id="${temp_parse}"
      # remove whitespace
      station_id="$(echo -e "${station_id}" | sed -e 's/[[:space:]]*$//')"
    else
      # Method 2 did not work, let's try method 3.
      # It works for files such as:
      # e.g. images/dir with space/TAN1802_160_DTIS__004.jpeg

      # this gives, e.g. /TAN1802_160_
      temp_parse=$(echo "${file_path_upper_case}" | grep -oE "/${NIWA_CRUISE_ID}_[0-9]{3,}_")
      if [ $? -eq 0 ]; then
        # this gives, e.g. 160
        temp_parse=$(echo "${temp_parse}" | awk -F '_' '{print $2}')
        station_id="${temp_parse}"
        # remove whitespace
        station_id="$(echo -e "${station_id}" | sed -e 's/[[:space:]]*$//')"
      else
        # Method 3 did not work, let's try method 4.
        # It works for files such as:
        # e.g. text/TAN2203/OFOP text files/TAN2203_001.sth_rerun.sth_obser.txt

        # this gives, e.g. /TAN2203_001.sth_rerun
        temp_parse=$(echo "${file_path_upper_case}" | grep -oE "/${NIWA_CRUISE_ID}_[0-9]{3,}.*_RERUN")
        if [ $? -eq 0 ]; then
          # this gives, e.g. 160
          temp_parse=$(echo "${temp_parse}" | awk -F '_' '{print $2}' | awk -F '.' '{print $1}')
          station_id="${temp_parse}"
          # remove whitespace
          station_id="$(echo -e "${station_id}" | sed -e 's/[[:space:]]*$//')"
        else
          # Method 4 did not work, let's try method 5.
          # It works for files such as:
          # e.g. TAN2203/Stn003/1234.m2t

          # this gives, e.g. /TAN1802/STN003/
          temp_parse=$(echo "${file_path_upper_case}" | grep -oE "/${NIWA_CRUISE_ID}/STN[0-9]{3,}/")
          if [ $? -eq 0 ]; then
            # this gives, e.g. STN003
            temp_parse=$(echo "${temp_parse}" | awk -F '/' '{print $3}' | grep -oE "[0-9]{3,}")
            station_id="${temp_parse}"
            # remove whitespace
            station_id="$(echo -e "${station_id}" | sed -e 's/[[:space:]]*$//')"
          else
            # Method 5 did not work, let's try method 6.
            # It works for files such as:
            # e.g. /Stn002/11-04-2022/20220411191258.m2ts

            # this gives, e.g. /STN002/11-04-2022/2
            temp_parse=$(echo "${file_path_upper_case}" | grep -oE "/STN[0-9]{3,}/[0-9]{2}-[0-9]{2}-[0-9]{4}/*.M*")
            if [ $? -eq 0 ]; then
              # this gives, e.g. STN003
              temp_parse=$(echo "${temp_parse}" | awk -F '/' '{print $2}' | grep -oE "[0-9]{3,}")
              station_id="${temp_parse}"
              # remove whitespace
              station_id="$(echo -e "${station_id}" | sed -e 's/[[:space:]]*$//')"
            else
              echo "Error: Could not get station id for the file: ${file_path} (file path matches no pattern, potential cruise ID mismatch)" | tee -a "${error_file}"
            fi
          fi
        fi
      fi
    fi
  fi

  set -e
}

upload_to_s3() {
  # path to a local plan file
  local plan_file_to_read_from=$1
  if [[ ! -f "${plan_file_to_read_from}" ]]; then
    echo "Error: Plan file does not exist: ${plan_file_to_read_from}" | tee -a "${error_file}"
    exit 1
  fi

  declare -a plan_file_as_array=()
  readarray -t plan_file_as_array < "${plan_file_to_read_from}"

  # either: video, text, or image
  local file_type=""

  for plan_file_line in "${plan_file_as_array[@]}"; do
    if [[ "${plan_file_line}" =~ "The following image files passed local verification:" ]]; then
      file_type="images"
    elif [[ "${plan_file_line}" =~ "The following text files passed local verification:" ]]; then
      file_type="text"
    elif [[ "${plan_file_line}" =~ "The following video files passed local verification:" ]]; then
      file_type="video"
    fi
    # shellcheck disable=SC2076
    if [[ ! "${plan_file_line}" =~ "." ]] || [[ ! "${plan_file_line}" =~ ";" ]]; then
      # ignore the lines with comments
      continue
    fi
    file_path=$(echo "${plan_file_line}" | awk -F ';' '{print $1}')
    station_id=$(echo "${plan_file_line}" | awk -F ';' '{print $2}')
    file_basename=$(basename "$file_path")
    s3_destination="s3://${bucket_name}/${NIWA_CRUISE_ID}/${station_id}/${file_type}/${file_basename}"

    # Run the upload command and capture the output
    if [[ "${NIWA_DRY_RUN}" == "true" ]]; then
      echo "Pretending to be uploading ${file_path} to ${s3_destination}" | tee -a "${success_file}"
    else
      echo "Really uploading ${file_path} to ${s3_destination}" | tee -a "${success_file}"
      # real upload happens here
      if aws s3api head-object --bucket "${bucket_name}" --key "${NIWA_CRUISE_ID}/${station_id}/${file_type}/${file_basename}" >/dev/null 2>/dev/null; then
        sync_output="S3 object exists already, not uploading"
        sync_output_exit_status=0
      else
        sync_output=$(set -x; aws s3 cp "${file_path}" "${s3_destination}" --storage-class "STANDARD_IA")
        sync_output_exit_status=$?
      fi

      echo "$sync_output" | tee -a "$sync_output_file"
      if [ ${sync_output_exit_status} -eq 0 ]; then
          # Upload successful, write the output to the success file
          echo "Success uploading to S3: ${file_path}" | tee -a "${success_file}"
      else
          # Upload successful, write the output to the error file
          echo "Error uploading to S3: ${file_path}" | tee -a  "${error_file}"
      fi
    fi
  done
}


# A bash function which verifies local image files. It checks:
# * that the file name matches a naming convention
# * that the file type is jpeg
check_image_files() {
    local dir=$1
    echo "Checking ${dir} for image files..."

    if [[ "${dir}" == "ignore" ]]; then
      echo "Images directory was set to 'ignore', cancelling the check"
      return
    fi
    if [ ! -d "$dir" ]; then
        echo "Error: Images directory: $dir does not exist." | tee -a "$error_file"
        exit 1
    fi

    # Find all the files, in the images directory, with the selected
    # file extensions.
    # Write the file names into an bash array.
    readarray files_with_matching_extension < <(find "${dir}" -name '*.jpg' -o -name '*.jpeg' -o -name '*.JPEG' -o -name '*.JPG')

    for file in "${files_with_matching_extension[@]}"; do
      #echo "file is ${file}"
      file_no_trailing_whitespace="$(echo -e "${file}" | sed -e 's/[[:space:]]*$//')"

      file_name=$(basename "$file")
      # make it fully upper case letters
      file_path_upper_case="${file_name^^}"

      if [[ ! "${file_path_upper_case}" =~ ${image_pattern1} ]] && [[ ! "${file_path_upper_case}" =~ ${image_pattern2} ]] && [[ ! "${file_path_upper_case}" =~ ${image_pattern3} ]] && [[ ! "${file_path_upper_case}" =~ ${image_pattern4} ]] && [[ ! "${file_path_upper_case}" =~ ${image_pattern5} ]] && [[ ! "${file_path_upper_case}" =~ ${image_pattern6} ]]; then
        echo "Error: File does not match image naming convention: ${file_no_trailing_whitespace}" | tee -a "$error_file"
        continue
      fi

      file_type=$(file --mime-type -b "${file_no_trailing_whitespace}")
      if [[ "$file_type" != "image/jpeg" ]]; then
        echo "Error: File is not a valid JPEG: ${file_no_trailing_whitespace} (Detected type: $file_type)" | tee -a "$error_file"
      else
        image_files_to_copy+=("${file_no_trailing_whitespace}")
      fi
    done
}

# A bash function which verifies local video files. It checks:
# * that the file name matches a naming convention
# * that the file type is video
check_video_files() {
    local dir=$1
    echo "Checking $dir for video files..."

    if [[ "${dir}" == "ignore" ]]; then
      echo "Videos directory was set to 'ignore', cancelling the check"
      return
    fi

    if [ ! -d "$dir" ]; then
      echo "Error: Videos directory: $dir does not exist." | tee -a "$error_file"
      exit 1
    fi

    # Find all the files, in the videos directory, with the selected
    # file extensions.
    # Write the file names into an bash array.
    readarray files_with_matching_extension < <(find "${dir}" -name '*.m2t' -o -name '*.m2ts'  -o -name '*.M2TS' -o -name '*.M2T')

    for file in "${files_with_matching_extension[@]}"; do
      file_no_trailing_whitespace="$(echo -e "${file}" | sed -e 's/[[:space:]]*$//')"

      file_name=$(basename "$file")
      # make it fully upper case letters
      file_path_upper_case="${file_name^^}"
      if [[ ! "${file_path_upper_case}" =~ ${video_pattern1} ]] && [[ ! "${file_path_upper_case}" =~ ${video_pattern2} ]]; then
        echo "Error: File does not match video naming convention: ${file_no_trailing_whitespace}" | tee -a "$error_file"
        continue
      fi

      if [[ "${NIWA_DRY_RUN}" == "true" ]]; then
        # We don't want to upload video files to the git repository,
        # because video files are usually big and storing them in a git
        # repository is not a right thing to do.
        echo "NIWA_DRY_RUN is set, so skipping video file type verification"
        video_files_to_copy+=("${file_no_trailing_whitespace}")
        continue
      fi

      file_type=$(file --mime-type -b "${file_no_trailing_whitespace}")
      if [[ "$file_type" != "video/MP2T" ]]; then
        echo "Error: File is not a valid .m2t or .m2ts file: ${file_no_trailing_whitespace} (Detected type: $file_type)" | tee -a "$error_file"
      else
        video_files_to_copy+=("${file_no_trailing_whitespace}")
      fi
    done
}

# A bash function which verifies local text files. It checks:
# * that the file name matches a naming convention
# * that the file type is text
check_ofop_files() {
    local dir=$1
    echo "Checking $dir for text files..."

    # Find all the files, in the videos directory, with the selected
    # file extensions.
    # Write the file names into an bash array.
    readarray files_with_matching_extension < <(find "${dir}" -name '*.txt' -o -name '*.TXT')

    for file in "${files_with_matching_extension[@]}"; do
      file_no_trailing_whitespace="$(echo -e "${file}" | sed -e 's/[[:space:]]*$//')"

      file_name=$(basename "$file")
      # make it fully upper case letters
      file_path_upper_case="${file_name^^}"

      file_type=$(file --mime-type -b "${file_no_trailing_whitespace}")
      if [[ "$file_type" != "text/plain" ]]; then
        echo "Error: File is not a valid text file: ${file_no_trailing_whitespace} (Detected type: $file_type)" | tee -a "$error_file"
        continue
      fi

      if [[ "${file_path_upper_case}" =~ $ofop_posi_pattern || \
            "${file_path_upper_case}" =~ $ofop_prot_pattern || \
            "${file_path_upper_case}" =~ $ofop_obser_pattern || \
            "${file_path_upper_case}" =~ $ofop_obser_rerun_pattern || \
            "${file_path_upper_case}" =~ $ofop_prot_rerun_pattern ]]; then
        text_files_to_copy+=("${file_no_trailing_whitespace}")
      else
        echo "Error: File does not match any pattern: ${file_name}" | tee -a  "$error_file"
      fi
    done
}

# Function to invoke the Lambda function using AWS CLI
invoke_lambda_function() {
    echo "Invoking Lambda function: $function_name..."

    # Invoke the Lambda function and capture the response
    aws lambda invoke --function-name "$lambda_function_name" "$lambda_function_response_file"

    # Check if the invocation was successful
    if [ $? -eq 0 ]; then
        echo "Lambda function invoked successfully - $(date). Response saved to $lambda_function_response_file" >> "$success_file"
    else
        echo "Failed to invoke Lambda function: $function_name - $(date)" >> "$error_file"
    fi
}

function write_validated_file_paths() {
  # this is either: video, text, or image
  local file_type=$1
  # https://askubuntu.com/a/995110/665365
  shift
  # this is an array of local file paths
  local files_array=("$@")

  echo "The following ${file_type} files passed local verification:" >> "${plan_file}"
  echo "FILE_PATH;STATION_ID" >> "${plan_file}"
  for file in "${files_array[@]}"; do
    station_id=""
    get_station_id "${file}"
    if [[ "${station_id}" != "" ]]; then
      # TODO: remove this?
      echo "Station ID, for the file: ${file}, is: ${station_id}" | tee -a "${success_file}"
      echo "${file};${station_id}" >> "${plan_file}"
    fi
  done
  echo "End of ${file_type} files that passed local verification" >> "${plan_file}"
  echo "" >> "${plan_file}"
}

##############################################
# Section: the actual run
##############################################

if [[ "${NIWA_DRY_RUN}" == "true" ]]; then

  ##############################################
  # SubSection: Initialize the log files
  ##############################################
  # 1. Cleanup the contents of the log files (truncate them)
  true > "${error_file}"
  true > "${success_file}"
  true > "${sync_output_file}"
  true > "${plan_file}"

  # 2. Write informative headers to the log files
  echo "File Upload Success Report - $(date)" > "$success_file"
  echo "----------------------------" >> "$success_file"
  echo "File Upload Error Report - $(date)" > "$error_file"
  echo "----------------------------" >> "$error_file"
  echo "File Sync Report - $(date)" > "$sync_output_file"
  echo "----------------------------" >> "$sync_output_file"
  echo "Data Upload Plan - $(date)" > "$plan_file"
  echo "----------------------------" >> "$plan_file"
  # shellcheck disable=SC2129
  echo "Environment Name: ${NIWA_ENVIRONMENT}" >> "$sync_output_file"
  echo "S3 Bucket Name: ${bucket_name}" >> "$sync_output_file"
  echo "Region: ${aws_region}" >> "$sync_output_file"

  ##############################################
  # SubSection: Verify the local files containing dtis data
  ##############################################

  ##############################################
  # SubSubSection: image files
  ##############################################
  # This array will contain the set of image files, which passed
  # the local verification steps
  declare -a image_files_to_copy=()

  # Check Images directory for naming convention and file type
  check_image_files "$images_dir"
  # Check station ID, write which files passed all the checks into a file
  write_validated_file_paths "image" "${image_files_to_copy[@]}"

  ##############################################
  # SubSubSection: video files
  ##############################################
  # This array will contain the set of video files, which passed
  # the local verification steps
  declare -a video_files_to_copy=()

  # Check Videos directory for naming convention and file type
  check_video_files "$videos_dir"
  # Check station ID, write which files passed all the checks into a file
  write_validated_file_paths "video" "${video_files_to_copy[@]}"

  ##############################################
  # SubSubSection: text files
  ##############################################
  # This array will contain the set of text files, which passed
  # the local verification steps
  declare -a text_files_to_copy=()

  # Check text directory for naming convention and file type
  if [ -d "$ofop_dir" ]; then
      check_ofop_files "$ofop_dir"
  else
      echo "Text files directory: $ofop_dir does not exist." | tee -a "$error_file"
      exit 1
  fi

  # Check station ID, write which files passed all the checks into a file
  write_validated_file_paths "text" "${text_files_to_copy[@]}"

  ##############################################
  # SubSubSection: Finish the local verification
  ##############################################
  echo "" | tee -a "$success_file"
  echo "Local files verification completed." | tee -a "$success_file"
  echo "Please read ${plan_file} to see which files passed local verification." | tee -a "$success_file"
  echo "" | tee -a "$success_file"

fi
##############################################
# SubSection: Verify the S3 bucket and local AWS CLI settings
##############################################

if [[ "${NIWA_DRY_RUN}" != "true" ]]; then
  # Verify the S3 bucket
  verify_s3_bucket

  # Set AWS configurations in the script (for S3 specifically)
  echo "Setting AWS configurations"
  aws configure set region "${aws_region}"
  aws configure set output json
  aws configure set s3.max_concurrent_requests 20
  aws configure set s3.max_queue_size 10000
  aws configure set s3.multipart_threshold 64MB
  aws configure set s3.multipart_chunksize 16MB
  aws configure set s3.max_bandwidth 200MB/s
  aws configure set s3.use_accelerate_endpoint false
  aws configure set s3.addressing_style virtual
  echo "Finished setting AWS configurations"
fi

##############################################
# Section: Upload
##############################################

echo "----------------------------" | tee -a  "$success_file"
echo "Uploading files to S3 - $(date)" | tee -a  "$success_file"
echo "----------------------------" | tee -a  "$success_file"

upload_to_s3 "${plan_file}"

if [[ "${NIWA_DRY_RUN}" == "true" ]]; then
  echo "" | tee -a "$success_file"
  echo "Exit, because dry run is set" | tee -a "$success_file"
  echo "Please read ${plan_file} to see which files passed local verification." | tee -a "$success_file"
  exit 0
fi

##############################################
# Section: Trigger the Lambda function
##############################################
# Trigger the Lambda function after upload completes
if [[ "${NIWA_DRY_RUN}" != "true" ]]; then
  echo "----------------------------" | tee -a  "$success_file"
  echo "----------------------------" | tee -a  "$error_file"
  invoke_lambda_function
  exit 0
fi
