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


14 November 2024 Tilmann Steinmetz

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
    "%m/%d/%Y %H:%M:%S",  # e.g., "04/16/2022 23:08:06"
    "%d.%m.%Y %H:%M:%S",  # e.g., "16.04.2022 23:08:06"
    "%Y-%m-%d %H:%M:%S",  # e.g., "2022-04-16 23:08:06"
    "%d/%m/%Y %H:%M:%S",  # e.g., "16/04/2022 23:08:06"
    # "%B %d, %Y %H:%M:%S",  # e.g., "April 16, 2022 23:08:06"
]

TIME_FORMATS = [
    "%H:%M:%S",  # e.g., "23:08:06"
    "%I:%M:%S %p",  # e.g., "11:08:06 PM"
    # "%H:%M",  # e.g., "23:08"
]


def parse_datetime(datetime_str: str) -> Optional[str]:
    """
    Attempt to parse a datetime string with multiple formats.

    Args:
        datetime_str (str): The datetime string to parse.

    Returns:
        Optional[str]: ISO 8601 formatted string if parsing is successful, else None.
    """
    for fmt in DATE_FORMATS:
        try:
            parsed_date = datetime.strptime(datetime_str, fmt)
            # Assume UTC timezone if not specified
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            return parsed_date.isoformat()
        except ValueError:
            continue
    logger.error(f"Failed to parse datetime: {datetime_str}")
    return None


def parse_time_only(time_str: str) -> Optional[str]:
    """
    Attempt to parse a time-only string with multiple formats and assign a default date.

    Args:
        time_str (str): The time string to parse.

    Returns:
        Optional[str]: ISO 8601 formatted string with the current date if parsing is successful, else None.
    """
    for fmt in TIME_FORMATS:
        try:
            parsed_time = datetime.strptime(time_str, fmt).time()
            # Assign the current UTC date
            current_date = datetime.now(timezone.utc).date()
            combined_datetime = datetime.combine(
                current_date, parsed_time, tzinfo=timezone.utc
            )
            return combined_datetime.isoformat()
        except ValueError:
            continue
    logger.error(f"Failed to parse time: {time_str}")
    return None


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
                print(f"Invalid date/time format: {date} {time}. Error: {str(e)}")
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
        response = s3_client.get_object(Bucket=bucket, Key=key)
        logger.info(f"Successfully retrieved file content for key {key}")
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
    for line in lines:
        if line.startswith("#Date\tTime\tPC_Time"):
            return "latest"
        elif line.startswith("#Date\tTime\tSUB1_Lon"):
            return "simple"
        elif re.match(r"#Date\s+Time\s+PC_Time", line):
            return "original"
    return "unknown"


def parse_original_format(lines: List[str]) -> Dict[str, Any]:
    metadata = {}
    descriptive_text = ""
    detailed_data_table = []

    # Parse metadata
    for idx, line in enumerate(lines):
        if line.strip() == "":
            start_idx = idx + 1
            break
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    # Parse detailed data table
    header = lines[start_idx + 1]
    columns = header.split("\t")
    for line in lines[start_idx + 2 :]:
        parts = line.split("\t")
        if len(parts) < len(columns):
            continue
        record = dict(zip(columns, parts))
        detailed_data_table.append(prepare_for_mongodb(record))

    return {
        "metadata": metadata,
        "descriptive_text": descriptive_text,
        "detailed_data_table": detailed_data_table,
    }


