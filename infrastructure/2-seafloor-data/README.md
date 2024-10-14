# 2-seafloor-data

The files in this directory create infrastructure resources (such as Amazon S3 buckets) for the Seafloor data.

This setup uses Terraform remote state, so it requires that code from the [1-terraform-init](1-terraform-init/) directory is run first.

## How to run this?

1. Make sure you are authenticated with the right AWS account. You might want to check it with `aws sts get-caller-identity`
2. Run the following:
```
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
