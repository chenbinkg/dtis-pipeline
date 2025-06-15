import json
import yaml
import argparse

if __name__ == "__main__":

	parser = argparse.ArgumentParser(
		description="Script to fix BIGGLE generated manifest files"
	)
	parser.add_argument("-c", required=True, help="yaml config file")

	args = parser.parse_args()


	try:
		# Load config file
		with open(args.c) as cfg_file:
			cfg = yaml.load(cfg_file, Loader=yaml.FullLoader)

		obj_list = []
		# Note: This will work only for S3 or Unix paths.
		new_path = cfg["img_path"] if cfg["img_path"].endswith("/") else cfg["img_path"] + "/"

		# Check if we need to cherry-pick labels from main manifest file
		filter_labels = None
		if "use_only_labels" in cfg:
			filter_labels = cfg["use_only_labels"].split(",")

		# Load target file
		with open(cfg["manifest_file"]) as json_data:
			# Rekognition/Sagemaker manifest files contain multiple json objects
			# We have to read each line and convert each object individually
			print("Processing input manifest file")
			for json_obj in json_data:
				ann = json.loads(json_obj)

				# Fix S3 bucket path
				p = ann["source-ref"].split("/")[-1]
				ann["source-ref"] = new_path + p

				# Fix issue with metadata type not set to object-detection
				meta_key_list = list(ann.keys())
				meta_key = None
				for k in meta_key_list:
					if k.endswith("-metadata"):
						meta_key = k
				# Skip if no type attribute
				if meta_key is None:
					obj_list.append(ann)
					continue

				# Replace annotation type value
				ann[meta_key]["type"] = "groundtruth/object-detection"

				# Check if need to discard annotation
				if filter_labels:
					class_map = ann[meta_key]["class-map"]
					class_keys = class_map.keys()
					for k in class_keys:
						if class_map[k] in filter_labels:
							obj_list.append(ann)
							continue
				else:
					obj_list.append(ann)

		print("Saving output to new manifest file")
		with open(cfg["output_file"], "w") as outfile:
			outfile.writelines([json.dumps(obj) + "\n" for obj in obj_list])

	except FileNotFoundError as e:
		print(f"Error opening file {e}. Check settings file.")
	except KeyError as e:
		print(f"Error reading config file {e}")