import logging
import pandas as pd
import os
import sys
import json
import argparse
from .mongodb import MongoDBOps

# Add parent directory to path for imports when running from /opt/ml/processing/input/code/
sys.path.insert(0, '/opt/ml/processing')

from mongodb import MongoDBOps
from utils import get_ssm_parameter, sanitize_log_input

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger()


# convert labelled data to video frame, see below
def get_video_start_time(df, start_prompt="Start video"):
    """
    Find video start time from MongoDB queried results
    return video start time as a list in descending time order
    """
    df = df.sort_values(by=["timestamp"], ascending=False)
    df = df[df["observation"].str.contains(start_prompt)]
    return df["timestamp"].tolist()

def sync_obser_with_video_frame(df_obs, df_master, vide_start_times):
    """
    sync video observation with video start times
    generate video frame names for each video at each time stamp
    """
    video_labels = {}
    for video_start_time in vide_start_times:
        # latest video comes first, filter from bottom
        df = df_obs[df_obs["timestamp"]>video_start_time]
        df["video_time"] = df["timestamp"] - video_start_time
        df["frame_num"] = df["video_time"].apply(lambda x: x.total_seconds()) - 1 # minus 1sec for better match
        df["frame_file"] = df["frame_num"].apply(lambda x: f"{int(x):05}.jpeg")
        df = pd.merge(left=df, 
                      right=df_master, 
                      left_on="observation", 
                      right_on="Observation_2", 
                      how="left"
                     )
        df = df.dropna(subset=["Observation_2"], axis=0)
        video_labels[video_start_time] = df
        df_obs = df_obs[~df_obs.index.isin(df.index)] # exclude df index
    return video_labels

