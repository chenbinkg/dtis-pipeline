#!/usr/bin/env bats

# https://bats-core.readthedocs.io/en/stable/docker-usage.html
setup() {
    bats_load_library bats-support
    bats_load_library bats-assert
}

@test "run data_upload without NIWA_ENVIRONMENT, exits with error" {
  run bash -c "export NIWA_DRY_RUN='true' && ../../data_upload.sh"
	assert_output "Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production"
	assert_equal "$status" 1
}

@test "run data_upload with NIWA_ENVIRONMENT, exits with success and log file shows images dir does not exist" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output --partial "Images directory: images does not exist."
	assert_equal "$status" 0
}

@test "run data_upload with NIWA_ENVIRONMENT and NIWA_IMAGES_DIR, test for image files verification" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/images for image files..."
  assert_output --partial "The following images will be copied to S3:
../test-data/images/dir with space/TAN1802_Stn_160_001.jpg ../test-data/images/dir with space/TAN1802_160_DTIS__004.jpeg ../test-data/images/Tan1802_160/TAN1802_Stn_160_016.jpg ../test-data/images/Tan1802_160/TAN1802_Stn_160_001.jpg ../test-data/images/Tan1802_160/TAN1802_Stn_160_002.jpeg"
	assert_equal "$status" 0

  run bash -c "cat error.txt"
  # we should see these errors, regarding naming conventions
	assert_output --partial "File does not match image naming convention: ../test-data/images/TAN2203_002/example2.jpg"
	assert_output --partial "File does not match image naming convention: ../test-data/images/TAN2203_002/example.jpg"
	assert_output --partial "File does not match image naming convention: ../test-data/images/bad-file-name.jpg"
  # we should see these errors, regarding file type
	assert_output --partial "File is not a valid JPEG: ../test-data/images/Tan1802_160/TAN1802_Stn_160_033.jpg (Detected type: text/plain)"

  # we should NOT see these errors
	refute_output --partial "File does not match image naming convention: ../test-data/images/dir with space/TAN1802_160_DTIS__004.jpg"
	refute_output --partial "File does not match image naming convention: ../test-data/images/dir with space/TAN1802_Stn_160_001.jpg"
	refute_output --partial "File does not match image naming convention: ../test-data/images/Tan1802_160/TAN1802_Stn_160_002.jpeg"
	refute_output --partial "File does not match image naming convention: ../test-data/images/Tan1802_160/TAN1802_Stn_160_016.jpg"
	assert_equal "$status" 0
}
