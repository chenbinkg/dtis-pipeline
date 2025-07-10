import time
import json
import yaml
import boto3
import argparse
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def create_dataset(rek_client, cfg):
	"""
	Creates an Amazon Rekognition Custom Labels dataset.
	:param rek_client: The Amazon Rekognition Custom Labels Boto3 client.
	:param cfg: (dict) Configuration paramteres
	"""

	try:
		# Create the project
		dataset_type = cfg["dataset_type"]
		project_arn = cfg["project_arn"]
		bucket = cfg["manifest_bucket"]
		if not cfg["dst_s3_folder"].endswith("/"):
			dst_folder = cfg["dst_s3_folder"] + "/"
		else:
			dst_folder = cfg["dst_s3_folder"]
		manifest_file = dst_folder + cfg["manifest_file"]

		logger.info("Creating %s dataset for project %s", dataset_type, project_arn)

		dataset_type = dataset_type.upper()
		dataset_source = json.loads(
			'{ "GroundTruthManifest": { "S3Object": { "Bucket": "'
			+ bucket
			+ '", "Name": "'
			+ manifest_file
			+ '" } } }'
		)

		response = rek_client.create_dataset(
			ProjectArn=project_arn, DatasetType=dataset_type, DatasetSource=dataset_source
		)

		dataset_arn = response['DatasetArn']
		logger.info("dataset ARN: %s", dataset_arn)

		finished = False
		while finished is False:

			dataset = rek_client.describe_dataset(DatasetArn=dataset_arn)

			status = dataset['DatasetDescription']['Status']

			if status == "CREATE_IN_PROGRESS":
				logger.info("Creating dataset: %s ", dataset_arn)
				time.sleep(5)
				continue

			if status == "CREATE_COMPLETE":
				logger.info("Dataset created: %s", dataset_arn)
				finished = True
				continue

			if status == "CREATE_FAILED":
				error_message = f"Dataset creation failed: {status} : {dataset_arn}"
				logger.exception(error_message)
				raise Exception(error_message)

			error_message = f"Failed. Unexpected state for dataset creation: {status} : {dataset_arn}"
			logger.exception(error_message)
			raise Exception(error_message)

		return dataset_arn


	except ClientError as err:
		logger.exception("Couldn't create dataset: %s", err.response['Error']['Message'])
		raise


if __name__ == "__main__":

	parser = argparse.ArgumentParser(
		description="Script for creating a dataset for model training on AWS Rekognition "
		            "Custom Label service"
	)
	parser.add_argument("-c", required=True, help="Training config yaml file")
	args = parser.parse_args()

	try:

		with open(args.c) as cfg_file:
			cfg = yaml.load(cfg_file, Loader=yaml.FullLoader)

		session = boto3.Session(profile_name=cfg["boto_profile"])
		rekognition_client = session.client("rekognition")

		dataset_arn = create_dataset(rekognition_client, cfg)
		print(f"Finished creating dataset: {dataset_arn}")

	except ClientError as err:
		logger.exception("Problem creating dataset: %s", err)