def parse_latest_format(lines: List[str]) -> Dict[str, Any]:
    metadata = {}
    descriptive_text = ""
    task_table = []
    detailed_data_table = []

    # Parse metadata
    for idx, line in enumerate(lines):
        if line.strip() == "":
            break
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    # Identify sections
    task_header_idx = (
        lines.index(
            "Task             :\tPC Date and Time\tUTC Time\tUTC Date\tSHIP Latitude\tSHIP Longitude\tSUB_1 Latitude\tSUB_1 Longitude\tWater Depth"
        )
        + 1
    )
    detailed_header_idx = (
        lines.index(
            "#Date\tTime\tPC_Time\tSHIP_Lon\tSHIP_Lat\tSHIP_SOG\tSHIP_COG\tSHIP_Hdg\tWater_Depth\tSUB1_Lon\tSUB1_Lat\tSUB1_Depth\tSUB1_Altitude\tElapsed video Time\tObservations/Comments\tImage-Video Path"
        )
        + 1
    )

    # Parse Task Table
    for line in lines[task_header_idx : detailed_header_idx - 1]:
        parts = line.split("\t")
        if len(parts) < 9:
            continue
        record = {
            "Task": parts[0],
            "PC_Date_and_Time": parse_datetime(parts[1]),
            "UTC_Time": parse_time_only(parts[2]),
            "UTC_Date": parse_datetime(parts[3]),
            "SHIP_Latitude": float(parts[4]),
            "SHIP_Longitude": float(parts[5]),
            "SUB_1_Latitude": float(parts[6]) if parts[6] else None,
            "SUB_1_Longitude": float(parts[7]) if parts[7] else None,
            "Water_Depth": float(parts[8]),
        }
        task_table.append(record)

    # Parse Detailed Data Table
    for line in lines[detailed_header_idx:]:
        parts = re.split(r"\t+", line)
        if len(parts) < 16:
            continue
        record = {
            "Date": parse_datetime(parts[0]),
            "Time": parse_time_only(parts[1]),
            "PC_Time": parse_datetime(parts[2]),
            "SHIP_Lon": float(parts[3]),
            "SHIP_Lat": float(parts[4]),
            "SHIP_SOG": float(parts[5]),
            "SHIP_COG": float(parts[6]),
            "SHIP_Hdg": float(parts[7]),
            "Water_Depth": float(parts[8]),
            "SUB1_Lon": float(parts[9]) if parts[9] else None,
            "SUB1_Lat": float(parts[10]) if parts[10] else None,
            "SUB1_Depth": float(parts[11]) if parts[11] else None,
            "SUB1_Altitude": float(parts[12]) if parts[12] else None,
            "Elapsed_video_Time": parts[13],
            "Observations_Comments": parts[14],
            "Image_Video_Path": parts[15] if parts[15] else None,
        }
        detailed_data_table.append(record)

    return {
        "metadata": metadata,
        "descriptive_text": descriptive_text,
        "task_table": task_table,
        "detailed_data_table": detailed_data_table,
    }


def parse_simple_format(lines: List[str]) -> Dict[str, Any]:
    metadata = {}
    detailed_data_table = []

    # Parse metadata
    for idx, line in enumerate(lines):
        if line.strip() == "":
            start_idx = idx + 1
            break
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    # Parse header
    header = lines[start_idx]
    columns = header.split("\t")

    # Parse data lines
    for line in lines[start_idx + 1 :]:
        parts = line.split("\t")
        if len(parts) < len(columns):
            continue
        record = {
            "Date": parse_datetime(parts[0]),
            "Time": parse_time_only(parts[1]),
            "SUB1_Lon": float(parts[2]),
            "SUB1_Lat": float(parts[3]),
            "ID_Number": parts[4],
            "ID_Name": parts[5],
        }
        detailed_data_table.append(prepare_for_mongodb(record))

    return {"metadata": metadata, "detailed_data_table": detailed_data_table}


