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
* For 2016 files: Prot and posi files need to be both available in an upload, image and video files are implicitly expected, too.
* For 2016 files: Prot and posi files need to be both available in an upload, image and video files are implicitly expected, too.



27 November 2024 Tilmann Steinmetz
27 November 2024 Tilmann Steinmetz

"""

import json
import logging
import os
import re
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


# Define possible date and time formats
DATE_FORMATS = [
    "%m/%d/%Y",  # e.g., "04/16/2022"
    "%m/%d/%Y %H:%M:%S",  # e.g., "04/16/2022 23:08:06"
    "%d.%m.%Y %H:%M:%S",  # e.g., "16.04.2022 23:08:06"
    "%Y-%m-%d %H:%M:%S",  # e.g., "2022-04-16 23:08:06"
    "%d/%m/%Y %H:%M:%S",  # e.g., "16/04/2022 23:08:06"
    "%B %d, %Y %H:%M:%S",  # e.g., "April 16, 2022 23:08:06"
]

TIME_FORMATS = [
    "%H:%M:%S",  # e.g., "23:08:06"
    "%I:%M:%S %p",  # e.g., "11:08:06 PM"
    "%H:%M",  # e.g., "23:08"
]


def parse_datetime(datetime_str: str) -> Optional[str]:
    """
    Attempt to parse a datetime string with multiple formats.
    Parses a datetime string and returns it in ISO 8601 format.

    Args:
        datetime_str (str): The datetime string to parse.

    Returns:
        Optional[str]: The ISO formatted datetime string or None if parsing fails.
    """
    for fmt in DATE_FORMATS:
        try:
            if datetime_str is None:
                return None
            logger.debug("datetime_str datetime: %s", datetime_str)
            parsed_date = datetime.strptime(datetime_str, fmt)
            # Assume UTC timezone if not specified
            try:
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
            logger.debug("Parsed datetime: %s", parsed_date)
            return parsed_date.isoformat()
        except ValueError:
            pass
            logger.debug(f"Invalid datetime format: {datetime_str}. Continuing...")
            # continue

    logger.debug(f"Failed to parse datetime: {datetime_str}")
    return None


def parse_time_only(time_str: str) -> Optional[str]:
    """
    Parses a time string and returns it in HH:MM:SS format.
    Attempt to parse a time-only string with multiple formats
     optionally: assign a default date.

    Args:
        time_str (str): The time string to parse.

    Returns:
        Optional[str]: ISO 8601 formatted string with the current date if
          parsing is successful, else None.
    """
    for fmt in TIME_FORMATS:
        try:
            parsed_time = datetime.strptime(time_str, fmt).time()
            # Assign the current UTC date
            # current_date = datetime.now(timezone.utc).date()
            # combined_datetime = datetime.combine(
            #     current_date, parsed_time, tzinfo=timezone.utc
            # )
            # return combined_datetime.isoformat()
            return parsed_time.isoformat()
        except ValueError:
            logger.warning(f"Invalid time format: {time_str}")
            continue
    logger.error(f"Failed to parse time: {time_str}")
    raise ValueError(f"Invalid time format: {time_str}")
    # return None


def prepare_for_mongodb(document):
    """Convert any datetime/timedelta objects to strings in a document"""
    if isinstance(document, dict):
        return {k: prepare_for_mongodb(v) for k, v in document.items()}
    elif isinstance(document, list):
        return [prepare_for_mongodb(v) for v in document]
    elif isinstance(document, datetime):
        return document.isoformat()
    elif isinstance(document, time):
        return datetime.combine(datetime.today(), document).isoformat()
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


def get_current_ingress_id(
    ingress_collection: str,
    cruise: str,
    station: str,
    remarks: str,
    date_created: datetime,
) -> int:
    """
    Get the current ingressId for a given cruise, station, and remarks.
    If the document does not exist, create it with a value of 0.
    This is used to keep track of the number of ingresses
    for a given cruise/station/remarks.

    Args:
        ingress_collection (Collection): The MongoDB collection for ingresses.
        cruise (str): The cruise identifier.
        station (str): The station identifier.
        remarks (str): The remarks identifier.

    Returns:
        int: The current ingressId value.
    """
    counter = ingress_collection.find_one_and_update(
        {
            "cruise": cruise,
            "station": station,
            "remarks": remarks,
            # "date_created": date_created, # we don't use the date_created
        },
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
                    # if isinstance(date_created, datetime)
                    # else date_created
                )
            },
        }

        # Log the document before insertion
        logger.debug(
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

    # latitudes, longitudes = zip(*coordinates)
    # return {
    #     "min_lat": min(latitudes),
    #     "max_lat": max(latitudes),
    #     "min_lon": min(longitudes),
    #     "max_lon": max(longitudes),
    # }

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
        # logger.debug(f"Fields: {fields}, file_format = {file_format}")
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
        logger.debug(f"Fields: {fields}, file_format = {file_format}")

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
        feature["media"] = f"/images/{voyage_station}/{voyage_station}.jpg"

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
        logger.debug(f"Looking for companion posi file: {posi_key}")

        # Get the posi file content from S3
        try:
            response = s3.get_object(Bucket=bucket, Key=posi_key)
            content = response["Body"].read().decode("utf-8")
            logger.debug(f"Found posi file: {posi_key}")
            return content  # .splitlines()
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
            logger.debug("Date: %s, Time: %s", date, time)
            try:
                dt = datetime.strptime(f"{date} {time}", "%m/%d/%Y %H:%M:%S")
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
                # print(f"Invalid date/time format: {date} {time}. Error: {str(e)}")
                logger.debug(
                    f"Invalid date/time format - Date: {date}; Time {time}. Error: {str(e)}"
                )
                continue  # Skip this line and continue with the next

    return data


def initialize_resources() -> Tuple[boto3.client, MongoClient, Database]:
    """
    Initialize resources like MongoDB client, S3 client, etc.
    """
    s3_client = boto3.client("s3")
    mongo_uri = os.environ.get("MONGODB_URI")
    mongo_db_name = os.environ.get("MONGODB_DATABASE")

    if not mongo_uri or not mongo_db_name:
        logger.error("MongoDB URI or Database name not set in environment variables.")
        raise Exception("MongoDB configuration missing.")

    try:
        mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        mongo_db = mongo_client[mongo_db_name]
        # Test connection
        # mongo_client.admin.command("ping")
    except Exception as e:
        logger.error(f"Error connecting to MongoDB: {e}")
        raise e

    return s3_client, mongo_client, mongo_db


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
        s3_client = boto3.client("s3") if s3_client is None else s3_client
        response = s3_client.get_object(Bucket=bucket, Key=key)
        logger.debug(f"Successfully retrieved file content for key {key}")
        return response["Body"].read().decode("utf-8")

    except ClientError as e:
        print(f"Error retrieving file from S3: {str(e)}")
        raise FileNotFoundError(f"File {key} not found in bucket {bucket}")


def detect_file_format(lines: List[str]) -> str:
    """
    Detects the file format based on header patterns.

    Args:
        lines (List[str]): Lines from the file content.

    Returns:
        str: Format identifier ('original', 'new', 'latest', 'simple').
    """
    dash_line_found = False

    for line in lines:
        stripped_line = line.strip()

        if stripped_line.startswith("---"):
            dash_line_found = True
            continue

        # Multiple header formats start similar - here we distinguish 'original' from 'latest'
        if dash_line_found:
            if stripped_line.startswith("UTC time\tPC time\tLat"):
                return "original"
            elif stripped_line.startswith("#Date\tTime\tPC_Time\tSHIP_Lon"):
                return "latest"
            elif re.match(r"#Date\s+Time\s+PC_Time", stripped_line):
                logger.debug("New file type detected")
                return "new"
            elif stripped_line.startswith(
                "#Date\tTime\tSUB1_Lon\tSUB1_Lat\tID_Number\tID_Name"
            ):
                return "simple"
            else:
                dash_line_found = (
                    False  # Reset if the line after dashes is not a header"
                )
    return "simple"


def parse_original_format(lines: List[str]) -> Dict[str, Any]:
    """
    Parses files adhering to the "original" prot format (the 2006 cruise data like TAN0616).

    Args:
        lines (List[str]): Lines from the file content.

    Returns:
        Dict[str, Any]: Structured data suitable for MongoDB insertion.
    """
    metadata = {}
    detailed_data_table = []
    headers = []
    header_found = False
    data_start_idx = 0

    # Updated delimiter pattern to match lines with any number of dashes
    delimiter_pattern = re.compile(
        r"^-+\s*$"
    )  # Matches lines with only dashes and optional trailing whitespace

    logger.debug("Starting to parse 'original' format file.")

    # # Phase 1: Parse Metadata and Detect Delimiter Line
    # logger.debug("Phase 1: Parsing metadata and detecting delimiter line.")
    # for idx, line in enumerate(lines):
    #     stripped_line = line.strip()

    #     # Skip empty lines
    #     if not stripped_line:
    #         continue

    #     # Check if the line is the delimiter line
    #     if delimiter_pattern.match(stripped_line):
    #         logger.debug(f"Delimiter line found at line {idx}: {line}")
    #         data_start_idx = idx + 1
    #         break  # Proceed to Phase 2

    #     # Check if the line contains a key-value pair separated by a tab
    #     if "\t" in stripped_line:
    #         parts = stripped_line.split("\t", 1)
    #         if len(parts) == 2:
    #             key, value = parts
    #             metadata_key = key.strip().rstrip(":")
    #             metadata_value = value.strip()
    #             metadata[metadata_key] = metadata_value
    #             logger.debug(f"Parsed metadata - {metadata_key}: {metadata_value}")
    #         else:
    #             logger.warning(f"Malformed metadata line at line {idx}: {line}")
    #     else:
    #         # Line does not contain a tab and is not a delimiter; ignore or log as needed
    #         logger.debug(
    #             f"Ignoring non-metadata, non-delimiter line at line {idx}: {line}"
    #         )
    #         continue

    # # Phase 1 Completion Check
    # logger.debug("Phase 1: Metadata parsing completed.")
    # if data_start_idx == 0:
    #     logger.error("Delimiter not found. Cannot proceed to parse data.")
    #     logger.error("Returning metadata only.")
    #     return {"metadata": metadata, "detailed_data_table": detailed_data_table}

    # # Phase 2: Detect Header Line
    # logger.debug("Phase 2: Detecting header line.")
    # for idx in range(data_start_idx, len(lines)):
    #     line = lines[idx].strip()

    #     # Skip empty lines and irrelevant sections
    #     if not line:
    #         continue

    #     # Identify the header line based on known header patterns
    #     # Updated to match the new header starting with "UTC time"
    #     if (
    #         line.startswith("UTC time")
    #         or line.startswith("Date")
    #         or line.startswith("#Date")
    #     ):
    #         headers = line.lstrip("#").split("\t")
    #         headers = [
    #             header.strip() for header in headers
    #         ]  # Remove any surrounding whitespace
    #         header_found = True
    #         logger.debug(f"Data table headers found at line {idx}: {headers}")
    #         data_start_idx = idx + 1
    #         break

    # # Phase 2 Completion Check
    # if not header_found:
    #     logger.error("No header found in 'original' format file.")
    #     logger.error("Returning metadata only.")
    #     return {"metadata": metadata, "detailed_data_table": detailed_data_table}

    # # # Phase 3: Parse Tasks

    # # This code is from parse_latest_format - but here, we don't have a clear task section

    # # logger.debug("Phase 3: Parsing tasks.")
    # # task_headers = [
    # #     "Task",
    # #     "PC Date and Time",
    # #     "UTC Time",
    # #     "UTC Date",
    # #     "SHIP Latitude",
    # #     "SHIP Longitude",
    # #     "SUB_1 Latitude",
    # #     "SUB_1 Longitude",
    # #     "Water Depth",
    # # ]
    # # task_start_idx = 0
    # # for idx, line in enumerate(lines):
    # #     if line.startswith("Task"):
    # #         task_start_idx = idx
    # #         break

    # # for idx in range(task_start_idx, len(lines)):
    # #     line = lines[idx].strip()
    # #     if not line or line.startswith("Gear deployed"):
    # #         continue
    # #     fields = line.split("\t")
    # #     if len(fields) != len(task_headers):
    # #         continue
    # #     task = dict(zip(task_headers, fields))
    # #     # Convert PC Date and Time to ISO 8601 format
    # #     if "PC Date and Time" in task:
    # #         try:
    # #             task["PC Date and Time"] = datetime.strptime(
    # #                 task["PC Date and Time"], "%d/%m/%Y %H:%M:%S"
    # #             ).isoformat()
    # #             task["PC Date and Time"] = parse_datetime(task["PC Date and Time"])
    # #         except ValueError as e:
    # #             logger.error(
    # #                 "Failed to parse datetime: PC Date and Time %s \n%s",
    # #                 task["PC Date and Time"],
    # #                 e,
    # #             )
    # #             continue
    # #     tasks.append(task)

    # # Phase 4: Parse Data Rows
    # logger.debug("Phase 4: Parsing data rows ifrom data_start_idx %s.", data_start_idx)
    # for data_idx, data_line in enumerate(lines[data_start_idx:], start=data_start_idx):
    #     stripped_data_line = data_line.strip()

    #     # Skip empty lines
    #     if not stripped_data_line:
    #         continue

    #     # Skip footer or unexpected sections
    #     if stripped_data_line.startswith("#") or delimiter_pattern.match(
    #         stripped_data_line
    #     ):
    #         logger.debug("Skipping non-data line at line %s: %s", data_idx, data_line)
    #         continue

    #     # Split the data line based on tabs
    #     fields = stripped_data_line.split("\t")

    #     if len(fields) != len(headers):
    #         logger.warning(
    #             "Data line does not match header count at line  %s: %s",
    #             data_idx,
    #             data_line,
    #         )
    #         continue

    #     record = dict(zip(headers, fields))
    #     parsed_record = {}

    #     # Convert and assign fields
    #     for header in headers:
    #         logger.debug("Parsing header %s", header)
    #         value = record.get(header, "").strip()

    #         if header.lower() == "date" or "date" in header.lower():
    #             # Parse date field (adjust format as needed)
    #             try:
    #                 parsed_value = (
    #                     datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    #                 )
    #             except ValueError:
    #                 try:
    #                     parsed_value = (
    #                         datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    #                     )
    #                 except ValueError:
    #                     try:
    #                         parsed_value = (
    #                             datetime.strptime(value, "%d.%m.%Y").date().isoformat()
    #                         )
    #                     except ValueError:
    #                         logger.warning(
    #                             "Failed to parse Date in (latest file format) at line %s: %s",
    #                             data_idx,
    #                             value,
    #                         )
    #                         parsed_value = value  # Keep as string if parsing fails
    #             parsed_record[header] = parsed_value
    #         elif header.lower() == "utc time" or header.lower() == "time":
    #             logger.debug("Parsing time field '%s'", header)
    #             # Parse time field
    #             try:
    #                 parsed_value = (
    #                     datetime.strptime(value, "%H:%M:%S").time().isoformat()
    #                 )
    #             except ValueError:
    #                 logger.warning(
    #                     "Failed to parse Time (in latest format) at line %s: %s",
    #                     data_idx,
    #                     value,
    #                 )
    #                 parsed_value = value  # Keep as string if parsing fails
    #             parsed_record[header] = parsed_value
    #         elif header.lower() in ["pc time", "pc_time"]:
    #             logger.debug("Parsing time field '%s'", header)
    #             # Parse PC Time field
    #             try:
    #                 parsed_value = datetime.strptime(
    #                     value, "%d/%m/%Y %H:%M:%S"
    #                 ).isoformat()
    #             except ValueError:
    #                 try:
    #                     parsed_value = datetime.strptime(
    #                         value, "%m/%d/%Y %H:%M:%S"
    #                     ).isoformat()
    #                 except ValueError:
    #                     try:
    #                         parsed_value = datetime.strptime(
    #                             value, "%d.%m.%Y %H:%M:%S"
    #                         ).isoformat()
    #                     except ValueError:
    #                         logger.warning(
    #                             "Failed to parse PC_Time at line %s: %s",
    #                             data_idx,
    #                             value,
    #                         )
    #                         parsed_value = value
    #             parsed_record[header] = parsed_value
    #         elif any(
    #             sub in header.lower()
    #             for sub in [
    #                 "lon",
    #                 "lat",
    #                 "speed",
    #                 "course",
    #                 "depth",
    #                 "heading",
    #                 "sub lat",
    #                 "sub lon",
    #             ]
    #         ):

    #             # Convert numeric fields to floats
    #             # Handle cases where values might have colons instead of dots (e.g., -39:28.509)
    #             value = value.replace(":", ".")
    #             try:
    #                 parsed_record[header] = float(value)
    #                 logger.debug("Parsing field '%s'", parsed_record[header])
    #             except ValueError:
    #                 logger.warning(
    #                     "Non-numeric value for '%s' at line %s: %s",
    #                     header,
    #                     data_idx,
    #                     value,
    #                 )
    #                 parsed_record[header] = None
    #         else:
    #             # Keep other fields as strings
    #             parsed_record[header] = value

    #     detailed_data_table.append(parsed_record)
    #     logger.debug("Parsed data record at line %s, %s", data_idx, parsed_record)

    # return {
    #     "metadata": metadata,
    #     # "tasks": tasks,
    #     "detailed_data_table": detailed_data_table,
    # }
    parsed_data = parse_metadata(lines)
    headers, header_idx = detect_header_line(lines, parsed_data[1])
    # tasks = parse_tasks(lines, header_idx)
    observations = parse_data_rows(lines, header_idx, headers)

    # Extract coordinate pairs
    coordinate_keys = [
        "SHIP_Lat",
        "SHIP_Lon",
        "SUB1_Lat",
        "SUB1_Lon",
    ]  # Update based on actual keys
    coordinate_keys = [
        "SHIP_Lat",
        "SHIP_Lon",
        "SUB1_Lat",
        "SUB1_Lon",
    ]  # Update based on actual keys
    coordinates = []
    for obs in observations:
        try:
            lat = float(obs.get("SHIP_Lat", 0))
            lon = float(obs.get("SHIP_Lon", 0))
            coordinates.append((lat, lon))

            # If there are SUB1 coordinates
            sub_lat = float(obs.get("SUB1_Lat", 0))
            sub_lon = float(obs.get("SUB1_Lon", 0))
            coordinates.append((sub_lat, sub_lon))
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid coordinate data in observation: {obs}. Error: {e}")
            continue

    # Calculate bounding box
    if coordinates:
        bounding_box = calculate_bounding_box(coordinates)
        logger.debug(f"Calculated Bounding Box: {bounding_box}")
    else:
        bounding_box = None
        logger.warning("No valid coordinates found to calculate bounding box.")

    return [
        {
            "metadata": parsed_data[0],
            "bounding_box": bounding_box,
            # "tasks": tasks,
            "detailed_data_table": observations,
        }
    ]


"""
refactored code from the original lambda function:

