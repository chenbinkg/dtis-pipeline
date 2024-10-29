#!/usr/bin/env bats

# https://bats-core.readthedocs.io/en/stable/docker-usage.html
setup() {
    bats_load_library bats-support
    bats_load_library bats-assert
    export NIWA_CRUISE_ID=123
}

@test "run data_upload without NIWA_ENVIRONMENT, exits with error" {
  run bash -c "export NIWA_DRY_RUN='true' && ../../data_upload.sh"
	assert_output "Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production"
	assert_equal "$status" 1
}

@test "run data_upload with NIWA_ENVIRONMENT, but fails because images dir does not exist" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output --partial "Images directory: images does not exist."
	assert_equal "$status" 0
}

@test "run data_upload with NIWA_ENVIRONMENT, but fails because videos dir does not exist" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output --partial "Videos directory: videos does not exist."
	assert_equal "$status" 0
}

@test "run data_upload with NIWA_ENVIRONMENT, but fails because text dir does not exist" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2023' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output --partial "Text files directory: ofop does not exist."
	assert_equal "$status" 0
}

@test "run data_upload with NIWA_ENVIRONMENT, test for image files verification" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2023' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && ../../data_upload.sh"
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

@test "run data_upload with NIWA_ENVIRONMENT, test for video files verification (dir: 2023)" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2023' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/2023 for video files..."
  assert_output --partial "The following videos will be copied to S3:
../test-data/2023/Video/TAN0616/TAN0616_003/1234.m2t ../test-data/2023/Video/TAN0616/TAN0616_003/201012220153000.m2t ../test-data/2023/Video/TAN0616/TAN0616_003/TAN0616_045.m2ts ../test-data/2023/Video/TAN0616_sthsth/TAN0616_003/201012220153000.m2t"
	assert_equal "$status" 0

  run bash -c "cat error.txt"
  # we should see these errors, regarding naming conventions
	assert_output --partial "File does not match video naming convention: ../test-data/2023/Video/TAN0616_sthsth/TAN0616_003/example.m2t"
	assert_equal "$status" 0
}

@test "run data_upload with NIWA_ENVIRONMENT, test for video files verification (dir: 2010-2019)" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2010-2019' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/2010-2019 for video files..."
  assert_output --partial "The following videos will be copied to S3:
../test-data/2010-2019/Video/TAN0616/TAN0616_003/sth/201012220153000.m2ts ../test-data/2010-2019/Video/TAN0616/TAN0616_003/sth/sth/201012220153001.m2t ../test-data/2010-2019/Video/TAN0616/TAN0616_003/sth/sth/TAN1802_001.m2ts ../test-data/2010-2019/Video/TAN0616/TAN0616_003/sth/201012220153000.m2t"
	assert_equal "$status" 0

  run bash -c "cat error.txt"
  # we should see these errors, regarding naming conventions
	assert_output --partial "File does not match video naming convention: ../test-data/2010-2019/Video/TAN0616/TAN0616_003/sth/sth/1.m2t"
	assert_equal "$status" 0
}

@test "run data_upload with NIWA_ENVIRONMENT, test for text files verification" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2010-2019' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/text/TAN2203 for text files..."
  assert_output --partial "The following text files will be copied to S3:
../test-data/text/TAN2203/OFOP text files/tan2203_001_prot.txt ../test-data/text/TAN2203/OFOP text files/TAN2203_001_posi.txt ../test-data/text/TAN2203/OFOP text files/tan2203_001_posi.txt"

	assert_equal "$status" 0

  run bash -c "cat error.txt"
  # we should see these errors, regarding naming conventions
	assert_output --partial "File does not match any pattern: tan2203_001_test_obser.txt"
	assert_output --partial "File does not match any pattern: tan2203_001_obser.txt"
	assert_output --partial "File does not match any pattern: tan1802_113_AcousticMarkWatercolumnshot_obser.txt"
	assert_equal "$status" 0
}
