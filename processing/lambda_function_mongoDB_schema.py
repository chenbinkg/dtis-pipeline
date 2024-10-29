'''
DataPlatform Lambda Function for ingesting text-file-based DTIS/OFOP content into MongoDB:

* Text files on S3 are parsed by this function and the relevant content converted to MongoDB collections.
* File format is expected to conform to the specifications used in/created by OFOP software for DTIS (prot and rerun files).
* Folders that contain video and image files are being referenced in the output collection by adding links to those folders. 

Requirements:
* PyMongo needs to be available to the Lambda process Python 3 environment (can be added via a Lambda layer)
* Define environment variables for 
* MongoDB connection string, e.g. MONGODB_URI, 
* and the name of the MongoDB database, e.g. MONGODB_DATABASE
* Define environment variable for the name of the MongoDB collection used for observations, e.g. MONGODB__COLLECTION
* Define environment variable for the name of the MongoDB collection used for overview, e.g. INGRESS_COLLECTION_DTIS
* Define environment variable for the name of the S3 bucket containing the text files, e.g. S3_BUCKET_NAME
* Prot and posi files need to be both available in an upload, image and video files are implicitly expected, too.



October 2024 Tilmann Steinmetz

'''


import json
import logging
import os
import re
import urllib
from datetime import datetime, time, timedelta, timezone

import boto3
from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import ReturnDocument

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_current_ingress_id(
    db, COUNTER_COLLECTION_NAME, cruise, station, remarks, date_created
):
    counter = db[COUNTER_COLLECTION_NAME].find_one_and_update(
        {"cruise": cruise, "station": station, "remarks": remarks},
        {
            "$setOnInsert": {
                "value": 0,
                "date_created": date_created,
                "date_updated": datetime.now(timezone.utc),
            }
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,  # CHANGE 1
    )
    return counter["value"]


def increment_ingress_id(
    db,
    COUNTER_COLLECTION_NAME,
    cruise,
    station,
    remarks,
    bounding_box,
    count_documents,
    date_created,
    video_events,
):
    # Calculate total duration
    total_duration = timedelta()
    for start, stop in zip(
        [e for e in video_events if e["event"] == "start"],
        [e for e in video_events if e["event"] == "stop"],
    ):
        start_time = datetime.fromisoformat(start["time"])
        stop_time = datetime.fromisoformat(stop["time"])
        total_duration += stop_time - start_time

    video_info = {
        "events": video_events,
        "total_videos": sum(1 for event in video_events if event["event"] == "start"),
        "total_duration": str(total_duration),
    }

    result = db[COUNTER_COLLECTION_NAME].update_one(
        {"cruise": cruise, "station": station, "remarks": remarks},
        {
            "$inc": {"value": 1},
            "$set": {
                "observationCount": count_documents,
                "boundingBox": bounding_box,
                "date_updated": datetime.now(timezone.utc),
                "video": video_info,
            },
            "$setOnInsert": {"date_created": date_created},
        },
        upsert=True,
    )


def calculate_bounding_box(coordinates):
    """
    Calculate the bounding box for a list of coordinates.
    """
    if not coordinates:
        return None

    lons, lats = zip(*coordinates)
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min(lons), min(lats)],
                [max(lons), min(lats)],
                [max(lons), max(lats)],
                [min(lons), max(lats)],
                [min(lons), min(lats)],
            ]
        ],
    }


def parse_header(header_text):
    meta = {}
    # Extract cruise, station, and remarks
    meta["cruise"] = next(
        (
            line.split(":")[1].strip()
            for line in header_text
            if line.startswith("Cruise")
        ),
        None,
    )
    meta["station"] = next(
        (
            line.split(":")[1].strip()
            for line in header_text
            if line.startswith("Station")
        ),
        None,
    )
    meta["remarks"] = next(
        (
            line.split(":")[1].strip()
            for line in header_text
            if line.startswith("Remarks")
        ),
        None,
    )

    return meta


