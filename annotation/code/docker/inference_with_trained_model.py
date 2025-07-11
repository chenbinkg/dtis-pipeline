import os
import json
import time
import boto3
import logging
import argparse
import datetime
import traceback
import pandas as pd
from PIL import Image
from pymongo.mongo_client import MongoClient
from botocore.exceptions import ClientError

_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class MongoDBOps:

    def __init__(self, read_secondary=False):
        self.user = "niwa-admin"
        self.password = "12345"
        if read_secondary:
            # read from secondary node to reduce CPU 
            self.conn_string = f"mongodb+srv://{self.user}:{self.password}@serverlessinstance0.ta8golw.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0?readPreference=secondary"
        else:
            self.conn_string = f"mongodb+srv://{self.user}:{self.password}@serverlessinstance0.ta8golw.mongodb.net"
        # self.client = MongoClient(self.conn_string)

    def read_to_df(self, db_name, collection_name, query_filter, column_filter):
        client = MongoClient(self.conn_string)
        coll = client[db_name][collection_name]
        mydoc = coll.find(query_filter, column_filter)
        df =  pd.DataFrame(list(mydoc))
        # df['obs_date'] = pd.to_datetime(df["obs_date"])  
        # df.set_index('obs_date')
        if "_id" in df.columns:
            df = df.drop('_id', axis=1)
        client.close()
        return df
    
    def gen_query_filter(self, columns, values):
        '''Generate query filter conditions'''
        query_filter = {}
        for col, val in zip(columns, values):
            query_filter[col] = val
        _logger.info(f"query_filter: {query_filter}")
        return query_filter

    def gen_column_filter(self, columns):
        '''Generate column filter in the following format:
        {col1: 1, col2: 1, col3: 1, col3: 1, col4: 1}
        '''
        column_filter = {}
        for col in columns:
            column_filter[col] = 1
        _logger.info(f"column_filter: {column_filter}")
        return column_filter

def construct_result_json(image, s3_input_uri, filename, results, label_map):
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
	output["source-ref"] = s3_input_uri + filename
	# annotations
	output["bounding-box"] = dict()
	output["bounding-box"]["image_size"] = [{"width": image.width, "height": image.height, "depth": 3}]
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


def retrieve_label_mapping(db_name, master_collection):
	"""
	Retrieve label to class id mapping information.
	Current approach is to read mapping from local. Future, to transit to
	retrieving info from mongoDB.
	"""
	# Note, this is technically a label to class id mapping
	# generate query from MongoDB (dtis_master) for labels		
	try:
		mongo_ops = MongoDBOps()
		columns = ["Observation_2", "Category", "biigle_tree_id"]
		query_cols = ["Category"]
		query_vals = ["Fish"]
		query_filter = mongo_ops.gen_query_filter(columns=query_cols, values=query_vals)
		column_filter = mongo_ops.gen_column_filter(columns=columns)
		df_master_fish = mongo_ops.read_to_df(
            db_name=db_name, 
            collection_name=master_collection, 
            query_filter=query_filter, 
            column_filter=column_filter
        )
		query_cols = ["Category"]
		query_vals = ["Invertebrate"]
		query_filter = mongo_ops.gen_query_filter(columns=query_cols, values=query_vals)
		column_filter = mongo_ops.gen_column_filter(columns=columns)
		df_master_invert = mongo_ops.read_to_df(
            db_name=db_name, 
            collection_name=master_collection, 
            query_filter=query_filter, 
            column_filter=column_filter
        )
		df = pd.concat([df_master_fish, df_master_invert], axis=0)
		df.rename(columns={"Observation_2": "name", "biigle_tree_id": "id"}, inplace=True)
		return dict(zip(df["name"], df["id"]))
	
	except KeyError:
		_logger.error(
			f"Error accessing class mapping file. 'class_mapping_file'"
			f" missing from config file."
		)
		_logger.error(traceback.print_exc())
		exit()
	except FileNotFoundError:
		_logger.error(
			f"Class mapping file {cfg['class_mapping_file']} "
			f"not found."
		)
		_logger.error(traceback.print_exc())
		exit()
	except Exception:
		_logger.error(
			f"Error processing class mapping file. Aborting inference run ..."
		)
		_logger.error(traceback.print_exc())
		exit()
		
