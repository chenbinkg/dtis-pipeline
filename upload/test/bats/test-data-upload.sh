#!/usr/bin/env bats

# https://bats-core.readthedocs.io/en/stable/docker-usage.html
setup() {
    bats_load_library bats-support
    bats_load_library bats-assert
}

@test "run data_upload without NIWA_ENVIRONMENT exits with error" {
  run bash -c "export NIWA_DRY_RUN='true' && ../../data_upload.sh"
	assert_output "Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production"
	assert_equal "$status" 1
}

@test "run data_upload with NIWA_ENVIRONMENT exits with success and log file shows no images dir" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output "Images directory: images does not exist."
	assert_equal "$status" 0
}

@test "run data_upload with NIWA_ENVIRONMENT and NIWA_IMAGES_DIR, but invalid jpg file name" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/images for image files..."
	assert_equal "$status" 0

  run bash -c "cat error.txt"
	assert_output "File does not match image naming convention: bad-file-name.jpg"
	assert_equal "$status" 0
}