parse_metadata: Parses the metadata section and detects the delimiter line.
detect_header_line: Detects the header line based on known patterns.
parse_tasks: Parses the tasks section.
parse_data_rows: Parses the data rows based on the detected headers.
parse_latest_format: Combines the above functions to parse the entire file.
"""


def parse_metadata(lines: List[str]) -> Tuple[Dict[str, str], int]:
    """
    Parses the metadata section and detects the delimiter line.
    """
    logger.debug("Parsing metadata section.")
    metadata = {}
    delimiter_pattern = re.compile(r"^-+$")
    data_start_idx = 0

    for idx, line in enumerate(lines):
        stripped_line = line.strip()

        if not stripped_line:
            continue

        if delimiter_pattern.match(stripped_line):
            data_start_idx = idx + 1
            break

        if ":" in stripped_line:
            parts = stripped_line.split(":", 1)
            if len(parts) == 2:
                key, value = parts
                metadata_key = key.strip()
                metadata_value = value.strip()
                if metadata_key != "Task":
                    metadata[metadata_key] = metadata_value
    logger.debug(f"Extracted metadata: {metadata}, data_start_idx: {data_start_idx}")
    return metadata, data_start_idx


def detect_header_line(lines: List[str], start_idx: int) -> Tuple[List[str], int]:
    """
    Detects the header line based on known patterns.
    """
    logger.debug("Detecting header line.")
    headers = []
    header_found = False

    # task_start_idx = -1
    for idx in range(start_idx, len(lines)):
        line = lines[idx].strip()

        if not line:
            continue

        if (
            line.startswith("UTC time")
            or line.startswith("Date")
            or line.startswith("#Date")
        ):
            logger.debug("Line content at idx: %s", line)
            headers = line.lstrip("#").split("\t")
            headers = [header.strip() for header in headers]
            header_found = True
            return headers, idx + 1

    if header_found:
        logger.debug(f"Detected headers: {headers} at line {idx}")
    return headers, start_idx


def parse_tasks(lines: List[str], start_idx: int) -> List[Dict[str, str]]:
    """
    Parses the tasks section.

    Args:
        lines (List[str]): Lines from the text file.
        start_idx (int): The index to start searching for tasks.

    Returns:
        List[Dict[str, str]]: A list of task dictionaries.
    """
    tasks = []
    task_headers = [
        "Task",
        "PC Date and Time",
        "UTC Time",
        "UTC Date",
        "SHIP Latitude",
        "SHIP Longitude",
        "SUB_1 Latitude",
        "SUB_1 Longitude",
        "Water Depth",
    ]

    # Compile regex patterns for matching task lines

    # Pattern Breakdown:
    # ^(Task|Tasks): Asserts that the line starts with either "Task" or "Tasks".
    # [ \t]*: Matches zero or more spaces or tabs. This ensures that any combination of spaces and tabs between "Task(s)" and the colon is accounted for.
    # :: Matches the colon character.
    # [ \t]*: Matches zero or more spaces or tabs after the colon.
    # (.+): Captures the rest of the line after the colon. This is the task description.

    task_pattern = re.compile(r"^(Task|Tasks)[ \t]*:[ \t]*(.+)", re.IGNORECASE)

    for idx in range(start_idx, len(lines)):
        line = lines[idx].strip()
        match = task_pattern.match(line)
        if match:
            continue  # Skip the header line
        if line.startswith(
            "----------------------------------------------------------------"
        ) or line.startswith("UTC time"):
            break  # End of tasks section

        fields = re.split(r"[ \t]{2,}", line)
        if len(fields) != len(task_headers):
            logger.warning(f"Skipping malformed task line {idx}: {line}")
            continue

        task = dict(zip(task_headers, fields))

        # Parse and format datetime fields using helper functions
        task["PC Date and Time"] = parse_datetime(task.get("PC Date and Time", ""))
        task["UTC Time"] = parse_time_only(task.get("UTC Time", ""))
        task["UTC Date"] = parse_datetime(task.get("UTC Date", ""))

        tasks.append(task)
        logger.debug(f"Parsed task at line {idx}: {task}")

    return tasks


def parse_data_rows(
    lines: List[str], start_idx: int, headers: List[str]
) -> List[Dict[str, Any]]:
    """
    Parses the data rows based on the detected headers.

    Args:
        lines (List[str]): Lines containing data.
        start_idx (int): The starting index for parsing.
        headers (List[str]): List of header names.

    Returns:
        List[Dict[str, Any]]: List of parsed data records.
    """
    logger.debug("Parsing data rows.")

    # detailed_data_table = []
    # delimiter_pattern = re.compile(r"^-+$")
    observations = []

    for idx in range(start_idx, len(lines)):
        line = lines[idx].strip()
        if not line:
            logger.debug("Skipping empty line at index %s.", idx)
            continue  # Skip empty lines

        fields = line.split("\t")
        # Check if the number of fields matches the number of headers
        if len(fields) != len(headers):
            logger.warning("Skipping malformed data line %s, %s", idx, line)
            # continue   # we can skip this line and continue with the next
            # but as some of our file formats do not have headers for all columns
            # we may want to  continue parsing

        observation = dict(zip(headers, fields))

        # Parse datetime fields
        observation["PC_Time"] = parse_datetime(observation.get("PC_Time", ""))
        observation["Date"] = parse_datetime(observation.get("Date", ""))
        observation["Time"] = parse_time_only(observation.get("Time", ""))

        for i, (header, part) in enumerate(zip(headers, fields)):
            header = header.strip()
            part = part.strip()
            if header == "DateTime":
                # Combine Date and Time into ISO format
                try:
                    date_time_obj = datetime.strptime(part, "%m/%d/%Y %H:%M:%S")
                    observation[header] = date_time_obj.isoformat()
                except ValueError as ve:
                    logger.error(
                        "Failed to parse DateTime at line %s: %s",
                        idx,
                        part,
                    )
                    observation[header] = part  # Keep original string if parsing fails

        # Ensure numeric fields are returned as strings
        for key in [
            "SHIP_Lon",
            "SHIP_Lat",
            "SHIP_SOG",
            "SHIP_COG",
            "SHIP_Hdg",
            "Water_Depth",
            "SUB1_Lon",
            "SUB1_Lat",
            "SUB1_Depth",
            "SUB1_Altitude",
            "ID_Number",
        ]:
            if key in observation:
                try:
                    observation[key] = str(observation[key])
                except ValueError:
                    observation[key] = None
                    logger.warning(
                        "Failed to convert '%s' to float at line %s: %s",
                        key,
                        idx,
                        observation[key],
                    )
            # else:
            #     observation[key] = observation[key]

        observations.append(observation)
        logger.debug("Parsed record at line %s: %s", idx, observation)

    logger.debug(f"Parsed {len(observations)} data rows.")

    return observations


def parse_latest_format(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Parses the latest format of the text file.
    Combines separate parsing functions to parse the entire file.

    Args:
        lines (List[str]): Lines from the text file content.

    Returns:
        List[Dict[str, Any]]: A list of structured data suitable for MongoDB insertion.
        metadata: Metadata dictionary.
        bounding_box: Bounding box coordinates (of all events parsed for this station).
        bounding_box: Bounding box coordinates (of all events parsed for this station).
        detailed_data_table: List of observation dictionaries.


    """
    logger.debug("Searching for METADATA. Parsing 'latest' format file.")
    parsed_data = parse_metadata(lines)

    logger.debug("Searching for HEADER. Parsing 'latest' format file.")
    headers, header_idx = detect_header_line(lines, parsed_data[1])
    logger.debug(
        "Finished Searching for HEADER at datastartidx %s. Parsing 'latest' format file.",
        header_idx,
    )
    if not headers:
        logger.error("Header detection failed. Returning empty data.")
        return []

    logger.debug("Parsing DATA ROWS. Parsing 'latest' format file.")
    observations = parse_data_rows(lines, header_idx, headers)

    # Extract coordinate pairs
    # coordinate_keys = ["SHIP_Lat", "SHIP_Lon", "SUB1_Lat", "SUB1_Lon"]  # Update based on actual keys
    coordinates = []
    for obs in observations:
        try:
            lat = float(obs.get("SHIP_Lat", 0))
            lon = float(obs.get("SHIP_Lon", 0))
            coordinates.append((lat, lon))

            # If there are SUB1 coordinates
            sub_lat = float(obs.get("SUB1_Lat", 0))
            sub_lon = float(obs.get("SUB1_Lon", 0))
            coordinates.append((sub_lat, sub_lon))
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid coordinate data in observation: {obs}. Error: {e}")
            continue

    # Calculate bounding box
    if coordinates:
        bounding_box = calculate_bounding_box(coordinates)
        logger.debug(f"Calculated Bounding Box: {bounding_box}")
    else:
        bounding_box = None
        logger.warning("No valid coordinates found to calculate bounding box.")

    return [
        {
            "metadata": parsed_data[0],
            "bounding_box": bounding_box,
            "detailed_data_table": observations,
        }
    ]