def parse_data_line(line, source_key, video_start_time, video_events):
    fields = line.split("\t")
    if len(fields) < 12:
        return None, video_start_time, video_events

    utc_time = fields[0]
    lat, lon = float(fields[2]), float(fields[3])
    sub_lat, sub_lon = float(fields[10]), float(fields[11])
    speed, course, depth, heading = map(float, fields[4:8])
    observation = fields[13] if len(fields) > 12 else ""
    media = ""
    mediatype = ""
    mediaoffset = None

    current_time = datetime.strptime(utc_time, "%H:%M:%S")

    if "video started" in observation.lower() or "start video" in observation.lower():
        video_start_time = current_time
        video_events.append({"event": "start", "time": current_time.isoformat()})
        mediaoffset = timedelta(seconds=0)
    elif "video stopped" in observation.lower() or "stop video" in observation.lower():
        if video_start_time:
            mediaoffset = current_time - video_start_time
            video_events.append(
                {
                    "event": "stop",
                    "time": current_time.isoformat(),
                    "duration": str(mediaoffset),
                }
            )
        video_start_time = None
    elif video_start_time:
        mediaoffset = current_time - video_start_time

    if "photo" in observation.lower():
        try:
            il = f'/images/{source_key.rsplit("_prot.", 1)[0].rsplit("_", 1)[0]}/{source_key.rsplit("_prot.", 1)[0]}_{observation.rsplit("photo", 1)[1]}.jpg'
        except:
            il = f'/images/{source_key.rsplit("_prot.", 1)[0].rsplit("_", 1)[0]}/{source_key.rsplit(".", 1)[0]}_{observation}.jpg'
        
        media = il
        mediatype = "photo"
    elif (
        video_start_time
        or "video stopped" in observation.lower()
        or "stop video" in observation.lower()
    ):
        # construct a link to the video file which will also be uploaded
        try:
            vl = f'/videos/{source_key.rsplit("_prot.", 1)[0].rsplit("_", 1)[0]}/{source_key.rsplit("_prot.", 1)[0]}.m2t'
        except:
            vl = f'/videos/{source_key.rsplit("_prot.", 1)[0].rsplit("_", 1)[0]}/{source_key.rsplit(".", 1)[0]}.m2t'
        
        media = vl
        mediatype = "video"

        # # construct a link to the video file which will also be uploaded
        # vl = f'/videos/{source_key.rsplit("_prot.", 1)[0].rsplit("_", 1)[0]}/{source_key.rsplit(".", 1)[0]}.m2t'
        # print(vl)
        if os.path.exists(vl):
            media = vl
            mediatype = "video"
        else:
            # We just pretend it must be there, for now:
            media = vl
            mediatype = "video"

    return (
        {
            "timestamp": utc_time,
            "shipLocation": {"type": "Point", "coordinates": [lon, lat]},
            "speed": speed,
            "course": course,
            "heading": heading,
            "depth": depth,
            "subLocation": {"type": "Point", "coordinates": [sub_lon, sub_lat]},
            "feature": {
                "media": media,
                "mediaType": mediatype,
                "mediaOffset": (
                    mediaoffset.total_seconds() if mediaoffset else None
                ),  # calculate the offset (time in seconds) for this record since "video started"
                "observation": observation,
                "observation2": None,
                "observation3": None,
                "observationRef": "[AphiaID / link to WORMS]",
            },
        },
        video_start_time,
        video_events,
    )


def get_posi_file_content(s3, bucket, key):
    # Extract the stem of the file name
    file_stem = re.sub(r"_prot\.txt$", "", key)
    posi_key = f"{file_stem}_posi.txt"

    try:
        response = s3.get_object(Bucket=bucket, Key=posi_key)
        return response["Body"].read().decode("utf-8")
    except s3.exceptions.NoSuchKey:
        print(f"No corresponding posi file found for {key}")
        return None


def parse_posi_file(content):
    lines = content.split("\n")
    header = lines[0].split("\t")
    data = {}

    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) >= 2:
            date = fields[0].strip()
            time = fields[1].strip()
            try:
                dt = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M:%S")
                dt_utc = dt.replace(tzinfo=timezone.utc)  # Make it timezone-aware
                data[dt_utc.isoformat()] = {
                    "datetime": dt_utc,  # This should be a full datetime object
                    "data": {
                        header[i]: fields[i]
                        for i in range(len(fields))
                        if i < len(header)
                    },
                }
            except ValueError as e:
                print(f"Invalid date/time format: {date} {time}. Error: {str(e)}")
                continue  # Skip this line and continue with the next

    return data


