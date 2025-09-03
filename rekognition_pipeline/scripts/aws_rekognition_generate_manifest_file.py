import os
import json
import yaml
import boto3
import logging
import tempfile
import argparse

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def read_annotation_files(cfg):
	"""
	Scan for list of annotation files from given path
	"""
	source_bucket = cfg["manifest_bucket"]
	annotation_folder = cfg["annotation_source_folder"]

	# Connect to S3 bucket
	s3 = boto3.client("s3")
	# Use Paginator to overcome the 1000 object retrieval limit on S3 SDK
	paginator = s3.get_paginator("list_objects_v2")
	pages = paginator.paginate(Bucket=source_bucket, Prefix=annotation_folder)
	logger.info(
		f"Successfully connected to annotation folder on S3: "
		f"{source_bucket + '/' + annotation_folder}"
	)

	annotation_list = []
	for page in pages:
		for objs in page["Contents"]:
			file_obj = s3.get_object(Bucket=source_bucket, Key=objs["Key"])
			entry = file_obj["Body"].read().decode('UTF-8')
			json_obj = json.loads(entry)

			try:
				# Check annotation structure conforms to SageMaker's requirements
				annotation = fix_source_ref(json_obj, cfg)
				annotation = check_bounding_box(annotation)
				annotation = check_class_mapping(annotation)
			except ValueError as e:
				logger.exception(
					f"Error found in annotation file: {json_obj['source-ref']}"
					f"- {e}"
				)

			# Check if need to filter away labels
			if "filter_labels" in cfg:
				filter_labels = cfg["filter_labels"]
				class_map = annotation["bounding-box-metadata"]["class-map"]
				for k in class_map.keys():
					if class_map[k] in filter_labels:
						annotation_list.append(annotation)
						break
			else:
				annotation_list.append(annotation)


	logger.info(
		f"Total of {len(annotation_list)} annotation files read from "
		f"S3 bucket ..."
	)
	return annotation_list

def fix_source_ref(entry, cfg):
	"""
	Fix a single json entry's source-ref path

	:param entry: json structured annotation entry
	:param cfg: configuration dict
	"""

	new_path = cfg["img_path"]
	new_path = new_path if new_path.endswith("/") else new_path + "/"

	# Read json structure and replace path in source-ref accordingly
	p = entry["source-ref"].split("/")[-1]
	entry["source-ref"] = new_path + p

	return entry

def check_bounding_box(entry):
	"""
	Make sure that class id is int
	"""

	img_width = entry["bounding-box"]["image_size"][0]["width"]
	img_height = entry["bounding-box"]["image_size"][0]["height"]

	for e in entry["bounding-box"]["annotations"]:
		e["class_id"] = int(e["class_id"])
		top = check_box_coord(e["top"])
		left = check_box_coord(e["left"])
		height = check_box_coord(e["height"])
		width = check_box_coord(e["width"])

		# Make sure that the bounding box does not exceed dimensions of image
		bb_right = left + width
		bb_bottom = top + height

		if bb_right > img_width:
			width -= (bb_right - img_width)

		if bb_bottom > img_height:
			height -= (bb_bottom - img_height)

		# Save checked bbox coordinates
		e["top"] = top
		e["left"] = left
		e["height"] = height
		e["width"] = width

	return entry

def check_box_coord(value):
	"""
	Check to make sure box coordinates is positive int
	"""

	value = float(value)
	if value < 0:
		value = 0.0
	return value

def check_class_mapping(entry):
	"""
	Fix potential error in class mapping
	"""
	# Ensure no decimal points in class map key
	old_class_map = entry["bounding-box-metadata"]["class-map"]
	new_class_map = dict()
	old_keys = list(old_class_map.keys())

	for k in old_keys:
		checked_key = k.split(".")[0]
		new_class_map[checked_key] = old_class_map[k]
	entry["bounding-box-metadata"]["class-map"] = new_class_map

	return entry

def save_annotations(annotations, cfg, save_aws=True):
	"""
	Save annotations to a local temp file

	:param annotations: (List) List of json annotations
	:param cfg: (dict) Configuration parameters
	:param save_aws: (bool) Flag to determine to upload annotation to S3
	"""

	try:
		temp_dir = tempfile.gettempdir()
		local_file = os.path.join(temp_dir, cfg["manifest_file"])

		with open(local_file, "w") as outfile:
			outfile.writelines([json.dumps(obj) + "\n" for obj in annotations])

		logger.info(f"Manifest file successfully saved locally to {local_file}")

		# Only save if destination folder and flag are set
		if "dst_s3_folder" in cfg and save_aws:
			client = boto3.client("s3")
			if not cfg["dst_s3_folder"].endswith("/"):
				dst_folder = cfg["dst_s3_folder"] + "/"
			else:
				dst_folder = cfg["dst_s3_folder"]
			dst_s3_file = dst_folder + cfg["manifest_file"]
			client.upload_file(
				local_file,
				cfg["manifest_bucket"],
				dst_s3_file
			)
			os.remove(local_file)
			logger.info(
				f"Manifest file successfully saved to S3 at "
				f"{cfg['manifest_bucket'] + '/' + dst_s3_file}"
			)

	except KeyError as e:
		logger.exception(
			f"No key found in config file when saving annotations to local: {e}"
		)
	except ClientError as e:
		logger.exception(f"Error uploading manifest file to S3 bucket {e}")


if __name__ == "__main__":

	parser = argparse.ArgumentParser(
		description="Script to generate SageMaker GroundTruth format Dataset"
		            "Manifest file for model training"
	)
	parser.add_argument("-c", required=True, help="yaml config file")
	args = parser.parse_args()

	try:
		# Load config file
		with open(args.c) as cfg_file:
			cfg = yaml.load(cfg_file, Loader=yaml.FullLoader)

		annotations = read_annotation_files(cfg)
		save_annotations(annotations, cfg)

	except FileNotFoundError as e:
		logger.exception(f"Error opening file {e}. Check settings file.")
	except KeyError as e:
		logger.exception(f"Error reading config file {e}")
	except ClientError as e:
		logger.exception(f"Error encountered creating manifest file: {e}")

