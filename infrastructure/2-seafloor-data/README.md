# 2-seafloor-data

The files in this directory create infrastructure resources (such as Amazon S3 buckets) for the Seafloor data.

This setup uses Terraform remote state, so it requires that code from the [1-terraform-init](1-terraform-init/) directory is run first.

## How to run this?

1. Make sure you are authenticated with the right AWS account. You might want to check it with `aws sts get-caller-identity`
2. Download the lambda python dependencies, and package them with the lambda function code into a zip file, so that it is available for Terraform:
```
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
```
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
```
cd mediaconvert
processing_dir=$(pwd)
zip -r lambda_media_convert.zip lambda_function_media_convert.py
mv "${processing_dir}/lambda_media_convert.zip" "$(dirname "${processing_dir}")/infrastructure/2-seafloor-data/"
```

3. Run the following:

```
cd infrastructure/2-seafloor-data

export NIWA_ENVIRONMENT=testing
export TF_VAR_environment=${NIWA_ENVIRONMENT}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

terraform init -backend-config="bucket=niwa-dtis-ofop-data-${AWS_ACCOUNT_ID}-terraform-state" -backend-config="key=niwa-dtis-ofop/${NIWA_ENVIRONMENT}/${NIWA_ENVIRONMENT}.tfstate"

terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

You may want to run the commands directly from your laptop, or use a [Dojo](https://github.com/kudulab/dojo)-docker container.

## Cleanup

Similar to above, the Terraform commands are:
```
export NIWA_ENVIRONMENT=testing
export TF_VAR_environment=${NIWA_ENVIRONMENT}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

terraform init -backend-config="bucket=niwa-dtis-ofop-data-${AWS_ACCOUNT_ID}-terraform-state" -backend-config="key=niwa-dtis-ofop/${NIWA_ENVIRONMENT}/${NIWA_ENVIRONMENT}.tfstate"

terraform plan -destroy -out=plan.tfplan
terraform apply plan.tfplan
```
