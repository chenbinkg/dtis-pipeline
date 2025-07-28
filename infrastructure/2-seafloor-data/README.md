# 2-seafloor-data

The files in this directory create infrastructure resources (such as Amazon S3 buckets) for the Seafloor data.

This setup uses Terraform remote state, so it requires that code from the [1-terraform-init](1-terraform-init/) directory is run first.

## How to run this?

1. Make sure you are authenticated with the right AWS account. You might want to check it with `aws sts get-caller-identity`
2. Define environment variable, as either dev, test or prod, for example
```bash
export ENVIRONMENT=dev
```
3. Upload the MongoDB connection string to AWS Systems Manager using CLI as shown below
```bash
aws ssm put-parameter \
    --name "/dtis/mongodb/uri" \
    --value "mongodb+srv://username:password@cluster.example.mongodb.net" \
    --type "SecureString" \
    --description "MongoDB connection string" \
    --region ap-southeast-2

```
4. Download the lambda python dependencies, and package them with the lambda function code into a zip file, so that it is available for Terraform:
```bash
./tasks lambda_package
cp lambda/lambda_functions/ingress/lambda_function.zip infrastructure/2-seafloor-data/

Alternatively, please run the following at the main repo directory:
```
function_name="ingress" path_cwd="$PWD/lambda" runtime="python3" bash lambda/scripts/create_pkg.sh
function_name="media_convert" path_cwd="$PWD/lambda" runtime="python3" bash lambda/scripts/create_pkg.sh
function_name="pretrained_annotation" path_cwd="$PWD/lambda" runtime="python3" bash lambda/scripts/create_pkg.sh
```

```
if it doesn't work, create the lambda_funciton.zip manually:
```bash
cd processing
processing_dir=$(pwd)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
rm -f "${processing_dir}/lambda_function.zip"
cd "${processing_dir}/venv/lib/python3.9/site-packages/"
zip -r9 ${processing_dir}/lambda_function.zip .
cd ${processing_dir}
zip -g ${processing_dir}/lambda_function.zip lambda_function_mongoDB_schema.py
mv "${processing_dir}/lambda_function.zip" "$(dirname "${processing_dir}")/infrastructure/2-seafloor-data/"
```
For mediaconvert lambda package, please run the following command:
```bash
cd mediaconvert
processing_dir=$(pwd)
zip -r lambda_media_convert.zip lambda_function_media_convert.py
mv "${processing_dir}/lambda_media_convert.zip" "$(dirname "${processing_dir}")/infrastructure/2-seafloor-data/"
```

5. Run the following:

```bash
cd infrastructure/2-seafloor-data
export PROJECT_NAME=data-platform-dtis
export ENVIRONMENT=dev
export TF_VAR_environment=${ENVIRONMENT}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

terraform init -backend-config="bucket=${PROJECT_NAME}-${ENVIRONMENT}-${AWS_ACCOUNT_ID}-terraform-state" -backend-config="key=niwa-dtis-ofop/${ENVIRONMENT}/${ENVIRONMENT}.tfstate"

terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

You may want to run the commands directly from your laptop, or use a [Dojo](https://github.com/kudulab/dojo)-docker container.

## Cleanup

Similar to above, the Terraform commands are:
```bash
cd infrastructure/2-seafloor-data
export PROJECT_NAME=data-platform-dtis
export ENVIRONMENT=dev
export TF_VAR_environment=${ENVIRONMENT}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

terraform init -backend-config="bucket=${PROJECT_NAME}-${ENVIRONMENT}-${AWS_ACCOUNT_ID}-terraform-state" -backend-config="key=niwa-dtis-ofop/${ENVIRONMENT}/${ENVIRONMENT}.tfstate"

terraform plan -destroy -out=plan.tfplan
terraform apply plan.tfplan
```

## Cleanup Command Reserved for Old POC Infra in Current PROD Environment Account
```bash
export ENVIRONMENT=testing
export TF_VAR_environment=${ENVIRONMENT}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

terraform init -backend-config="bucket=niwa-dtis-ofop-data-${AWS_ACCOUNT_ID}-terraform-state" -backend-config="key=niwa-dtis-ofop/${ENVIRONMENT}/${ENVIRONMENT}.tfstate"

terraform plan -destroy -out=plan.tfplan
terraform apply plan.
```