# def parse_simple_format(lines: List[str]) -> List[Dict[str, Any]]:
#     """
#     Parses files adhering to the "simple" format.

#     Args:
#         lines (List[str]): Lines from the file content.


#     Returns:
#         List[Dict[str, Any]]: List of Structured data docs suitable for MongoDB insertion.
#         (metadata, detailed_data_table)
#     """
#     logger.debug("Parsing 'simple' format file.")
def parse_simple_format(lines: List[str]) -> Dict[str, Any]:
    """
    Parses files adhering to the "simple" format.

    Args:
        lines (List[str]): Lines from the file content.

    Returns:
        Dict[str, Any]: Structured data with empty metadata and detailed data table suitable for MongoDB insertion.
    """
    logger.debug("Parsing 'simple' format file.")
    metadata = {}
    observations = []

    if not lines:
        logger.error("Input lines are empty.")
        return {
            "metadata": metadata,
            "detailed_data_table": observations,
        }

    # Parse header from the first line
    header = lines[0].strip()
    logger.debug("Simple format Header: %s", header)

    if not header.startswith("#"):
        logger.error("Header line does not start with '#': %s", header)
        return {
            "metadata": metadata,
            "detailed_data_table": observations,
        }

    # Remove '#' and split by tab to get columns
    columns = header.lstrip("#").split("\t")
    logger.debug("Columns before combining Date and Time: %s", columns)

    # Check if the first two columns are 'Date' and 'Time'
    if len(columns) >= 2 and columns[0] == "Date" and columns[1] == "Time":
        # Combine 'Date' and 'Time' into 'DateTime'
        columns = ["DateTime"] + columns[2:]
        logger.debug("Columns after combining Date and Time: %s", columns)
    else:
        logger.warning(
            "Expected first two columns to be 'Date' and 'Time'. Columns: %s", columns
        )
        logger.warning(
            "Expected first two columns to be 'Date' and 'Time'. Columns: %s", columns
        )

    # Parse data lines starting from the second line
    data_lines = lines[1:]
    logger.debug("Number of data lines to parse: %d", len(data_lines))

    # Use existing parse_data_rows function with updated columns
    observations = parse_data_rows(data_lines, 0, columns)

    logger.debug("Parsed %d data records.", len(observations))

    return {
        "metadata": metadata,
        "detailed_output_table": observations,
    }


