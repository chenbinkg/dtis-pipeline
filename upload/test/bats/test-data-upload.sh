#!/usr/bin/env bats

# https://bats-core.readthedocs.io/en/stable/docker-usage.html
setup() {
    bats_load_library bats-support
    bats_load_library bats-assert
    # set this as a default for all tests,
    # can be overriden if needed
    export NIWA_CRUISE_ID=TAN123
}

@test "NIWA_ENVIRONMENT not set, exits with error" {
  run bash -c "export NIWA_DRY_RUN='true' && ../../data_upload.sh"
	assert_output "Variable NIWA_ENVIRONMENT was not set. Please set it to either testing or production"
	assert_equal "$status" 1
}

@test "images dir does not exist, fails" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output --partial "Images directory: images does not exist."
	assert_equal "$status" 0
}

@test "videos dir does not exist, fails" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output --partial "Videos directory: videos does not exist."
	assert_equal "$status" 0
}

@test "text dir does not exist, fails" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2023' && ../../data_upload.sh"
	assert_equal "$status" 1

  run bash -c "cat error.txt"
	assert_output --partial "Text files directory: ofop does not exist."
	assert_equal "$status" 0
}

@test "cruise ID: TAN123, no file matches" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2010-2019' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/text/TAN2203 for text files..."
  assert_output --partial "Checking ../test-data/images for image files..."
  assert_output --partial "Checking ../test-data/2010-2019 for video files..."

	assert_equal "$status" 0

  run bash -c "cat error.txt"
	assert_output --partial "File does not match any pattern: tan2203_001_test_obser.txt"
	assert_output --partial "Error: File: ../test-data/text/TAN2203/OFOP text files/tan2203_001_obser.txt does not come from the cruise of ID: TAN123"
	assert_output --partial "File does not match any pattern: tan1802_113_AcousticMarkWatercolumnshot_obser.txt"
	assert_output --partial "File does not match image naming convention: ../test-data/images/TAN2203_002/example2.jpg"
	assert_output --partial "File does not match image naming convention: ../test-data/images/TAN2203_002/example.jpg"
	assert_output --partial "File does not match image naming convention: ../test-data/images/bad-file-name.jpg"
	assert_output --partial "File is not a valid JPEG: ../test-data/images/Tan1802_160/TAN1802_Stn_160_033.jpg (Detected type: text/plain)"
	refute_output --partial "File does not match image naming convention: ../test-data/images/dir with space/TAN1802_160_DTIS__004.jpg"
	refute_output --partial "File does not match image naming convention: ../test-data/images/dir with space/TAN1802_Stn_160_001.jpg"
	refute_output --partial "File does not match image naming convention: ../test-data/images/Tan1802_160/TAN1802_Stn_160_002.jpeg"
	refute_output --partial "File does not match image naming convention: ../test-data/images/Tan1802_160/TAN1802_Stn_160_016.jpg"
	assert_output --partial "File does not match video naming convention: ../test-data/2010-2019/Video/TAN0616/TAN0616_003/sth/sth/1.m2t"
	assert_equal "$status" 0

  # check that no files passed the local verification
  run bash -c "cat plan.txt"
	refute_output --partial "test-data"
}

@test "cruise ID: TAN123, videos from 2023, no file matches" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2023' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/2023 for video files..."
	assert_equal "$status" 0

  run bash -c "cat error.txt"
  # we should see these errors, regarding naming conventions
	assert_output --partial "File does not match video naming convention: ../test-data/2023/Video/TAN0616_sthsth/TAN0616_003/example.m2t"
	assert_equal "$status" 0

  # check that no files passed the local verification
  run bash -c "cat plan.txt"
	refute_output --partial "test-data"
}


@test "cruise ID: TAN1802, some file matches" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2010-2019' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && export NIWA_CRUISE_ID=TAN1802 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/images for image files..."
  assert_output --partial "Checking ../test-data/2010-2019 for video files..."
  assert_output --partial "Checking ../test-data/text/TAN2203 for text files..."

  # contains Stn
  assert_output --partial "Station ID, for the file: ../test-data/images/dir with space/TAN1802_Stn_160_001.jpg, is: 160"
  # contains DTIS
  assert_output --partial "Station ID, for the file: ../test-data/images/dir with space/TAN1802_160_DTIS__004.jpeg, is: 160"
  # cruise id is mixed-case (not: TAN, but: Tan)
  assert_output --partial "Station ID, for the file: ../test-data/images/Tan1802_160/Tan1802_Stn_160_009.jpg, is: 160"
  # directory name is /Stn003/
  assert_output --partial "Station ID, for the file: ../test-data/2010-2019/Video/TAN1802/Stn003/1234.m2t, is: 003"
  # Stn002/11-04-2022/20220411191258.m2ts
  assert_output --partial "Station ID, for the file: ../test-data/2010-2019/Voyage 2022-2024/Video/TAN1802/DTIS Video/Stn052/11-04-2022/20220411191258.m2ts, is: 052"

  assert_output --partial "Could not get station id for the file: ../test-data/2010-2019/Video/TAN0616/TAN0616_003/sth/sth/TAN1802_001.m2ts (file path matches no pattern, potential cruise ID mismatch)"

  # check some files passed the local verification
  run bash -c "cat plan.txt"
	assert_output --partial "../test-data/images/dir with space/TAN1802_Stn_160_001.jpg;160"
	assert_output --partial "../test-data/images/dir with space/TAN1802_160_DTIS__004.jpeg;160"
	assert_output --partial "../test-data/images/Tan1802_160/TAN1802_Stn_160_016.jpg;160"
	assert_output --partial "../test-data/images/Tan1802_160/TAN1802_Stn_160_001.jpg;160"
	assert_output --partial "../test-data/images/Tan1802_160/Tan1802_Stn_160_009.jpg;160"
	assert_output --partial "../test-data/images/Tan1802_160/TAN1802_Stn_160_002.jpeg;160"
  # no text files passed the local verification
	assert_output --partial "The following text files passed local verification:
FILE_PATH;STATION_ID
End of text files that passed local verification"
  # videos
	assert_output --partial "../test-data/2010-2019/Video/TAN1802/Stn003/1234.m2t;003"
	assert_output --partial "../test-data/2010-2019/Video/TAN1802/Stn003/12345.M2T;003"
	assert_output --partial "../test-data/2010-2019/Voyage 2022-2024/Video/TAN1802/DTIS Video/Stn052/11-04-2022/20220411191258.m2ts;052"
}

@test "cruise ID: TAN2203, different file matches" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='../test-data/images' && export NIWA_VIDEOS_DIR='../test-data/2010-2019' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && export NIWA_CRUISE_ID=TAN2203 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ../test-data/images for image files..."
  assert_output --partial "Checking ../test-data/2010-2019 for video files..."
  assert_output --partial "Checking ../test-data/text/TAN2203 for text files..."

  # contains cruise ID in file name, lower case letters
  assert_output --partial "Station ID, for the file: ../test-data/text/TAN2203/OFOP text files/tan2203_001_obser.txt, is: 001"
  assert_output --partial "Station ID, for the file: ../test-data/text/TAN2203/OFOP text files/tan2203_001_posi.txt, is: 001"
  assert_output --partial "Station ID, for the file: ../test-data/text/TAN2203/OFOP text files/tan2203_001_prot.txt, is: 001"
  # contains cruise ID in file name, upper case letters
  assert_output --partial "Station ID, for the file: ../test-data/text/TAN2203/OFOP text files/TAN2203_001_posi.txt, is: 001"
  # rerun, obser
  assert_output --partial "Station ID, for the file: ../test-data/text/TAN2203/OFOP text files/TAN2203_001.sth_rerun.sth_obser.txt, is: 001"
  assert_output --partial "Station ID, for the file: ../test-data/text/TAN2203/OFOP text files/TAN2203_001.sth_rerun.sth_prot.txt, is: 001"
  # an image
  assert_output --partial "Station ID, for the file: ../test-data/images/TAN2203_002/TAN2203_Stn_002_033.jpg, is: 002"
  # an image and file extension is all caps
  assert_output --partial "Station ID, for the file: ../test-data/images/Datasets/Voyage 2022-2024/Data/TAN2203/DTIS/DTIS Stills/TAN2203_002/TAN2203_002_001.JPG, is: 002"
  assert_output --partial "File does not match any pattern: tan1802_113_AcousticMarkWatercolumnshot_obser.txt"

  # check some files passed the local verification
  run bash -c "cat plan.txt"
  # no text files passed the local verification
	assert_output --partial "The following video files passed local verification:
FILE_PATH;STATION_ID
End of video files that passed local verification"
  # images
  assert_output --partial "../test-data/images/TAN2203_002/TAN2203_Stn_002_033.jpg;002"
  assert_output --partial "../test-data/images/Datasets/Voyage 2022-2024/Data/TAN2203/DTIS/DTIS Stills/TAN2203_002/TAN2203_002_001.JPG;002"
  # text files

  assert_output --partial "../test-data/text/TAN2203/OFOP text files/TAN2203_001.sth_rerun.sth_obser.txt;001"
  assert_output --partial "../test-data/text/TAN2203/OFOP text files/tan2203_001_obser.txt;001"
  assert_output --partial "../test-data/text/TAN2203/OFOP text files/tan2203_001_prot.txt;001"
  assert_output --partial "../test-data/text/TAN2203/OFOP text files/TAN2203_001.sth_rerun.sth_prot.txt;001"
  assert_output --partial "../test-data/text/TAN2203/OFOP text files/tan2203_034_prot.TXT;034"
  assert_output --partial "../test-data/text/TAN2203/OFOP text files/TAN2203_001_posi.txt;001"
  assert_output --partial "../test-data/text/TAN2203/OFOP text files/tan2203_001_posi.txt;001"
}

@test "cruise ID: TAN2203, ignore images and videos" {
  run bash -c "export NIWA_DRY_RUN='true' && export  NIWA_ENVIRONMENT='testing' && export NIWA_IMAGES_DIR='ignore' && export NIWA_VIDEOS_DIR='ignore' && export NIWA_OFOP_DIR=../test-data/text/TAN2203 && export NIWA_CRUISE_ID=TAN2203 && ../../data_upload.sh"
	assert_output --partial "Exit, because dry run is set"
  assert_output --partial "Checking ignore for image files..."
  assert_output --partial "Images directory was set to 'ignore', cancelling the check"
  assert_output --partial "Checking ignore for video files..."
  assert_output --partial "Videos directory was set to 'ignore', cancelling the check"
  assert_output --partial "Checking ../test-data/text/TAN2203 for text files..."

  # since we are ignoring all video and image files, t
  refute_output --partial "jpg"
  refute_output --partial "m2t"
  refute_output --partial "jpeg"
}
