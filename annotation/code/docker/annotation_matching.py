from pymongo.mongo_client import MongoClient
import logging
import pandas as pd
import boto3
from io import StringIO
import json

_logger = logging.getLogger()
_logger.setLevel(logging.INFO)

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

# convert labelled data to video frame, see below
def get_video_start_time(df, start_prompt="Start video"):
    """
    Find video start time from MongoDB queried results
    return video start time as a list in descending time order
    """
    df = df.sort_values(by=["timestamp"], ascending=False)
    df = df[df["observation"].str.contains(start_prompt)]
    return df["timestamp"].tolist()

def sync_obser_with_video_frame(df_obs, vide_start_times):
    """
    sync video observation with video start times
    generate video frame names for each video at each time stamp
    """
    video_labels = {}
    for video_start_time in vide_start_times:
        # latest video comes first, filter from bottom
        df = df_obs[df_obs["timestamp"]>video_start_time]
        df["video_time"] = df["timestamp"] - video_start_time
        df["frame_num"] = df["video_time"].apply(lambda x: x.total_seconds())
        df["frame_file"] = df["frame_num"].apply(lambda x: f"frame_{int(x):04}.jpeg")
        video_labels[video_start_time] = df
        df_obs = df_obs[~df_obs.index.isin(df.index)] # exclude df index
    return video_labels

def read_csv_from_s3(bucket_name, file_key):
    """
    Reads a CSV file from an S3 bucket and returns it as a pandas DataFrame.

    :param bucket_name: Name of the S3 bucket
    :param file_key: Key (path) of the CSV file in the S3 bucket
    :return: pandas DataFrame containing the CSV data
    """
    # Create a session using boto3
    s3 = boto3.client('s3')
    # Get the object from the S3 bucket
    response = s3.get_object(Bucket=bucket_name, Key=file_key)
    # Read the CSV data
    csv_data = response['Body'].read().decode('utf-8')
    # Convert the CSV data to a pandas DataFrame
    df = pd.read_csv(StringIO(csv_data))
    return df

def read_manifest(manifest_path):
    with open(manifest_path, 'r') as file:
        data = [json.loads(line) for line in file]
    return data

def convert_float32(obj):
    if isinstance(obj, np.float32):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

# generate query from MongoDB (dtis_videos) for video start time
mongo_ops = MongoDBOps()
columns = ["cruise", "station", "timestamp", "date", "time", "observation"]
query_cols = ["cruise", "station"]
query_vals = ["TAN0616", "095"]
query_filter = mongo_ops.gen_query_filter(columns=query_cols, values=query_vals)
column_filter = mongo_ops.gen_column_filter(columns=columns)
df_video_meta = mongo_ops.read_to_df(
    db_name="dtistest", 
    collection_name="dtis_videos", 
    query_filter=query_filter, 
    column_filter=column_filter
)

# generate query from MongoDB (dtis_ofop_obser) for labelled data
mongo_ops = MongoDBOps()
columns = ["cruise", "station", "timestamp", "date", "time", "observation", "observation2"]
query_cols = ["cruise", "station"]
query_vals = ["TAN0616", "095"]
query_filter = mongo_ops.gen_query_filter(columns=query_cols, values=query_vals)
column_filter = mongo_ops.gen_column_filter(columns=columns)
df_ofop_obser = mongo_ops.read_to_df(
    db_name="dtistest", 
    collection_name="dtis_ofop_obser", 
    query_filter=query_filter, 
    column_filter=column_filter
)
df_ofop_obser = df_ofop_obser.sort_values("timestamp").reset_index(drop=True)

vide_start_times = get_video_start_time(df_video_meta)
video_labels = sync_obser_with_video_frame(df_ofop_obser, vide_start_times)

# read ofop master file
bucket_name = 'dtis-ofop'
file_key = 'button_files/ofop-master.csv'
df_master = read_csv_from_s3(bucket_name, file_key)
df_master = df_master[df_master["Category"].isin(['Fish', 'Invertebrate'])]

# read grounding dino labels, already filtered by detection area pct (0.001)
manifest_path = "output_rekognition.manifest"
dino_anno = read_manifest(manifest_path)

# read from json file for species and bounding boxes identified
# validate the video labels vs groundingdino labels
matched_anno = dino_anno.copy()
for video_start_time, df in video_labels.items():
    print(video_start_time)
    # get human label video frames
    # keep only Fish and Invertebrate
    df1 = df[
    (df["observation2"].isin(df_master["Observation_1"])) | 
    (df["observation2"].isin(df_master["Observation_2"]))
    ]
    # find labels matches with video label
    human_labels_found = []
    human_labels_not_found = []
    for i, row in df1.iterrows():
        file_name = row["frame_file"]
        file_counter = int(file_name.split("_")[-1].split(".")[0])
        if "observation2" in row.keys():
            human_anno = row["observation2"]
        else:
            human_anno = row["observation"]
        # check if file_name is found in dino label set
        # file_found = [file_name for e in dino_anno if file_name in e["source-ref"]
        file_found = []
        for i, e in enumerate(dino_anno):
            if file_name in e["source-ref"]:
                # if file_name of human label can be found in dino label
                file_found.append(file_name)
                for key in list(e.keys()):
                    if key != "source-ref":
                        if "-metadata" in key:
                            # modify metadata key
                            new_metadata_key = f"{human_anno}-metadata"
                            e[new_metadata_key] = e.pop(key)
                            e[new_metadata_key]['human-annotated'] = 'yes'
                            # matched_anno[i][new_metadata_key] = e[key]
                            # del matched_anno[i][key]
                        else:
                            # modify anno key
                            new_key = f"{human_anno}"
                            e[new_key] = e.pop(key)
                            # matched_anno[i][new_key] = e[key]
                            # del matched_anno[i][key]
                            
        if file_counter < 2000:
            if file_found:
                human_labels_found.append(file_name)
            else:
                human_labels_not_found.append(file_name)


matched_manifest_path = "matched_rekognition.manifest"
for json_line in matched_anno:
    with open(matched_manifest_path, 'a') as f:
        f.write(json.dumps(json_line, default=convert_float32) + '\n')

df1[df1["frame_file"].isin(human_labels_not_found)]

'''
TO-DO: architecture

triggered by media-convert completion event
set up event bridge rule to trigger lambda --> sagemaker pipeline when conversion completes (for latest trips, raw format is .mpeg, need to convert to .mp4 to reduce bit rate maybe?)
TO-DO: Sagemaker pipeline

create container
retrieve model weights
filter master list
activate groundingDINO for pre-labellng job: label_bbox
perform label filtering: remove labels with low detection area
only keep fish and inverterbrate in ofop obser using ofop_master file
match labelled frames with ofop labels for additional validation/filtering
save labelled images to s3, create connection with biigle
manual labelling
with labelled images, train the models
'''