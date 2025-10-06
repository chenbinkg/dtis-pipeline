# How to Run Annotation Using Pre-trained 

## Create Project Structure
1. `cd annotation`
2. `mkdir code`
3. `cd code`
4. `mkdir docker`

## Build an Virtual Environment with All Necessary Packages
1. `cd docker`
2. `python -m venv venv`
3. `source venv/bin/activate`
4. `pip install ...`
5. test the environment using your inference.py
6. `pip freeze > requirements.txt`
7. clean up by `rm -r venv`

## Build Docker Image using AWS ECR
1. create an virtual environment, turned on docker in your PC
2. run `pip install docker`
3. run `cd annotation`
4. run `./docker_buildx.sh data-platform-dtis {environment} ap-southeast-2`

## Test Docker with entrypoint.sh
1. have awscli installed in your virtual environment
2. run `aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin {aws_account_id}.dkr.ecr.ap-southeast-2.amazonaws.com`
e.g `aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 851725470721.dkr.ecr.ap-southeast-2.amazonaws.com`
3. check ECR repo:
```bash
aws ecr describe-repositories --region ap-southeast-2
```
4. run `docker pull {aws_account_id}.dkr.ecr.ap-southeast-2.amazonaws.com/data-platform-dtis-{environment}-annotation:latest`
e.g. `docker pull 851725470721.dkr.ecr.ap-southeast-2.amazonaws.com/data-platform-dtis-prod-annotation:latest`
5. run 
```bash
docker run -it \
 -e AWS_ACCESS_KEY_ID="{your_access_key_id}" \
 -e AWS_SECRET_ACCESS_KEY="{your_secret_access_key}" \
 -e AWS_REGION="ap-southeast-2" \
 -e MODEL_S3_URI="s3://data-platform-dtis-prod-851725470721-model-data/models/RF-DETR/checkpoint_best_regular.pth" \
  {aws_account_id}.dkr.ecr.ap-southeast-2.amazonaws.com/data-platform-dtis-{environment}-annotation /bin/bash
```
6. run `python`
7. try to import libraries going to be used in the inference.py using `import ... `, check any errors

## Upload Credential and Secrets to AWS
```bash
aws secretsmanager create-secret \
    --name "aws-credentials/biigle/create-user-disk" \
    --description "AWS Access Key ID and Secret Access Key for my application" \
    --secret-string '{"access_key_id":"XXXXXXXXXXXXXXX","secret_access_key":"XXXXXXXXXXXXXX”}’
```

## Retrieve Secrets
```bash
aws secretsmanager get-secret-value --secret-id "aws-credentials/biigle/create-user-disk" --region ap-southeast-2
```

## Create Pipeline
1. run `cd annotation`
2. run `python sagemaker_create_pipeline.py`