def main(cruise, station, db_name, video_collection, master_collection, ofop_obser_collection, ssm_param_mongodb_uri):
    """
    Main function to perform annotation matching.
    This function reads video metadata and master labels from MongoDB,
    retrieves observation data, and matches human labels with pretrained annotations.
    It processes the video frames and saves the matched annotations to S3.
    The function expects the S3 input URI to contain cruise and station information,
    which it uses to query the relevant data from MongoDB collections.
    It also expects the MongoDB collections to contain specific fields for video metadata,
    master labels, and observation data.
    The matched annotations are saved in the output directory specified by the SageMaker processing job.

    Args:
        cruise (str): Cruise identifier.
        station (str): Station identifier.
        db_name (str): Name of the MongoDB database.
        video_collection (str): Name of the MongoDB collection for video metadata.
        master_collection (str): Name of the MongoDB collection for master labels.
        ofop_obser_collection (str): Name of the MongoDB collection for observation data.
        ssm_param_mongodb_uri (str): SSM parameter for MongoDB URI.
    """
    _logger.info("Starting RFDETR annotation matching job")
    _logger.info(f"Processing images for cruise: {cruise}, station: {station}")

    # SageMaker paths
    input_data_path = '/opt/ml/processing/pretrained_annotations'
    output_data_path = '/opt/ml/processing/matched_annotations'
    os.makedirs(output_data_path, exist_ok=True)
    _logger.info(f"Input data path: {input_data_path}")
    _logger.info(f"Output data path: {output_data_path}")

    # generate query from MongoDB (dtis_videos) for video start time
    mongodb_uri = get_ssm_parameter(ssm_param_mongodb_uri, "")
    mongo_ops = MongoDBOps(mongodb_uri=mongodb_uri)
    columns = ["cruise", "station", "timestamp", "date", "time", "observation"]
    query_cols = ["cruise", "station"]
    query_vals = [cruise, station]
    query_filter = mongo_ops.gen_query_filter(columns=query_cols, values=query_vals)
    column_filter = mongo_ops.gen_column_filter(columns=columns)
    df_video_meta = mongo_ops.read_to_df(
        db_name=db_name, 
        collection_name=video_collection, 
        query_filter=query_filter, 
        column_filter=column_filter
    )

    # generate query from MongoDB (dtis_master) for labels
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

    df_master = pd.concat([df_master_fish, df_master_invert], axis=0)
    _logger.info(f"master headers: {df_master.columns}")
    # generate query from MongoDB (dtis_ofop_obser) for labelled data
    columns = ["cruise", "station", "timestamp", "date", "time", "observation", "observation2"]
    query_cols = ["cruise", "station"]
    query_vals = [cruise, station]
    query_filter = mongo_ops.gen_query_filter(columns=query_cols, values=query_vals)
    column_filter = mongo_ops.gen_column_filter(columns=columns)
    df_ofop_obser = mongo_ops.read_to_df(
        db_name=db_name, 
        collection_name=ofop_obser_collection, 
        query_filter=query_filter, 
        column_filter=column_filter
    )
    _logger.info(f"ofop headers: {df_ofop_obser.columns}")
    # keep observation2 if both observation and observation2 exist
    if "observation2" in df_ofop_obser.columns:
        if "observation" in df_ofop_obser.columns:
            df_ofop_obser = df_ofop_obser.drop("observation", axis=1)
        df_ofop_obser = df_ofop_obser.rename(columns={"observation2": "observation"})
    df_ofop_obser = df_ofop_obser.sort_values("timestamp").reset_index(drop=True)

    vide_start_times = get_video_start_time(df_video_meta)
    video_labels = sync_obser_with_video_frame(df_ofop_obser, df_master, vide_start_times)

    # read from json file for species and bounding boxes identified
    # validate the video labels vs pretrained annotation labels
    # annotation_path = "annotated_images/TAN0616_095/"
    # annotation_path_output = "annotated_images/TAN0616_095_matched_ofop/"

    pretrained_anno_files = os.listdir(input_data_path)

    for video_start_time, df in video_labels.items():
        print(video_start_time)
        # get human label video frames
        # find labels matches with video label
        human_labels_found = 0
        total_annotations = 0
        unique_frames = df["frame_file"].unique()
        for file_name in sorted(unique_frames):
            _logger.info(f"processing {file_name} for annotation matching")
            df_1 = df[df["frame_file"] == file_name]
            file_counter = file_name.split(".")[0]
            anno_file_found = [e for e in pretrained_anno_files if f"{file_counter}.json" in e]
            if len(anno_file_found) == 0:
                _logger.info(f"*{file_counter}.json not found!")
                continue
            _logger.info(f"anno file found: {anno_file_found[0]}")
            # load pretrained anno file
            anno_file = os.path.join(input_data_path, anno_file_found[0])
            with open(anno_file) as f:
                pretrained_anno_json = json.load(f)
            _logger.info(f"loaded pretrained annotation file: {pretrained_anno_json}")
            # check if there is annotation
            if isinstance(pretrained_anno_json, list):
                _logger.info(f"annotation not in dictionary format for: {file_name}! Skipping...")
                continue
            if "bounding-box-metadata" not in pretrained_anno_json.keys():
                _logger.info(f"no object detected for pretrained model at: {file_name}!")
                continue
            # find all available labels
            class_map = pretrained_anno_json['bounding-box-metadata']['class-map']
            pretrained_annos = pretrained_anno_json['bounding-box']['annotations']
            class_ids = list(class_map.keys())
            class_labels = list(class_map.values())
            biigle_tree_ids = df_1["biigle_tree_id"].tolist()
            human_annos = df_1["observation"].tolist()
            # loop through pretrained annotation class
            # simple way to perform 1-to-1 detection matching
            class_map_1 = class_map.copy()
            pretrained_annos_1 = pretrained_annos.copy()
            total_annotations+=len(pretrained_annos)
            for cid, cname, btid, anno in zip(class_ids, class_labels, biigle_tree_ids, human_annos):
                class_map_1.pop(cid) # remove pretrain class id
                btid_int = int(btid) # convert to int
                class_map_1[btid_int] = anno # assign human annotation and biigle tree id
                _logger.info(f"***changing class {cname} to {anno} at: {file_name}***")
                # loop through bounding box and replace
                for i, anno_x in enumerate(pretrained_annos_1):
                    if anno_x["class_id"] == cid:
                        pretrained_annos_1[i]["class_id"] = btid_int
                        human_labels_found+=1
            pretrained_anno_json['bounding-box-metadata']['class-map'] = class_map_1
            pretrained_anno_json['bounding-box']['annotations'] = pretrained_annos_1

            matched_manifest_path = os.path.join(output_data_path, anno_file_found[0])
            # Save new results
            with open(matched_manifest_path, 'w') as f:
                json.dump(pretrained_anno_json, f)
        _logger.info(
            f"total human labels matched with pretrained annotations: {human_labels_found}\n"
            f"total pretrained annotations not matched: {total_annotations-human_labels_found}\n"
            f"total pretrained annotations: {total_annotations}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cruise", type=str, default=None)
    parser.add_argument("--station", type=str, default=None)
    parser.add_argument("--db_name", type=str, default=None)
    parser.add_argument("--video_collection_name", type=str, default=None)
    parser.add_argument("--master_collection_name", type=str, default=None)
    parser.add_argument("--ofop_obser_collection_name", type=str, default=None)
    parser.add_argument("--ssm_param_mongodb_uri", type=str, default="/dtis/mongodb/uri")
    args, _ = parser.parse_known_args()

    _logger.info("Received arguments {}".format(args))
    main(
        cruise=args.cruise,
        station=args.station,
        db_name=args.db_name,
        video_collection=args.video_collection_name,
        master_collection=args.master_collection_name,
        ofop_obser_collection=args.ofop_obser_collection_name,
        ssm_param_mongodb_uri=args.ssm_param_mongodb_uri
        )
