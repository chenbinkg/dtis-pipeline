# DTIS Data Upload Application

This application was written to upload the data from local or network drive (`R:`) to aws cloud,
and is specifically catered to dtis (deep-sea towed imaging system) data.

## DTIS Data Upload Inputs Test

To run this application, make sure you have following inputs ready:
1. **cruise_id**: the cruise id this data collection belongs to, e.g. `TAN2009`
2. **image_dir**: the main image directory for this cruise, e.g. `R:\National\Datasets\Voyage 2019-2021\Video\TAN2009\TAN2009_DTIS stills`
3. **video_dir**: the main video directory for this cruise, e.g. `R:\National\Datasets\Voyage 2019-2021\Video\TAN2009\TAN2009_DTIS_video`
4. **ofop_dir**: the main ofop directory for this cruise, e.g. `R:\National\Datasets\Voyage 2019-2021\Data\TAN2009\TAN2009_OFOP\TAN2009_OFOP_prot`
Note that at least one of the image, video and ofop directory inputs has to be non-empty for the application to work.
If any of the directories are empty, simple press `ENTER` to skip the input.
5. **environment**: accepts both `testing` and `production` inputs, data will be uploaded to either testing or production databases
6. **dry_run**: set this to "true" if you only want to test the application, set this to `false` if you want to directly upload to S3.
Note that, by setting dry_run to `true`, the application will still prompt you for data upload later after directories are scanned. If you set dry_run to `false`, make sure you have aws credentials available, including `aws_access_key_id` (compulsory), `aws_secret_access_key` (compulsory) and `aws_session_token` (optional). 
You can obtain your aws credentials at the Access Portal: `https://d-97674a7caa.awsapps.com/start/#/?tab=accounts`
Please take note that the credentials you obtained from Access Portal expires in `24`hours. If the upload process takes more than `24`hours, it will fail after the session expires.

## AWS Credentials

This application does provide multiple ways to authenticate your aws credentials, depending on your preferences. Key in `1`, `2`, or `3` according to descriptions below when you are prompted.
1. **by Environment Variables**: the application will automatically grab your AWS credentials from the environment variables, so make sure you set your environment variables before running this application, including `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN`. 
2. **by AWS profile**: if you have already set up your AWS profile using AWS CLI in your machine, just have to enter your profile name here, the application will grab your AWS credentials from your profile. You can list your profiles by running following commands in your terminal: 
```aws configure list```, or ```aws configure list-profiles```.
3. **by Inputting AWS Credentials**: obtain your Access Key ID, Secret Access Key and Session Token from Access Portal as mentioned earlier or from your AWS administrator if you don't want your session to expire.





If you encounter any problems, please raise a IT service ticket directing to Data Platform team or Bryce Chen.