def parse_file_content(
    file_content: str, key: str, ingress_collection: Collection
) -> Tuple[
    List[Dict[str, Any]],  # List of documents
    str,  # file_format,
    Optional[Tuple[float, float, float, float]],  # bounding_box
]:
    """
    Parses the file content and returns a list of documents
    and the file format.

    Args:
        file_content: The file content as a string.
        key: The S3 object key.
        ingress_collection: The MongoDB collection for ingresses.

    Returns:
        List[Dict[str, Any]]: A list of parsed documents.
        file_format (from detection algorithm).

    """
    logger.debug(f"file_content: {file_content[:100]}...")

    try:
        cruise_from_name, station_from_name = key.split("_")[0:2]
        cruise_from_name = cruise_from_name.split("/")[0]
    except ValueError:
        logger.error(f"Invalid key format: {key}")
        return {}

    logger.debug(
        "From file name we know - cruise: %s, station: %s",
        cruise_from_name,
        station_from_name,
    )

    # split the file content into indivdual lines
    lines = file_content.splitlines()

    # Detect file format
    file_format = detect_file_format(lines)
    logger.info(
        "Detected file format (in 'parse_file_content'): %s",
        file_format,
    )

    # Parse based on file format:
    if file_format == "original":
        logger.info("Parsing 'original' format file.")
        parsed_data_list = parse_original_format(lines)
        documents = []
    elif file_format == "latest":
        logger.info("Parsing 'latest' format file.")
        parsed_data_list = parse_latest_format(lines)
        documents = []
    elif file_format == "simple":
        logger.info("Parsing 'simple' format file.")
        parsed_data_list = parse_simple_format(lines)
        documents = []
    else:
        logger.error("Unknown file format - cannot parse.")
        return []

    # Prepare documents for MongoDB insertion
    for parsed_data in parsed_data_list:
        logging.debug("Preparing document for MongoDB insertion. %s", parsed_data)
        document = prepare_documents(parsed_data, key, ingress_collection)
        if document:
            documents.append(document)

    # # We will return the bounding box from the last parsed document
    # bounding_box = parsed_data.get("bounding_box")

    if not documents:
        logger.error("No parsed data found to create documents.")

    return documents, file_format