def lambda_handler(event, context):
    # Read the file from S3
    s3 = boto3.client("s3")
    bucket_name = os.environ["S3_BUCKET_NAME"]
    
    file_key = urllib.parse.unquote_plus(
        event["Records"][0]["s3"]["object"]["key"], encoding="utf-8"
    )

    try:
        logger.info(f"Attempting to get object: {file_key} from bucket: {bucket_name}")
        response = s3.get_object(Bucket=bucket_name, Key=file_key)
        file_content = response["Body"].read().decode("utf-8")
        logger.info(f"Successfully retrieved file content")
        # Process file_content here
    except s3.exceptions.NoSuchKey:
        logger.error(f"The object {file_key} does not exist in bucket {bucket_name}")
        # Handle the error - maybe return an error message or set a default value
    except Exception as e:
        logger.error(f"An unexpected error occurred: {str(e)}")
        # Handle other potential errors

    # Read the prot file from s3
    response = s3.get_object(Bucket=bucket_name, Key=file_key)
    file_content = response["Body"].read().decode("utf-8")

    # Get and parse the corresponding posi file
    posi_content = get_posi_file_content(s3, bucket_name, file_key)
    posi_data = parse_posi_file(posi_content) if posi_content else {}

    lines = file_content.split("\n")
    # Split the file into header and data
    header = lines[:12]  # Adjust based on your actual header size
    data_lines = lines[12:]

    # Parse the header
    meta = parse_header(header)
    cruise = meta.get("cruise", "")
    station = meta.get("station", "")
    remarks = meta.get("remarks", "")

    # Connect to MongoDB (assuming connection string is in environment variable)
    client = MongoClient(os.environ["MONGODB_URI"])
    db = client[os.environ["MONGODB_DATABASE"]]
    collection = db[os.environ["MONGODB_COLLECTION"]]
    ingress_counter = os.environ["INGRESS_COLLECTION_DTIS"]
    COUNTER_COLLECTION_NAME = ingress_counter
    date_created = datetime.now(timezone.utc).isoformat()

    try:
        # Get the current ingressId
        current_ingress_id = get_current_ingress_id(
            db, COUNTER_COLLECTION_NAME, cruise, station, remarks, date_created
        )

        # Prepare documents and collect subLocation coordinates
        video_events = []
        video_start_time = None
        documents = []
        sub_coordinates = []
        for i, line in enumerate(data_lines):
            data_point, video_start_time, video_events = parse_data_line(
                line, file_key, video_start_time, video_events
            )
            if data_point:
                prot_time = datetime.strptime(
                    data_point["timestamp"], "%H:%M:%S"
                ).time()

                # Find the closest matching timestamp in posi_data
                closest_posi_entry = min(
                    posi_data.values(),
                    key=lambda x: abs(
                        (
                            datetime.combine(x["datetime"].date(), prot_time).replace(
                                tzinfo=timezone.utc
                            )
                            - x["datetime"]
                        ).total_seconds()
                    ),
                    default=None,
                )

                if closest_posi_entry:
                    # Use the date from the posi file and time from the prot file
                    timestamp = closest_posi_entry["datetime"].replace(
                        hour=prot_time.hour,
                        minute=prot_time.minute,
                        second=prot_time.second,
                    )

                else:
                    raise ValueError("No matching timestamp found in posi_data.")

                data_point["timestamp"] = timestamp.isoformat()

                doc = {
                    "_id": ObjectId(),
                    "meta": {
                        "cruiseStationId": ObjectId(),
                        "cruise": cruise,
                        "station": station,
                        "remarks": remarks,
                        "ingressId": current_ingress_id,
                        "created": date_created,
                    },
                    **data_point,
                }

                documents.append(doc)
                sub_coordinates.append(doc["subLocation"]["coordinates"])

        # Calculate the bounding box
        bounding_box = calculate_bounding_box(sub_coordinates)

        # Insert documents into MongoDB
        result = collection.insert_many(documents)
        # Increment the ingressId for the next run
        increment_ingress_id(
            db,
            ingress_counter,
            cruise,
            station,
            remarks,
            bounding_box,
            len(documents),
            date_created,
            video_events,
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                f"Inserted {len(result.inserted_ids)} documents into MongoDB. Current ingressId: 
                {get_current_ingress_id(db, COUNTER_COLLECTION_NAME, cruise, station, remarks, date_created)}"
            ),
        }
    except Exception as e:
        print(e)
        return {
            "statusCode": 500,
            "body": json.dumps(f"Error processing file. Error: {str(e)}"),
        }
    finally:
        # Close the MongoDB connection
        client.close()
