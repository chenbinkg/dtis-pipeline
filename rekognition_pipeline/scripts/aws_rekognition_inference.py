import os
import json
import yaml
import boto3
import logging
import argparse
import tempfile
import traceback
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def start_model(client, project_arn, model_arn, version_name, min_unit, max_unit):
	"""
	Start a rekognition model for inference
	"""
	try:
		# Check model status
		describe_response = client.describe_project_versions(
			ProjectArn=project_arn,
			VersionNames=[version_name]
		)
		for model in describe_response['ProjectVersionDescriptions']:
			if model["Status"] == "RUNNING":
				logger.info(f"Model {version_name} is already running.")
				return

		# Start the model
		logger.info(f"Starting Model {version_name}")
		client.start_project_version(
			ProjectVersionArn=model_arn,
			MinInferenceUnits=min_unit,
			MaxInferenceUnits=max_unit
		)
		# Wait for the model to be in the running state
		project_version_running_waiter = client.get_waiter('project_version_running')
		project_version_running_waiter.wait(ProjectArn=project_arn, VersionNames=[version_name])

		# Get the running status
		describe_response = client.describe_project_versions(
			ProjectArn=project_arn,
			VersionNames=[version_name]
			)
		for model in describe_response['ProjectVersionDescriptions']:
			logger.info(f"Model {version_name} status is set to {model['Status']}")
	except ClientError as e:
		logger.error(f"Error starting model {version_name} - {e}")
	except Exception as e:
		logger.error(f"Error starting model {e}")


def stop_model(client, model_arn):
	"""
	Stop a rekognition model.
	"""
	try:
		response = client.stop_project_version(ProjectVersionArn=model_arn)
		logger.info(f"Model status set to: {response['Status']}")

	except Exception as e:
		logger.error(f"Error stopping rekognition model {model_arn} - {e}")


def run_inference_on_s3_dataset(client, cfg):
	"""
	Run Rekognition on an image dataset stored on S3

	:param client: Boto3 Rekognition client
	:param cfg: (dict) Configuration parameters
	"""

	try:
		# Connect to target bucket where dataset is stored
		s3 = boto3.client("s3")
		paginator = s3.get_paginator("list_objects_v2")
		pages = paginator.paginate(
			Bucket=cfg["dataset_bucket"],
			Prefix=cfg["dataset_folder"]
		)

		# Process images
		logger.info(f"Running inference on {cfg['dataset_folder']} ...")
		dataset_output = []
		for page in pages:
			for objs in page["Contents"]:
				file_obj = objs["Key"]
				# Only run inference on images
				if not (file_obj.endswith(".jpg") or file_obj.endswith(".png") or file_obj.endswith(".jpeg")):
					continue
				result = client.detect_custom_labels(
					Image={
						"S3Object": {
							"Bucket": cfg["dataset_bucket"],
							"Name": file_obj
						}
					},
					MinConfidence=cfg["min_confidence"],
					ProjectVersionArn=cfg["model_arn"]
				)
				json_output = construct_result_json(
					cfg["dataset_bucket"],
					file_obj,
					result["CustomLabels"]
				)
				if json_output:
					dataset_output.append(json_output)

		logger.info(f"Inference run complete for {cfg['dataset_folder']}")
		logger.info(f"Total files with detection: {len(dataset_output)}")
		return dataset_output

	except ClientError as e:
		logger.error(f"Error running inference on S3 dataset {e}")
		return None
	except Exception:
		logger.error(
			f"Error running inference on S3 dataset {cfg['dataset_folder']}"
		)
		logger.error(traceback.print_exc())
		return None

def construct_result_json(bucket, filename, results):
	"""
	Constructs the output of custom label into a json-formatted output
	"""
	# No objects detected
	if len(results) == 0:
		return None

	detections = []
	for detect in results:
		obj = dict()
		obj["Label"] = detect["Name"]
		obj["Confidence"] = detect["Confidence"]
		box = detect["Geometry"]["BoundingBox"]
		obj["left"] = box["Left"]
		obj["top"] = box["Top"]
		obj["width"] = box["Width"]
		obj["height"] = box["Height"]

		detections.append(obj)

	output = dict()
	output["file_ref"] = "s3://" + bucket + "/" + filename
	output["detections"] = detections

	return output

def save_detection_results(output, cfg):
	"""
	Save Custom Label output to file
	"""
	try:
		if output is None:
			logger.info("No output from Custom Label. No output file generated")
			return

		temp_dir = tempfile.gettempdir()
		local_file = os.path.join(temp_dir, cfg["output_file"])

		logger.info(f"Saving output to {local_file}")
		with open(local_file, "w") as outfile:
			outfile.writelines([json.dumps(obj) + "\n" for obj in output])
		logger.info("Output saved successfully.")

	except KeyError as e:
		logger.error(f"No key found in config file when saving annotations {e}")


if __name__ == "__main__":

	parser = argparse.ArgumentParser(
		description="Use trained rekognition model for inference"
	)
	parser.add_argument("-c", required=True, help="Config yaml file")
	args = parser.parse_args()

	try:
		with open(args.c) as cfg_file:
			cfg = yaml.load(cfg_file, Loader=yaml.FullLoader)

		# Check and set the min and max inference units
		if "min_inference_unit" in cfg:
			min_unit = int(cfg["min_inference_unit"])
		else:
			min_unit = 1
		if "max_inference_unit" in cfg:
			max_unit = int(cfg["max_inference_unit"])
		else:
			max_unit = 2

		# Connect to rekognition
		client = boto3.client('rekognition')

		# Start Rekognition model first
		start_model(
			client,
			cfg["project_arn"],
			cfg["model_arn"],
			cfg["model_version"],
			min_unit,
			max_unit
		)

		# Run inference on dataset uploaded on S3
		output = run_inference_on_s3_dataset(client, cfg)
		save_detection_results(output, cfg)

	except KeyError as e:
		logger.error(f"Missing parameters in config file: {e}")
	finally:
		# Stop model even if the script fails
		stop_model(client, cfg["model_arn"])