def prepare_documents(
    parsed_data: Dict[str, Any], file_key: str, ingress_collection: Optional[Collection]
) -> List[Dict[str, Any]]:
    """
    Prepares a document for MongoDB insertion based on the parsed data .

    Args:
        parsed_data (Dict[str, Any]): The data parsed from the input file.
        file_key (str): The S3 key of the input file.
        ingress_collection (Optional[Collection]): MongoDB collection for ingresses.

    Returns:
        List[Dict[str, Any]]: A list of structured documents ready for MongoDB insertion
        (or None if preparation fails).
    """
    metadata = parsed_data.get("metadata", {})
    bounding_box = parsed_data.get("bounding_box")
    observations = parsed_data.get("detailed_data_table", [])

    # Initialize the list of documents
    documents = []

    logger.debug("Preparing document for MongoDB insertion.")
    logger.info("Assembling document")

    # Extracted metadata
    logger.info("Extracted metadata: %s", metadata)

    # Extracted bounding box (coordinates)
    logger.info("Extracted bounding box: %s", str(bounding_box))

    # Extract detailed data table (observations)
    logger.info("Extracted %s observations.", len(observations))

    # Initialize the list of documents
    documents = []

    logger.debug("Preparing document for MongoDB insertion.")
    logger.info("Assembling document")

    # Extracted metadata
    logger.info("Extracted metadata: %s", metadata)

    # Extracted bounding box (coordinates)
    logger.info("Extracted bounding box: %s", str(bounding_box))

    # Extract detailed data table (observations)
    logger.info("Extracted %s observations.", len(observations))

    # Get the current ingressId
    current_ingress_id = 1

    # Extract ingressID from  MongoDB (using ingress_collection)
    if ingress_collection is not None:
        try:
            current_ingress_id = get_current_ingress_id(
                ingress_collection,
                metadata.get("Cruise"),
                metadata.get("Station"),
                metadata.get("Remarks"),
                datetime.now(timezone.utc),
            )
            logger.debug(
                "Updated ingress document with ingress_id: %s",
                current_ingress_id,
            )
        except Exception as e:
            logger.error("Failed to get current ingressId: %s", e)
            return []  # Return empty list if ingressId retrieval fails
        finally:
            logger.debug("Current ingressId: %s", current_ingress_id)

    # increment ingress id
    count_documents = len(parsed_data.get("detailed_data_table", []))

    increment_ingress_id(
        ingress_collection,
        metadata.get("Cruise"),
        metadata.get("Station"),
        metadata.get("Remarks"),
        bounding_box,
        count_documents,
        datetime.now(timezone.utc),
    )

    # Initialize default values
    try:
        first_data = parsed_data["detailed_data_table"][0]
        ship_lon = float(first_data.get("SHIP Longitude", 0.0))
        ship_lat = float(first_data.get("SHIP Latitude", 0.0))
        sub1_lon = float(first_data.get("SUB_1 Longitude", 0.0))
        sub1_lat = float(first_data.get("SUB_1 Latitude", 0.0))
        ship_sog = float(first_data.get("SHIP SOG", 0.0))
        ship_cog = float(first_data.get("SHIP COG", 0.0))
        ship_hdg = float(first_data.get("SHIP Hdg", 0.0))
        water_depth = float(first_data.get("Water Depth", 0.0))
        sub1_depth = float(first_data.get("SUB1_Depth", 0.0))
    except (ValueError, KeyError, IndexError) as e:
        logger.warning(f"Invalid or missing data in detailed_data_table: {e}")
        # Assign default values
        ship_lon, ship_lat, sub1_lon, sub1_lat = 0.0, 0.0, 0.0, 0.0
        ship_sog, ship_cog, ship_hdg, water_depth, sub1_depth = 0.0, 0.0, 0.0, 0.0, 0.0

    for observation in observations:
        # Initialize the document
        document = {
            # "file_key": file_key,
            # "meta": {
            #     "cruiseStationId": str(ObjectId()),  # Generate a unique ID
            #     "cruise": metadata.get("Cruise"),
            #     "station": metadata.get("Station"),
            #     "remarks": metadata.get("Remarks"),
            #     "ingressId": 1,  # This can be dynamically assigned as needed
            #     "created_at": datetime.now(timezone.utc).isoformat(),
            # },
            "file_key": file_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
            "bounding_box": bounding_box,
            "timestamp": observation.get("PC_Time"),
            "shipLocation": {
                "type": "Point",
                "coordinates": [
                    float(observation.get("SHIP_Lon", 0.0)),
                    float(observation.get("SHIP_Lat", 0.0)),
                ],
            },
            "speed": float(observation.get("SHIP_SOG", 0.0)),
            "course": float(observation.get("SHIP_COG", 0.0)),
            "heading": float(observation.get("SHIP_Hdg", 0.0)),
            "depth": float(observation.get("Water_Depth", 0.0)),
            "subLocation": {
                "type": "Point",
                "coordinates": [
                    float(observation.get("SUB1_Lon", 0.0)),
                    float(observation.get("SUB1_Lat", 0.0)),
                ],
            },
            "subDepth": float(observation.get("SUB1_Depth", 0.0)),
            "feature":
            # observation,  # Assign observation based on 'detailed_data_table' content
            {
                "media": "video",
                "mediaType": "video",
                "mediaOffset": 0,
                "observation": "Observations/Comments",
                "observation2": observation.get("Image/Video Path", "Some video"),
                "observation_source": file_key,
                "observationRef": "<a href='https://www.marinespecies.org/rest/'>Link</a>",
            },
        }
        documents.append(document)
        logger.debug(f"Prepared document for observation: {document}")

    # if not document["tasks"]:
    #     logger.warning("No tasks found in the parsed data.")
    #     document["tasks"] = []  # Or set to None, based on your schema

    # # logger.debug("Prepared document: %s", json.dumps(document, indent=2))
    # logger.debug(f"Prepared document: {document}")
    # return document

    logger.info(f"Total documents prepared for insertion: {len(documents)}")
    return documents