def process_image(
		image_path, 
		output_path, 
		client, 
		s3_input_uri, 
		file, 
		label_map,
		min_confidence,
		model_arn
		):
    """Process a single image with the Rekognition model."""
    
    image = Image.open(image_path)
	# run inference on a single image
    result = client.detect_custom_labels(
        Image=image,
        MinConfidence=min_confidence,
        ProjectVersionArn=model_arn
    )
	
    json_output = construct_result_json(
						image,
						s3_input_uri,
						file,
						result["CustomLabels"],
						label_map
					)
    # Save results
    with open(output_path, 'w') as f:
        json.dump(json_output, f)
    
    return result["CustomLabels"]

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
				_logger.info(f"Model {version_name} is already running.")
				return

		# Start the model
		_logger.info(f"Starting Model {version_name}")
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
			_logger.info(f"Model {version_name} status is set to {model['Status']}")
	except ClientError as e:
		_logger.error(f"Error starting model {version_name} - {e}")
	except Exception as e:
		_logger.error(f"Error starting model {e}")

def stop_model(client, model_arn):
	"""
	Stop a rekognition model.
	"""
	try:
		response = client.stop_project_version(ProjectVersionArn=model_arn)
		_logger.info(f"Model status set to: {response['Status']}")

	except Exception as e:
		_logger.error(f"Error stopping rekognition model {model_arn} - {e}")

def main(
		s3_input_uri, 
		db_name, 
		master_collection_name, 
		project_arn, 
		model_arn, 
		model_version, 
		min_unit=1, 
		max_unit=2, 
		min_confidence=50
		):
    """
    Main function to run the processing job.
    This function loads the Rekognition model, processes images from the input directory,
    and saves the results in the output directory.
    """
    # SageMaker paths
    input_data_path = '/opt/ml/processing/input'
    output_data_path = '/opt/ml/processing/output'
    
    # Ensure output directory exists
    os.makedirs(output_data_path, exist_ok=True)
    
    # Connect to rekognition
    client = boto3.client('rekognition')
	
    # retrieve label mapping
    label_map = retrieve_label_mapping(db_name, master_collection_name)
	
    # Check model file existence and size
    start_model(
			client,
			project_arn,
			model_arn,
			model_version,
			min_unit,
			max_unit
		)
    
    _logger.info(f"Loading model from {model_arn}")
    
    # Process all images in the input directory
    start_time = time.time()
    processed_count = 0
    
    for root, _, files in os.walk(input_data_path):
        for file in sorted(files):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
                input_file_path = os.path.join(root, file)
                relative_path = os.path.relpath(input_file_path, input_data_path)
                output_file_path = os.path.join(output_data_path, f"{os.path.splitext(relative_path)[0]}.json")
                
                if os.path.exists(output_file_path):
                    _logger.warning(f"Skipping {relative_path}, already processed")
                    continue
                
                # Ensure output directory for this file exists
                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
                
                _logger.info(f"Processing {relative_path}")
                try:
                    results = process_image(
						image_path=input_file_path,
						output_path=output_file_path,
						client=client,
						s3_input_uri=s3_input_uri,
						file=file,
						label_map=label_map,
						min_confidence=min_confidence,
						model_arn=model_arn
						)
                    _logger.info(f"Found {len(results)} objects in {relative_path}")
                    processed_count += 1
                except Exception as e:
                    _logger.error(f"Error processing {relative_path}: {e}")
    
    elapsed_time = time.time() - start_time
    _logger.info(f"Processed {processed_count} images in {elapsed_time:.2f} seconds")
    _logger.info("Processing job complete")
	
	# Stop model even if the script fails
    stop_model(client, model_arn)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--s3_input_uri", type=str, default=None)
    parser.add_argument("--db_name", type=str, default=None)
    parser.add_argument("--master_collection_name", type=str, default=None)
    parser.add_argument("--project_arn", type=str, default=None)
    parser.add_argument("--model_arn", type=str, default=None)
    parser.add_argument("--model_version", type=str, default=None)
    parser.add_argument("--min_unit", type=int, default=1)
    parser.add_argument("--max_unit", type=int, default=2)
    parser.add_argument("--min_confidence", type=float, default=50.0)
    args, _ = parser.parse_known_args()

    _logger.info("Received arguments {}".format(args))
    main(
        s3_input_uri=args.s3_input_uri,
        db_name=args.db_name,
        master_collection_name=args.master_collection_name,
        project_arn=args.project_arn,
        model_arn=args.model_arn,
        model_version=args.model_version,
        min_unit=args.min_unit,
        max_unit=args.max_unit,
        min_confidence=args.min_confidence
        )
