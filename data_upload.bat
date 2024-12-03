@echo off

:: Prompt for inputs
set /p NIWA_DRY_RUN="Enter NIWA_DRY_RUN (true/false): "
set /p NIWA_ENVIRONMENT="Enter NIWA_ENVIRONMENT (testing/production): "
set /p NIWA_CRUISE_ID="Enter NIWA_CRUISE_ID: "
set /p NIWA_IMAGES_DIR="Enter NIWA_IMAGES_DIR: "
set /p NIWA_VIDEOS_DIR="Enter NIWA_VIDEOS_DIR: "
set /p NIWA_OFOP_DIR="Enter NIWA_OFOP_DIR: "

:: Pass inputs to the shell script
wsl bash -c "NIWA_DRY_RUN=%NIWA_DRY_RUN% NIWA_ENVIRONMENT=%NIWA_ENVIRONMENT% NIWA_CRUISE_ID=%NIWA_CRUISE_ID% NIWA_IMAGES_DIR='%NIWA_IMAGES_DIR%' NIWA_VIDEOS_DIR='%NIWA_VIDEOS_DIR%' NIWA_OFOP_DIR='%NIWA_OFOP_DIR%' ./upload/data_upload.sh"