def insert_documents_to_mongodb(
    collection: Collection, documents: List[Dict[str, Any]]
) -> List[Any]:
    """
    Upload and insert 'documents' (a.k.a records) to MongoDB Atlas
    collection.

    Args:
        collection (Collection): The MongoDB collection where documents will be inserted.
        documents List[Dict[str, Any]]: A list of documents to insert.

    Returns:
        List[Any]: A list of inserted document IDs.
    """
    if not documents:
        logger.warning("No documents to insert.")
        return []

    try:
        result = collection.insert_many(documents, ordered=False)
        logger.info(f"Inserted {len(documents)} documents into MongoDB.")
        return result.inserted_ids
    except Exception as e:
        logger.error(f"Error inserting documents into MongoDB: {str(e)}")
        raise e


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))
    try:
        s3_client, mongo_client, db = initialize_resources()
        collection = db[os.environ["MONGODB_COLLECTION"]]
        ingress_collection = db[os.environ["INGRESS_COLLECTION_DTIS"]]

        all_documents = []  # Collect all documents to insert at once

        for record in event["Records"]:
            try:
                # Parse SQS message body
                message_body = json.loads(record["body"])
                logger.info(f"Processing message body: {message_body}")

                # If it's from S3 event notification
                if "Records" in message_body:
                    for s3_event in message_body["Records"]:
                        bucket_name = s3_event["s3"]["bucket"]["name"]
                        file_key = s3_event["s3"]["object"]["key"]
                        logger.info(
                            "Processing S3 file - Bucket: %s, Key: %s",
                            bucket_name,
                            file_key,
                        )

                        # Get file content from S3
                        file_content = get_file_from_s3(
                            s3_client=None,  # Replace with your S3 client if needed
                            bucket=bucket_name,
                            key=file_key,
                        )

                        logger.debug(
                            f"file_content: {file_content[:100]}..."
                        )  # Log first 100 chars for brevity

                        # Parse file content
                        documents, file_format = parse_file_content(
                            file_content,
                            file_key,
                            ingress_collection,  # Pass the ingress collection
                        )

                        all_documents.extend(documents)

                # If it's your custom message format
                else:
                    bucket_name = message_body["bucket"]
                    file_key = message_body["key"]
                    if not bucket_name or not file_key:
                        logger.warning(
                            "Missing 'bucket' or 'key' in message body: %s",
                            message_body,
                        )
                        continue
                    logger.info(
                        "Processing custom message - Bucket: %s, Key: %s",
                        bucket_name,
                        file_key,
                    )

                    # Get file content from S3
                    file_content = get_file_from_s3(
                        s3_client,
                        bucket_name,
                        file_key,
                    )

                    # Parse the file content
                    documents, file_format = parse_file_content(
                        file_content,
                        file_key,
                        ingress_collection,  # Pass the ingress collection
                    )
                    # parsed_data_list = parse_latest_format(file_content.splitlines())

                    # Get the ingress collection
                    ingress_collection = db[os.environ["INGRESS_COLLECTION_DTIS"]]
                    all_documents.extend(documents)

                    # # Prepare and insert documents
                    # all_documents = []
                    # for parsed_data in parsed_data_list:
                    #     documents = prepare_documents(
                    #         parsed_data, file_key, ingress_collection
                    #     )
                    #     logger.debug(f"Prepared documents: {documents}")
                    #     all_documents.extend(documents)

                    # inserted_ids = insert_documents_to_mongodb(
                    #     db[os.environ["MONGODB_COLLECTION"]], all_documents
                    # )

                    # return {
                    #     "statusCode": 200,
                    #     "body": json.dumps(
                    #         f"Inserted {len(inserted_ids)} documents successfully!"
                    #     ),
                    # }

            except Exception as e:
                logger.error(f"Error processing record: {str(e)}")
                # Optionally, handle failed records
                continue

        if all_documents:
            insert_documents_to_mongodb(collection, all_documents)
            logger.info(f"Inserted {len(all_documents)} documents into MongoDB.")
        else:
            logger.info("No documents to insert.")

        mongo_client.close()
        return {
            "statusCode": 200,
            "body": json.dumps("Successfully processed all records."),
        }

    except Exception as e:
        logger.error("Error processing event: %s; \n%s", str(e), documents)
        return {
            "statusCode": 500,
            "body": json.dumps("An error occurred."),
        }