def parse_file_content(file_content: str, key: str) -> Dict[str, Any]:
    """
    Parse the file content.

    Args:
        file_content: The file content as a string.
        key: The S3 object key.

    Returns:
        A dictionary containing the parsed data.
    """
    documents = []

    # data parsing logic
    logger.info(f"file_content: {file_content}")

    # split the key into cruise and station:
    cruise_from_name, station_from_name = key.split("_")[0:2]
    logger.info(
        f"From file name we know - cruise: {cruise_from_name}, station: {station_from_name}"
    )

    # split the file content into indivdual lines
    lines = file_content.split("\n")

    # Detect file format
    file_format = detect_file_format(lines)

    if file_format == "original":
        parsed_data = parse_original_format(lines)
    elif file_format == "latest":
        parsed_data = parse_latest_format(lines)
    elif file_format == "simple":
        parsed_data = parse_simple_format(lines)
    else:
        logger.error("Unknown file format")
        return []

    # Initialize variables to hold different sections
    metadata = {}
    descriptive_text = ""
    task_table = []
    detailed_data_table = []

    # Patterns to identify sections
    metadata_pattern = re.compile(r"^(Cruise|Station|Remarks)\s*:\s*(.*)$")
    task_table_header_pattern = re.compile(r"^Task\s*:\s*.*")
    detailed_table_header_pattern = re.compile(r"^#Date\s+Time\s+PC_Time.*")

    # Flags to determine current section
    in_metadata = True
    in_descriptive_text = False
    in_task_table = False
    in_detailed_table = False
    task_table_lines = []
    detailed_table_lines = []

    # Split the file into header and data
    file_format = "original"
    # counter = 0
    for aline in lines:
        # Strip leading/trailing whitespace
        stripped_line = aline.strip()

        # This section is used to determine which file part we are in
        if in_metadata:
            match = metadata_pattern.match(stripped_line)
            if match:
                key, value = match.groups()
                metadata[key.strip()] = value.strip()
                logger.info("Now in Metadata line:")
            elif stripped_line == "":
                # End of metadata section
                in_metadata = False
                in_descriptive_text = True
            else:
                # Unexpected line in metadata
                logger.warning(f"Unexpected line in metadata: {stripped_line}")

        elif in_descriptive_text:
            if task_table_header_pattern.match(stripped_line):
                in_descriptive_text = False
                in_task_table = True
                logger.info("Switching to task table")
                continue
            else:
                descriptive_text += stripped_line + " "

        elif in_task_table:
            if stripped_line.startswith("-") or stripped_line.startswith("----"):
                # End of task table
                in_task_table = False
                in_detailed_table = True
                logger.info("Switching to detailed table")
                continue
            else:
                task_table_lines.append(stripped_line)

        elif in_detailed_table:
            if detailed_table_header_pattern.match(stripped_line):
                # Next lines are detailed data table
                logger.info("Switching to detailed data table")
                continue
            elif stripped_line.startswith("----"):
                # End of data tables
                in_detailed_table = False
                continue
            else:
                detailed_table_lines.append(stripped_line)

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
        documents: The documents to be inserted.

    Returns:
        The result of the insertion operation.
    """
    try:
        if documents:
            result = collection.insert_many(documents)
            logger.info(f"Inserted {len(documents)} documents into MongoDB.")
            return result.inserted_ids
        else:
            logger.info("No documents to insert.")
            return []
    except Exception as e:
        logger.error(f"Error inserting documents into MongoDB: {str(e)}")
        raise e


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
                bucket_name = message_body["bucket"]
                file_key = message_body["key"]

                # If it's from S3 event notification
                if "Records" in message_body:
                    for s3_event in message_body["Records"]:
                        bucket_name = s3_event["s3"]["bucket"]["name"]
                        file_key = s3_event["s3"]["object"]["key"]

                        # Process the file
                        file_content = get_file_from_s3(s3, bucket_name, file_key)

                        # Parse file content
                        documents = parse_file_content(file_content, file_key)

                # If it's your custom message format
                else:
                    bucket_name = message_body["bucket"]
                    file_key = message_body["key"]

                    # Get file content from S3
                    file_content = get_file_from_s3(s3, bucket_name, file_key)

                    # Parse file content
                    documents = parse_file_content(file_content, file_key)

                    # # Prepare documents for MongoDB
                    # prepared_documents = [prepare_for_mongodb(doc) for doc in documents]

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

            except Exception as e:
                logger.error(f"Error processing document: {str(e)}")
                failed_messages.append(record["messageId"])

    except Exception as e:
        logger.error(f"Error processing event: {e}")

    finally:
        # Ensure the MongoDB connection is closed
        client.close()

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
