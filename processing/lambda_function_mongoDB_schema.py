"""
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

* Time parsing:

should we use the 'pendulum' library so we're better able to deal with dates/times?


12 November 2024 Tilmann Steinmetz

"""

import json
import logging
import os
import urllib
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection, ReturnDocument
from pymongo.database import Database

logger = logging.getLogger()
logger.setLevel(logging.INFO)

START_TIME = datetime.now(timezone.utc)
MAX_EXECUTION_TIME = 850  # 14.5 minutes (for 15-minute Lambda timeout)


def check_timeout():
    """Check if the function is approaching the timeout limit"""
    elapsed_time = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    if elapsed_time > MAX_EXECUTION_TIME:
        logger.warning("Function approaching timeout - forcing exit")
        raise Exception("Function timeout reached")


def prepare_for_mongodb(document):
    """Convert any datetime/timedelta objects to strings in a document"""
    if isinstance(document, dict):
        return {k: prepare_for_mongodb(v) for k, v in document.items()}
    elif isinstance(document, list):
        return [prepare_for_mongodb(v) for v in document]
    elif isinstance(document, (datetime, time)):
        return document.isoformat()
    elif isinstance(document, timedelta):
        return str(document)
    return document


def datetime_handler(obj):
    """Custom JSON serializer for datetime objects"""
    if isinstance(obj, (datetime, time)):
        return obj.isoformat()
    elif isinstance(obj, timedelta):
        return str(obj)
    elif isinstance(obj, ObjectId):
        return str(obj)  # Convert ObjectId to string
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def get_current_ingress_id(ingress_collection, cruise, station, remarks, date_created):
    """
    Get the current ingressId for a given cruise, station, and remarks.
    If the document does not exist, create it with a value of 0.

    This is used to keep track of the number of ingresses for a given cruise/station/remarks.
    """
    counter = ingress_collection.find_one_and_update(
        {"cruise": cruise, "station": station, "remarks": remarks},
        {
            "$setOnInsert": {
                "value": 0,
                "date_created": (
                    date_created.isoformat()
                    if isinstance(date_created, datetime)
                    else date_created
                ),
                "date_updated": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return counter["value"]


def increment_ingress_id(
    ingress_collection,
    cruise,
    station,
    remarks,
    bounding_box,
    count_documents,
    date_created,
):
    """
    Increment the ingressId for a given cruise, station, and remarks.
    If the document does not exist, create it with a value of 1.

    This is used to keep track of the number of ingresses for a given cruise/station/remarks.
    """

    try:
        update_doc = {
            "$inc": {"value": 1},
            "$set": {
                "observationCount": count_documents,
                "boundingBox": bounding_box,
                "date_updated": datetime.now(
                    timezone.utc
                ).isoformat(),  # Convert to ISO string
            },
            "$setOnInsert": {
                "date_created": (
                    date_created.isoformat()
                    if isinstance(date_created, datetime)
                    else date_created
                )
            },
        }

        # Log the document before insertion
        logger.info(
            f"Attempting to update with document: {json.dumps(update_doc, default=str)}"
        )

        result = ingress_collection.update_one(
            {"cruise": cruise, "station": station, "remarks": remarks},
            update_doc,
            upsert=True,
        )
        return result
    except Exception as e:
        logger.error(f"Error in increment_ingress_id: {str(e)}")
        logger.error(f"Document that caused error: {update_doc}")
        raise


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


from typing import Any, Dict, List, Optional, Tuple


def parse_data_line(
    line: str,
    source_key: str,
    video_start_time: Optional[datetime] = None,
    video_events: List[Dict[str, Any]] = [],
    file_format: str = "original",
) -> Tuple[Optional[Dict[str, Any]], Optional[datetime], List[Dict[str, Any]]]:
    """
    Parse a line of data from either original or new rerun_XX_obs format files
    """
    check_timeout()

    # Add safety check for video_events list size
    if len(video_events) > 1000:  # Set appropriate limit
        logger.error("Too many video events - possible infinite loop")

    if not line or line.startswith("#") or line.startswith("End ###"):
        return None, video_start_time, video_events

    fields = line.strip().split("\t")

    if file_format == "original":
        if len(fields) < 12:  # Original format requires at least 12 fields
            return None, video_start_time, video_events
        # logger.info(f"Fields: {fields}, file_format = {file_format}")
        utc_time = fields[0]
        lon = float(fields[3])
        lat = float(fields[2])
        speed = float(fields[4])
        course = float(fields[5])
        depth = float(fields[6])
        heading = float(fields[7])
        sub_lon = float(fields[11])
        sub_lat = float(fields[10])
        observation = fields[13] if len(fields) > 12 else ""
        current_time = datetime.strptime(utc_time, "%H:%M:%S")

    else:  # new rerun_obser text file format
        if len(fields) != 6:  # New format requires exactly 6 fields
            return None, video_start_time, video_events
        logger.info(f"Fields: {fields}, file_format = {file_format}")

        utc_time = fields[1]
        # Skip date field[0] in rerun file. We will interpolate the date
        lon = float(fields[2])
        lat = float(fields[3])
        speed = None
        course = None
        depth = None
        heading = None
        sub_lon = lon  # Use same coordinates for sub location
        sub_lat = lat
        observation = fields[5]
        current_time = datetime.strptime(utc_time, "%H:%M:%S")

    # Determine source type
    is_prot = source_key.endswith("_prot.txt")
    is_obs = source_key.endswith("_obser.txt")

    if not (is_prot or is_obs):
        raise ValueError("Invalid source input (text) file type")

    # Initialize feature dictionary
    feature = {
        "media": "",
        "mediaType": "",
        "mediaOffset": None,
        "observation": observation,
        "observation2": None,
        "observation_source": file_format,
        "observationRef": f"<a href='https://www.marinespecies.org/rest/AphiaRecordsByMatchNames?scientificnames%5B%5D={observation}&marine_only=true'>Try a WORMS search for {observation}</a>",
    }

    # Handle photo observations
    if "photo" in observation.lower():
        feature["mediaType"] = "photo"
        # Extract voyage and station from source_key (assuming format like 'TAN2306_123_prot.txt')
        if is_prot:
            voyage_station = source_key.split("_prot.txt")[0]
        elif is_obs:
            voyage_station = source_key.split("_obser.txt")[0]

        # voyage_station = source_key.split("_prot.txt")[0]
        feature["media"] = f"/images/{voyage_station}/{voyage_station}_12.jpg"

    # Handle video observations
    if isinstance(video_start_time, str):
        video_start_time = datetime.strptime(video_start_time, "%H:%M:%S")

    if "video started" in observation.lower() or "start video" in observation.lower():
        a_start_time = timedelta(seconds=0)
        video_start_time = current_time
        video_events.append(
            {"event": "start", "time": current_time.strftime("%H:%M:%S")}
        )
        feature["mediaOffset"] = str(a_start_time)
        feature["mediaType"] = "video"
        # Extract voyage and station from source_key (assuming format like 'TAN2306_123_prot.txt')
        if is_prot:
            voyage_station = source_key.split("_prot.txt")[0]
        elif is_obs:
            voyage_station = source_key.split("_obser.txt")[0]

        feature["media"] = f"/videos/{voyage_station}/{voyage_station}.m2t"

    elif "video stopped" in observation.lower() or "stop video" in observation.lower():
        if video_start_time:
            media_offset = current_time - video_start_time
            feature["mediaOffset"] = str(media_offset)
            video_events.append(
                {
                    "event": "stop",
                    "time": current_time.strftime("%H:%M:%S"),
                    "duration": str(media_offset),
                }
            )
            video_start_time = None

    # Create the result dictionary
    # Common processing for both formats
    result = {
        "timestamp": utc_time,
        "shipLocation": {"type": "Point", "coordinates": [lon, lat]},
        "speed": speed,
        "course": course,
        "heading": heading,
        "depth": depth,
        "subLocation": {"type": "Point", "coordinates": [sub_lon, sub_lat]},
        "feature": feature,
    }

    return result, video_start_time, video_events


def get_posi_file_content(s3: boto3.client, bucket: str, key: str) -> str:
    """
    We are using a companion _'posi.txt' file to look up date/time information:
    Lambda function uses a lookup of information from a a pair of 'companion' text files.
    get_posi_file_content() is used to find a file which has a similar file name,
    but instead of ending in _prot.txt, it ends in _posi.txt.
    """

    try:
        # Handle both _prot.txt and _obser.txt cases
        if key.endswith("_prot.txt"):
            posi_key = key.replace("_prot.txt", "_posi.txt")
        elif key.endswith("_obser.txt"):
            posi_key = key.replace("_obser.txt", "_posi.txt")
        else:
            raise ValueError(
                f"Source file {key} is neither a _prot.txt nor _obs.txt file"
            )
        logger.info(f"Looking for companion posi file: {posi_key}")

        # Get the posi file content from S3
        try:
            response = s3.get_object(Bucket=bucket, Key=posi_key)
            content = response["Body"].read().decode("utf-8")
            logger.info(f"Found posi file: {posi_key}")
            return content
        except s3.exceptions.NoSuchKey:
            logger.error(f"Companion posi file not found: {posi_key}")
            raise FileNotFoundError(f"Companion posi file not found: {posi_key}")

    except Exception as e:
        logger.error(
            f"Error getting posi file content: {str(e)} - We cannot use date lookups. Stopping."
        )
        raise


def parse_posi_file(content):
    """
    Parse the content of a posi file.

    Args:
        content: The content of the posi file as a string.

    Returns:
        A dictionary containing the parsed data.

    Raises:
        ValueError: If the content is not in the expected format.
    """
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


def initialize_resources() -> Tuple[boto3.client, MongoClient, Database]:
    """
    Initialize resources like MongoDB client, S3 client, etc.
    """
    s3_client = boto3.client("s3")
    mongo_client = MongoClient(os.environ["MONGODB_URI"])
    db = mongo_client[os.environ["MONGODB_DATABASE"]]
    return s3_client, mongo_client, db


def get_file_from_s3(s3_client: boto3.client, bucket: str, key: str) -> str:
    """
    Retrieve file content from S3.

    Args:
        s3_client: The S3 client.
        bucket: The S3 bucket name.
        key: The S3 object key.

    Returns:
        The file content as a string.

    Raises:
        FileNotFoundError: If the file is not found in the bucket.
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        logger.info(f"Successfully retrieved file content for key {key}")
        return response["Body"].read().decode("utf-8")

    except ClientError as e:
        print(f"Error retrieving file from S3: {str(e)}")
        raise FileNotFoundError(f"File {key} not found in bucket {bucket}")


def parse_file_content(file_content: str, key: str) -> Dict[str, Any]:
    """
    Parse the file content.

    Args:
        file_content: The file content as a string.
        key: The S3 object key.

    Returns:
        A dictionary containing the parsed data.
    """
    # data parsing logic
    logger.info(f"file_content: {file_content}")

    # split the key into cruise and station:
    cruise_from_name, station_from_name = key.split("_")[0:2]
    logger.info(
        f"From file name we know - cruise: {cruise_from_name}, station: {station_from_name}"
    )

    # split the file content into indivdual lines
    lines = file_content.split("\n")

    # Split the file into header and data
    file_format = "original"
    for aline in lines:
        logger.info(f"Processing input data line: {aline}")
        if aline.startswith("#Date"):  # Detect new format (rerun_XX_obs file)
            file_format = "new"
            logger.info(f"File format: {file_format}")
            header = aline
            data_lines = lines[1:]

            # if the file is a rerun file, cruise and station name are derive from file name:
            cruise = cruise_from_name
            station = station_from_name
            remarks = None
            break  # Exit the loop once we've identified the format

    if file_format == "original":
        # Only for the original observations file:
        logger.info(f"File format: {file_format}")
        header = lines[:12]  # Adjust based on your actual header size
        data_lines = lines[13:]

        # Parse the header
        meta = parse_header(header)
        cruise = meta.get("cruise", "")
        station = meta.get("station", "")
        remarks = meta.get("remarks", "")

    # return parsing results
    logger.info(f"Returning parsed results for header: {header}")

    return {
        "header": header,
        "data_lines": data_lines,
        "cruise": cruise,
        "station": station,
        "remarks": remarks,
        "file_format": file_format,
    }


def prepare_documents(
    ingress_collection: Collection,
    data_lines: List[str],
    file_key: str,
    posi_data: Dict[str, Any],
    cruise: str,
    station: str,
    remarks: str,
    file_format: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Prepare documents for MongoDB insertion.

    Args:
        ingress_collection: The MongoDB collection for ingresses.
        data_lines: The data lines from the file.
        file_key: The S3 object key.
        posi_data: The posi data.
        cruise: The cruise name.
        station: The station name.
        remarks: Any remarks.
        file_format: The file format.

    Returns:
        A list of documents to be inserted into MongoDB.
    """
    date_created = datetime.now(timezone.utc).isoformat()

    # Get the current ingressId
    current_ingress_id = get_current_ingress_id(
        ingress_collection, cruise, station, remarks, date_created
    )
    logger.info(f"Current ingressId: {current_ingress_id}")

    # Prepare documents and collect subLocation coordinates
    video_events = []
    video_start_time = None
    documents = []
    sub_coordinates = []

    for i, line in enumerate(data_lines):
        # Check for empty lines or end marker
        if not line.strip() or line.startswith("End"):
            logger.info(f"Found end of data at line {i}: {line}")
            break  # This will exit the loop

        # logger.info(f"Processing input data line {i}: {line}")
        data_point, video_start_time, video_events = parse_data_line(
            line, file_key, video_start_time, video_events, file_format=file_format
        )

        if data_point:
            prot_time = datetime.strptime(data_point["timestamp"], "%H:%M:%S").time()

            # Find the closest matching timestamp in posi_data
            logger.info("Finding closest matching timestamp in posi: %s", prot_time)
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
            # logger.info(f"Found matching timestamp in posi")

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

            # Before inserting/updating
            document = prepare_for_mongodb(doc)

            # For debugging purposes only
            try:
                logger.info(
                    "Document to be inserted/updated: %s",
                    json.dumps(document, default=datetime_handler),
                )
            except TypeError as e:
                logger.error(f"Error serializing document: {str(e)}")
                continue  # Skip this document

            documents.append(document)
            sub_coordinates.append(doc["subLocation"]["coordinates"])

    # Calculate the bounding box
    bounding_box = calculate_bounding_box(sub_coordinates)

    return documents, bounding_box


def insert_documents_to_mongodb(
    collection: Collection, documents: List[Dict[str, Any]]
) -> List[Any]:
    """
    Upload and insert 'documents' (a.k.a records) to MongoDB Atlas
    collection.

    Args:
        collection_name: The MongoDB collection to insert documents into.
        documents: A list of the documents to be inserted.

    Returns:
        The result of the insertion operation.
    """
    try:
        result = collection.insert_many(documents)
        return result.inserted_ids
    except Exception as e:
        logger.error(f"Error inserting documents into MongoDB: {str(e)}")
        raise


def lambda_handler(event, context):
    """
    Lambda function handler.

    Args:
        event: The event object.
        context: The context object.

    Returns:
        A dictionary containing the status code and the response body.
    """
    logger.info("Lambda function started")
    logger.info(f"Event: {json.dumps(event)}")
    logger.info(f"Context: {context}")

    # Initialize resources
    s3, client, db = initialize_resources()

    # MongoDB (assuming connection string is in environment variable)
    collection = db[os.environ["MONGODB_COLLECTION"]]
    ingress_counter = db[os.environ["INGRESS_COLLECTION_DTIS"]]
    COUNTER_COLLECTION_NAME = ingress_counter

    failed_messages = []

    try:
        for record in event["Records"]:
            try:
                # Parse SQS message body
                message_body = json.loads(record["body"])

                # If it's from S3 event notification
                if "Records" in message_body:
                    for s3_event in message_body["Records"]:
                        bucket_name = s3_event["s3"]["bucket"]["name"]
                        file_key = s3_event["s3"]["object"]["key"]
                        # Process the file
                        # Get file content from S3
                        file_content = get_file_from_s3(s3, bucket_name, file_key)
                        logger.info(f"Processing file: s3://{bucket_name}/{file_key}")

                        # Parse file content
                        documents = parse_file_content(file_content, file_key)

                # If it's your custom message format
                else:
                    bucket_name = message_body["bucket"]
                    file_key = message_body["key"]
                    # Get file content from S3
                    file_content = get_file_from_s3(s3, bucket_name, file_key)
                    logger.info(f"Processing file: s3://{bucket_name}/{file_key}")

                    # Parse file content
                    documents = parse_file_content(file_content, file_key)

                # Process the documents
                (
                    header,
                    data_lines,
                    cruise,
                    station,
                    remarks,
                    file_format,
                ) = documents.values()

                # Get and parse the corresponding posi file
                posi_content = get_posi_file_content(s3, bucket_name, file_key)
                posi_data = parse_posi_file(posi_content) if posi_content else {}

                date_created = datetime.now(timezone.utc).isoformat()
                # Prepare documents and collect subLocation coordinates
                out_documents, bounding_box = prepare_documents(
                    COUNTER_COLLECTION_NAME,
                    data_lines,
                    file_key,
                    posi_data,
                    cruise,
                    station,
                    remarks,
                    file_format,
                )

                # number of inserted documents for summary update in ingresses collection
                len_outdocuments = len(out_documents)
                logger.info(f"Number of documents to be inserted: {len_outdocuments}")

                # Insert documents into MongoDB
                inserted_ids = insert_documents_to_mongodb(collection, out_documents)

                # Update ingress counter
                increment_ingress_id(
                    COUNTER_COLLECTION_NAME,
                    cruise,
                    station,
                    remarks,
                    bounding_box,
                    len_outdocuments,
                    date_created,
                )

            except JSONDecodeError as e:
                # TODO: test this
                logger.exception(f"Error decoding JSON: {str(e)}")
                failed_messages.append(record["messageId"])
            except Exception as e:
                logger.error(f"Error processing document: {str(e)}")
                logger.exception(f"Error processing document: {str(e)}")
                failed_messages.append(record["messageId"])

        if failed_messages:
            return {
                "batchItemFailures": [
                    {"itemIdentifier": msg_id} for msg_id in failed_messages
                ]
            }

        return {
            "statusCode": 200,
            "body": json.dumps("Successfully processed all messages."),
        }
    finally:
        # Ensure the MongoDB connection is closed
        client.close()
