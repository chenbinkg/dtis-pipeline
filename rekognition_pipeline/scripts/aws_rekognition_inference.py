import io
import os
import json
import yaml
import boto3
import logging
import argparse
import datetime
import tempfile
import traceback
import pandas as pd
from PIL import Image
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def construct_result_json(s3, bucket, filename, results, label_map):
	"""
	Constructs the output of custom label into a json-formatted output
	"""
	# No objects detected
	if len(results) == 0:
		raise ValueError("No detection found")

	annotations = []
	confidence = []
	class_map_obj = dict()
	for detect in results:
		obj = dict()
		conf = dict()

		# Get class id and mapping info first
		id_value = label_map[detect["Name"]]
		obj["class_id"] = id_value
		class_map_obj[str(id_value)] = detect["Name"]

		conf["confidence"] = float(detect["Confidence"])
		box = detect["Geometry"]["BoundingBox"]
		obj["top"] = box["Top"]
		obj["left"] = box["Left"]
		obj["height"] = box["Height"]
		obj["width"] = box["Width"]

		annotations.append(obj)
		confidence.append(conf)

	# Double check to make sure there are objects detected
	if len(annotations) == 0:
		raise ValueError("No detection found")

	# Assemble the resulting SageMaker format json file
	output = dict()
	output["source-ref"] = "s3://" + bucket + "/" + filename
	# annotations
	output["bounding-box"] = dict()
	output["bounding-box"]["image_size"] = [get_img_metadata(s3, cfg, filename)]
	output["bounding-box"]["annotations"] = annotations
	# annotation metadata
	output["bounding-box-metadata"] = dict()
	output["bounding-box-metadata"]["objects"] = confidence
	output["bounding-box-metadata"]["class-map"] = class_map_obj
	output["bounding-box-metadata"]["type"] = "groundtruth/object-detection"
	output["bounding-box-metadata"]["human-annotated"] = "no"
	output["bounding-box-metadata"]["creation-date"] = str(datetime.datetime.now())
	output["bounding-box-metadata"]["job-name"] = "labeling-job/rekognition"

	return output

def get_img_metadata(s3, cfg, filename):
	"""
	Get metadata of image stored on S3
	"""
	# Get file content from S3
	content = s3.get_object(
		Bucket=cfg["dataset_bucket"],
		Key=filename
	)
	stream = io.BytesIO(content["Body"].read())
	img = Image.open(stream)

	img_meta = dict()
	img_width, img_height = img.size
	img_meta["width"] = img_width
	img_meta["height"] = img_height
	img_meta["depth"] = 3

	return img_meta

def retrieve_label_mapping(cfg):
	"""
	Retrieve label to class id mapping information.
	Current approach is to read mapping from local. Future, to transit to
	retrieving info from mongoDB.
	"""
	try:
		# Note, this is technically a label to class id mapping
		df = pd.read_csv(cfg["class_mapping_file"])
		return dict(zip(df["name"], df["id"]))
	except KeyError:
		logger.error(
			f"Error accessing class mapping file. 'class_mapping_file'"
			f" missing from config file."
		)
		logger.error(traceback.print_exc())
		exit()
	except FileNotFoundError:
		logger.error(
			f"Class mapping file {cfg['class_mapping_file']} "
			f"not found."
		)
		logger.error(traceback.print_exc())
		exit()
	except Exception:
		logger.error(
			f"Error processing class mapping file. Aborting inference run ..."
		)
		logger.error(traceback.print_exc())
		exit()

def run_inference_on_s3_dataset(client, cfg, label_map):
	"""
	Run Rekognition on an image dataset stored on S3

	:param client: Boto3 Rekognition client
	:param cfg: (dict) Configuration parameters
	:param label_map: (dict) label to class id mapping data structure
	"""

	try:
		# Error check - make sure dataset folder does not end with a '/'
		if cfg["dataset_folder"].endswith("/"):
			cfg["dataset_folder"] = cfg["dataset_folder"][:-1]

		# Connect to target bucket where dataset is stored
		s3 = boto3.client("s3")
		paginator = s3.get_paginator("list_objects_v2")
		pages = paginator.paginate(
			Bucket=cfg["dataset_bucket"],
			Prefix=cfg["dataset_folder"]
		)

		# For saving output to file use
		dataset_path = cfg["dataset_folder"].split("/")
		dataset_path = "/".join(dataset_path[:-1])
		dataset_path = dataset_path + "/" + cfg["output_folder"]

		# Process images
		logger.info(f"Running inference on {cfg['dataset_folder']} ...")
		dataset_output = []

		page_no = 0
		for page in pages:
			count = 0
			page_no += 1
			for objs in page["Contents"]:
				count += 1
				logger.info(
					f"Progress: {count}/{len(page['Contents'])} images in "
					f"page {page_no}"
				)
				file_obj = objs["Key"]
				# Only run inference on images
				if not (file_obj.endswith(".jpg") or file_obj.endswith(".png") or file_obj.endswith(".jpeg")):
					continue

				# run inference on a single image
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

				# construct output into json file for each image
				try:
					json_output = construct_result_json(
						s3,
						cfg["dataset_bucket"],
						file_obj,
						result["CustomLabels"],
						label_map
					)

					# save output to a json file
					save_detection_results(
						s3,
						json_output,
						cfg["dataset_bucket"],
						dataset_path,
						file_obj
					)
				except ValueError as e:
					logger.info(f"Skipping {file_obj} - {e}")
					continue

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

def save_detection_results(s3, output, bucket, path, filename):
	"""
	Save Custom Label output to file and upload to S3
	"""
	try:
		# Save file to local first
		temp_dir = tempfile.gettempdir()
		fname = filename.split("/")[-1]

		# Make sure we only remove the file suffix
		fname = fname.split(".")
		fname = ".".join(fname[:-1])
		fname = fname + ".json"

		local_file = os.path.join(temp_dir, fname)
		logger.info(f"Saving output to {local_file}")

		with open(local_file, "w") as outfile:
			outfile.writelines(json.dumps(output))

		# Upload file to S3
		s3_file = path + "/" + fname
		s3.upload_file(local_file, bucket, s3_file)
		# os.remove(local_file)
		logger.info(f"results saved to {local_file}")
	except KeyError as e:
		logger.error(f"No key found in config file when saving annotations {e}")

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

		# To avoid starting the model for a fail run, retrieve class map first
		label_map = retrieve_label_mapping(cfg)

		start_time = datetime.datetime.now()
		# Start Rekognition model first
		start_model(
			client,
			cfg["project_arn"],
			cfg["model_arn"],
			cfg["model_version"],
			min_unit,
			max_unit
		)
		logger.info(f"Starting model - {datetime.datetime.now() - start_time} seconds")
		# Run inference on dataset uploaded on S3
		output = run_inference_on_s3_dataset(client, cfg, label_map)
		# save_detection_results(s3, output, cfg["dataset_bucket"], path, fi)
		logger.info(f"Inference complete in - {datetime.datetime.now() - start_time} seconds")
	except KeyError as e:
		logger.error(f"Missing parameters in config file: {e}")
	finally:
		# Stop model even if the script fails
		stop_model(client, cfg["model_arn"])
