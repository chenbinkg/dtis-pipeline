import yaml
import argparse
import logging
import boto3

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def create_project(rek_client, project_name):
	"""
	Creates an Amazon Rekognition Custom Labels project
	:param rek_client: The Amazon Rekognition Custom Labels Boto3 client.
	:param project_name: A name for the new prooject.
	"""

	try:
		# Create the project.
		logger.info("Creating project: %s", project_name)

		response = rek_client.create_project(ProjectName=project_name)

		logger.info("project ARN: %s", response['ProjectArn'])

		return response['ProjectArn']


	except ClientError as err:
		logger.exception("Couldn't create project - %s: %s", project_name, err.response['Error']['Message'])
		raise


if __name__ == "__main__":

	parser = argparse.ArgumentParser(
		description="Script to create a new project for AWS Rekognition"
		            "Custom Label service"
	)
	parser.add_argument("-c", required=True, help="config yaml file")
	args = parser.parse_args()

	try:
		with open(args.c) as cfg_file:
			cfg = yaml.load(cfg_file, Loader=yaml.FullLoader)

		session = boto3.Session(profile_name=cfg["boto_profile"])
		rekognition_client = session.client("rekognition")

		project_arn = create_project(
			rekognition_client,
			cfg["project_name"]
		)

		print(f"Finished creating project: {cfg['project_name']}")
		print(f"ARN: {project_arn}")

	except ClientError as err:
		logger.exception("Problem creating project: %s", err)
		print(f"Problem creating project: {err}")

