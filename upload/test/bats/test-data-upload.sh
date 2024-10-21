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

@test "run data_upload with NIWA_ENVIRONMENT exits with success" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && ../../data_upload.sh"
	assert_output "Exit, because dry run is set"
	assert_equal "$status" 0
}
