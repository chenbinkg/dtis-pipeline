import yaml
import json
import boto3
import logging
import argparse

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def train_model(rek_client, project_arn, version_name, output_bucket, output_folder, tag_key, tag_key_value):
	"""
	Trains an Amazon Rekognition Custom Labels model.
	:param rek_client: The Amazon Rekognition Custom Labels Boto3 client.
	:param project_arn: The ARN of the project in which you want to train a model.
	:param version_name: A version for the model.
	:param output_bucket: The S3 bucket that hosts training output.
	:param output_folder: The path for the training output within output_bucket
	:param tag_key: The name of a tag to attach to the model. Pass None to exclude
	:param tag_key_value: The value of the tag. Pass None to exclude

	"""

	try:
		# Train the model

		status = ""
		logger.info(
			"training model version %s for project %s",
			version_name, project_arn
			)

		output_config = json.loads(
			'{"S3Bucket": "'
			+ output_bucket
			+ '", "S3KeyPrefix": "'
			+ output_folder
			+ '" }  '
		)

		tags = {}

		if tag_key is not None and tag_key_value is not None:
			tags = json.loads(
				'{"' + tag_key + '":"' + tag_key_value + '"}'
			)

		response = rek_client.create_project_version(
			ProjectArn=project_arn,
			VersionName=version_name,
			OutputConfig=output_config,
			Tags=tags
		)

		logger.info("Started training: %s", response['ProjectVersionArn'])

		# Wait for the project version training to complete.

		project_version_training_completed_waiter = rek_client.get_waiter('project_version_training_completed')
		project_version_training_completed_waiter.wait(
			ProjectArn=project_arn,
			VersionNames=[version_name]
			)

		# Get the completion status.
		describe_response = rek_client.describe_project_versions(
			ProjectArn=project_arn,
			VersionNames=[version_name]
			)
		for model in describe_response['ProjectVersionDescriptions']:
			logger.info("Status: %s", model['Status'])
			logger.info("Message: %s", model['StatusMessage'])
			status = model['Status']

		logger.info("finished training")

		return response['ProjectVersionArn'], status

	except ClientError as err:
		logger.exception("Couldn't create model: %s", err.response['Error']['Message'])
		raise


if __name__ == "__main__":
	parser = argparse.ArgumentParser(
		description="Train a object detection model using AWS Rekognition "
		            "Custom Label service"
	)
	parser.add_argument("-c", required=True, help="Training config yaml file")
	args = parser.parse_args()

	try:
		with open(args.c) as cfg_file:
			cfg = yaml.load(cfg_file, Loader=yaml.FullLoader)

		# Train the model.
		session = boto3.Session(profile_name=cfg["boto_profile"])
		rekognition_client = session.client("rekognition")

		print(f"Training model version {cfg['version_name']} for project {cfg['project_arn']}")
		tag_name = cfg["tag_name"] if "tag_name" in cfg else None
		tag_value = cfg["tag_value"] if "tag_value" in cfg else None

		model_arn, status = train_model(
			rekognition_client,
			cfg["project_arn"],
			cfg["version_name"],
			cfg["model_output_bucket"],
			cfg["model_output_folder"],
			tag_name,
			tag_value
		)

		print(f"Finished training model: {model_arn}")
		print(f"Status: {status}")


	except ClientError as err:
		logger.exception("Problem training model: %s", err)
		print(f"Problem training model: {err}")
	except Exception as err:
		logger.exception("Problem training model: %s", err)
		print(f"Problem training model: {err}")
