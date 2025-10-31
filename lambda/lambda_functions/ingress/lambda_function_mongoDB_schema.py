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
* 2016 files: currently not expected to work (this is the 'original' format, not the 'latest' format)

02 December 2024 Tilmann Steinmetz

"""

import json
import logging
import os
import re
import boto3
import sys
import yaml
from io import StringIO
import pandas as pd
from pathlib import Path
import argparse
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from botocore.exceptions import ClientError
from pymongo import MongoClient
from pymongo.collection import Collection, ReturnDocument
from pymongo.database import Database


logger = logging.getLogger()
logger.setLevel(logging.INFO)

START_TIME = datetime.now(timezone.utc)
MAX_EXECUTION_TIME = 850  # 14.5 minutes (for 15-minute Lambda timeout)
# Define possible date and time formats for PCTime
DATETIME_FORMATS = [
    "%d/%m/%Y %H:%M:%S",  # e.g., "16/04/2022 23:08:06"
    "%d.%m.%Y %H:%M:%S",  # e.g., "16.04.2022 23:08:06"
    "%m/%d/%Y %H:%M:%S",  # e.g., "04/16/2022 23:08:06"
    "%m/%d/%Y",  # e.g., "04/16/2022"
    "%Y-%m-%d %H:%M:%S",  # e.g., "2022-04-16 23:08:06"
    "%B %d, %Y %H:%M:%S",  # e.g., "April 16, 2022 23:08:06"
    "%d/%m/%Y %H:%M:%S %p",  # e.g., "April 16, 2022 23:08:06"
]
# Define possible time formats for Time
TIME_FORMATS = [
    "%H:%M:%S",  # e.g., "23:08:06"
    "%I:%M:%S %p",  # e.g., "11:08:06 PM"
    "%H:%M",  # e.g., "23:08"
]
# Define possible date formats for Date
DATE_FORMATS = [
    "%d/%m/%Y",  # e.g., "16/04/2022"
    "%d.%m.%Y",  # e.g., "16.04.2022"
    "%m/%d/%Y",  # e.g., "04/16/2022"
    "%Y-%m-%d",  # e.g., "2022-04-16"
]


class Configs:

    def __init__(
        self,
        config_path: Optional[str] = None,
        cruises_config_path: Optional[str] = None,
    ):
        self.config_path = config_path or Path(__file__).resolve().parent / "config.yml"
        self.cruises_config_path = (
            cruises_config_path or Path(__file__).resolve().parent / "cruises.yml"
        )
        self.headers: Optional[Any] = None
        self.file_suffixes: Optional[str] = None

        self.read_config_file()
        self.read_cruise_config()

    def read_config_file(self) -> None:
        try:
            with open(self.config_path, "r") as file:
                config = yaml.safe_load(file) or {}
                self.file_suffixes = config.get("file_suffix", {})
                self.MongoDB_config = config.get("MongoDB_config", {})
        except Exception as e:
            logging.error(f"Error reading config file: {e}")
            sys.exit(1)

    def read_cruise_config(self) -> None:
        try:
            with open(self.cruises_config_path, "r") as file:
                config = yaml.safe_load(file) or {}
                self.cruises = config.get("cruises")
        except Exception as e:
            logging.error(f"Error reading cruises config file: {e}")
            sys.exit(1)


def parse_datetime(datetime_str: str) -> Optional[datetime]:
    """
    Attempt to parse a datetime string with multiple formats.
    Parses a datetime string and returns it in ISO 8601 format.

    Args:
        datetime_str (str): The datetime string to parse.

    Returns:
        Optional[str]: utc datetime or None if parsing fails.
    """
    for fmt in DATETIME_FORMATS:
        try:
            if datetime_str is None:
                return None
            parsed_date = datetime.strptime(datetime_str, fmt)
            # Assume UTC timezone if not specified
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            # logger.debug("Parsed datetime: %s", parsed_date)
            return parsed_date
        except ValueError:
            # logger.warning(f"Invalid datetime format: {datetime_str}")
            continue

    logger.debug(f"Failed to parse datetime: {datetime_str}")
    return None


def parse_date_only(date_str: str) -> Optional[str]:
    """
    Attempt to parse a date string with multiple formats.
    Parses a date string and returns as datetime object

    Args:
        date_str (str): The date string to parse.

    Returns:
        Optional[str]: The date object or None if parsing fails.
    """
    for fmt in DATE_FORMATS:
        try:
            if date_str is None:
                return None
            parsed_date = datetime.strptime(date_str, fmt).date()
            return parsed_date
        except ValueError:
            # logger.warning(f"Invalid date format: {date_str}")
            continue

    logger.debug(f"Failed to parse date: {date_str}")
    return None


def parse_time_only(time_str: str) -> Optional[str]:
    """
    Parses a time string and returns it in HH:MM:SS format.
    Attempt to parse a time-only string with multiple formats
     optionally: assign a default date.

    Args:
        time_str (str): The time string to parse.

    Returns:
        Optional[str]: time object if
          parsing is successful, else None.
    """
    for fmt in TIME_FORMATS:
        try:
            parsed_time = datetime.strptime(time_str, fmt).time()
            return parsed_time
        except ValueError:
            logger.warning(f"Invalid time format: {time_str}")
            continue
    logger.error(f"Failed to parse time: {time_str}")
    return None


def insert_documents_to_mongodb(
    collection: Collection, documents: List[Dict[str, Any]], is_rerun: bool = False
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
    inserted_doc_counts = 0
    updated_doc_counts = 0

    if not documents:
        logger.warning("No documents to insert.")
        return inserted_doc_counts, updated_doc_counts

    try:
        if not is_rerun:
            # Remove all the records with the same file_key if is_rerun is False
            file_keys = list(set(doc.get("file_key") for doc in documents if "file_key" in doc))
            if file_keys:
                delete_result = collection.delete_many({"file_key": {"$in": file_keys}})
                logger.info(
                    f"Deleted {delete_result.deleted_count} existing documents with matching file_key(s): {file_keys}."
                )

            # Insert all documents
            result = collection.insert_many(documents)
            inserted_doc_counts = len(result.inserted_ids)
            logger.info(f"Inserted {inserted_doc_counts} new documents into MongoDB.")
        else:
            # Separate documents into new, update, and skip
            existing_documents_to_update = []
            new_documents = []
            existing_documents_to_skip_update = []

            for doc in documents:
                existing_doc = collection.find_one(
                    {
                        "cruise": doc["cruise"],
                        "station": doc["station"],
                        "timestamp": doc["timestamp"],
                    }
                )
                if existing_doc:
                    if is_rerun:
                        existing_documents_to_skip_update.append(doc)
                    else:
                        existing_documents_to_update.append(doc)
                else:
                    new_documents.append(doc)

            # Insert new documents into MongoDB
            logger.info(f"New documents to insert: {len(new_documents)}")
            if new_documents:
                result = collection.insert_many(new_documents)
                logger.info(f"Inserted {len(result.inserted_ids)} new documents into MongoDB.")
            # Skip existing documents for rerun
            logger.info(
                f"Existing documents to skip update due to pre-existing rerun entry: "
                f"{len(existing_documents_to_skip_update)}"
            )
            # Update existing documents in MongoDB
            logger.info(
                f"Existing documents to update: {len(existing_documents_to_update)}"
            )
            for doc in existing_documents_to_update:
                update_doc = {k: v for k, v in doc.items() if k not in ["_id", "cruise", "station", "timestamp"]}
                rsl = collection.update_one(
                    {
                        "cruise": doc["cruise"],
                        "station": doc["station"],
                        "timestamp": doc["timestamp"],
                    },
                    {"$set": update_doc},
                )
                if rsl.matched_count > 0 and rsl.modified_count > 0:
                    updated_doc_counts += 1
            logger.info(f"Updated {updated_doc_counts} documents in MongoDB.")
        return inserted_doc_counts, updated_doc_counts
    except Exception as e:
        logger.error(f"Error inserting documents into MongoDB: {str(e)}")
        raise e


def get_current_ingress_id(
    ingress_collection: str,
    cruise: str,
    station: str,
    object_key: str,
    date_created: datetime,
) -> int:
    """
    Get the current ingressId for a given cruise, station, and object_key.
    If the document does not exist, create it with a value of 0.
    This is used to keep track of the number of ingresses
    for a given cruise/station/object_key.

    Args:
        ingress_collection (Collection): The MongoDB collection for ingresses.
        cruise (str): The cruise identifier.
        station (str): The station identifier.
        date_created (datetime): The date the document was created.

    Returns:
        int: The current ingressId value.
    """
    counter = ingress_collection.find_one_and_update(
        {
            "cruise": cruise,
            "station": station,
            "object_key": object_key,
            # "date_created": date_created, # we don't use the date_created
        },
        {
            "$setOnInsert": {
                "ingress_count": 0,
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
    return counter["ingress_count"]


def increment_ingress_id(
    ingress_collection,
    cruise,
    station,
    object_key,
    bounding_box,
    document_counts,
    date_created,
    metadata,
):
    """
    Increment the ingressId for a given cruise, station, and object_key.
    If the document does not exist, create it with a value of 1.

    This is used to keep track of the number of ingresses for a given cruise/station/object_key.

    Args:
        ingress_collection (Collection):
            The MongoDB collection for ingresses.
        cruise (str):
            The cruise identifier.
        station (str):
            The station identifier.
        object_key (str):
            The object_key identifier.
        bounding_box (dict):
            The bounding box coordinates.data.
        document_counts (int):
            The number of documents ingested.
        date_created (datetime):
            The date the document was created.
        metadata (dict):
            The metadata to update in the document.
    Returns:
        int:
        The updated ingress_count.
    """
    logger.debug(
        f"Attempting to update document with filter: "
        f"'cruise': {cruise}, 'station': {station}, 'object_key': {object_key}"
    )
    logger.debug(f"Bounding Box: {bounding_box}")
    try:
        update_doc = {
            "$inc": {"ingress_count": 1},
            "$set": {
                "bounding_box": bounding_box,
                "date_updated": datetime.now(
                    timezone.utc
                ).isoformat(),  # Convert to ISO string
                "metadata": metadata,
                "document_counts": document_counts,
            },
            # "$setOnInsert": {
            #     "date_created": (
            #         date_created.isoformat()
            #         if isinstance(date_created, datetime)
            #         else date_created
            #     ),
            # },
        }
        # Log the update document for debugging
        logger.debug(f"Update Document: {json.dumps(update_doc, default=str)}")

        # Use find_one_and_update to return the updated document
        counter = ingress_collection.find_one_and_update(
            {"cruise": cruise, "station": station, "object_key": object_key},
            update_doc,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        if counter is None:
            logger.error("find_one_and_update did not return any document.")
            return 0

        ingress_count = counter.get("ingress_count", 0)
        logger.info(
            f"Updated document ingress_count: {ingress_count}, bounding_box: {counter.get('bounding_box')}"
        )

        return ingress_count

    except Exception as e:
        logger.error(f"Error in increment_ingress_id: {str(e)}")
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


def initialize_resources() -> Tuple[boto3.client, MongoClient, Database]:
    """
    Initialize resources like MongoDB client, S3 client, etc.
    """

    s3_client = boto3.client("s3")
    ssm = boto3.client("ssm", region_name="ap-southeast-2")
    parameter_name = os.environ.get("MONGODB_URI_SSM_PARAM")
    # Get parameter (with decryption if it's a SecureString)
    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)

    # Extract the MongoDB URI
    mongo_uri = response["Parameter"]["Value"]

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
        logger.info("Error retrieving file from S3: %s"), str(e)
        raise FileNotFoundError(f"File {key} not found in bucket {bucket}")


def detect_file_format(lines: List[str]) -> str:
    """
    Detects the file format based on header patterns.

    Args:
        lines (List[str]): Lines from the file content.

    Returns:
        str: Format identifier ('original', 'new', 'latest', 'simple').
    """
    # set to true to detect the first header line for obser files
    # for prot files dash line usually comes later
    dash_line_found = True

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
            elif stripped_line.startswith("Date\tTime\tPC_Time\tSHIP_Lon"):
                return "latest"
            elif stripped_line.startswith("#Date\tTime\tPC_Time\tSHIP_Lat"):
                return "latest"
            elif stripped_line.startswith(
                "#Date\tTime\tSUB1_Lon\tSUB1_Lat\tID_Number\tID_Name"
            ):
                return "simple"
            else:
                dash_line_found = (
                    False  # Reset if the line after dashes is not a header"
                )
    return "unknown"


def parse_original_format(lines: List[str]) -> Dict[str, Any]:
    """
    Parses files adhering to the "original" prot format (the 2006 cruise data like TAN0616).

    Args:
        lines (List[str]): Lines from the file content.

    Returns:
        Dict[str, Any]: Structured data suitable for MongoDB insertion.
    """
    metadata = {}
    observations = []
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

    # # Phase 1 Completion Check

    # # Phase 2: Detect Header Line
    # logger.debug("Phase 2: Detecting header line.")

    # # Phase 2 Completion Check
    # if not header_found:
    #     logger.error("No header found in 'original' format file.")
    #     logger.error("Returning metadata only.")
    #     return {"metadata": metadata, "observations": observations}

    # # # Phase 3: Parse Tasks

    # # This code is from parse_latest_format - but here, we don't have a clear task section

    # # logger.debug("Phase 3: Parsing tasks.")

    # # Phase 4: Parse Data Rows
    # logger.debug("Phase 4: Parsing data rows ifrom data_start_idx %s.", data_start_idx)

    metadata, data_start_idx = parse_metadata(lines)
    headers, header_idx = detect_header_line(lines, data_start_idx)
    # tasks = parse_tasks(lines, header_idx)
    observations = parse_data_rows(lines, header_idx, headers)

    # Extract coordinate pairs

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
            coordinates.append((lon, lat))

            # If there are SUB1 coordinates
            sub_lat = float(obs.get("SUB1_Lat", 0))
            sub_lon = float(obs.get("SUB1_Lon", 0))
            coordinates.append((sub_lon, sub_lat))
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

    return {
        "metadata": metadata,
        "bounding_box": bounding_box,
        # "tasks": tasks,
        "observations": observations,
    }


def parse_metadata(lines: List[str]) -> Tuple[Dict[str, str], int]:
    """
    Parses the metadata section and detects the delimiter line usually in
    the form of a line with only dashes. "------------------"
    metadata contains : in the text line

    return metadata which contains ":" in the text line as separator
    return data_start_idx which is the index of the line after the delimiter line
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
    logger.info(f"Extracted metadata: {metadata}, data_start_idx: {data_start_idx}")
    return metadata, data_start_idx


def detect_header_line(lines: List[str], start_idx: int) -> Tuple[List[str], int]:
    """
    Detects the header line based on known patterns.
    header line starts with "UTC time" or "Date" or "#Date"

    returns headers which is a list of strings
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
            logger.info("Line content at idx: %s", line)
            # removed # next to Date which is used to identify the header line
            # some files may not contain #
            headers = line.lstrip("#").split("\t")
            headers = [header.strip() for header in headers]
            header_found = True
            return headers, idx + 1

    if header_found:
        logger.info(f"Detected headers: {headers} at line {idx}")
    return headers, start_idx


def get_pc_time(observation):
    """
    Get the PC time from the observation dictionary.
    if not found, return None
    """
    possible_keys = ["PC_Time", "PC time", "PC Time"]
    for key in possible_keys:
        if key in observation.keys():
            return observation[key]
    return None


def get_date(observation, pc_time):
    """
    Get the date from the observation dictionary.
    if not found, return the first 10 characters of the PC time.
    """
    possible_keys = ["Date", "UTC Date", "UTC_Date"]
    for key in possible_keys:
        if key in observation.keys():
            return observation[key]
    return pc_time[:10]


def get_time(observation):
    """
    Get the time from the observation dictionary.
    if not found, return None
    """
    possible_keys = ["Time", "UTC Time", "UTC_Time", "time"]
    for key in possible_keys:
        if key in observation.keys():
            return observation[key]
    return None


def parse_data_rows(
    lines: List[str], start_idx: int, headers: List[str], skip_mismatched=False
) -> List[Dict[str, Any]]:
    """
    Parses the data rows based on the detected headers for prot files.

    Args:
        lines (List[str]): Lines containing data.
        start_idx (int): The starting index for parsing.
        headers (List[str]): List of header names.

    Returns:
        List[Dict[str, Any]]: List of parsed data records.
    """
    logger.debug("Parsing data rows.")
    observations = []
    skipped_lines = 0

    for idx in range(start_idx, len(lines)):
        line = lines[idx].strip()
        # detect empty lines
        # or comments, which usually is the header line
        if not line or line.startswith("#"):
            skipped_lines += 1
            continue  # Skip empty lines or comments
        # detect end of the data section (in obser.txt files)
        if line.startswith("End ###"):
            skipped_lines += 1
            break  # End of data section

        fields = line.split("\t")
        # Check if the number of fields matches the number of headers
        if len(fields) != len(headers):
            logger.warning("Malformed data line %s, %s", idx, line)
            if len(fields) > len(headers):
                logger.warning("It has more fields than headers.")
            else:
                logger.warning("It has fewer field than headers.")
            if skip_mismatched:
                logger.warning("Skipping line %s due to mismatched fields", idx)
                skipped_lines += 1
                continue

        observation = dict(zip(headers, fields))

        # "original": "UTC time, PC time
        # "latest": "#Date, Time, PC_Time
        # "new": "#Date, Time, PC_Time"
        # "simple": "#Date, Time"

        # Parse datetime fields
        pc_time = get_pc_time(observation)
        if pc_time is not None:
            observation["PC_Time"] = parse_datetime(pc_time)
        try:
            date = get_date(observation, pc_time)
            observation["Date"] = parse_date_only(date)
            time = get_time(observation)
            observation["Time"] = parse_time_only(time)
        except:
            logger.error(f"Failed to parse Date and Time at line {idx}: {line}")
            continue

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
                        "Failed to convert '%s' to string at line %s: %s",
                        key,
                        idx,
                        observation[key],
                    )
            # else:
            #     observation[key] = observation[key]

        observations.append(observation)
        logger.debug(f"Parsed observation at line {idx}: {observation}")

    logger.info(
        f"Parsed {len(observations)} data rows, skipped {skipped_lines} rows, total {len(lines)} rows."
    )

    return observations


def parse_adaptive_format(lines: List[str], text_config: dict, data_type: str, MongoDB_config: dict) -> List[Dict[str, Any]]:
    """
    Parses the latest format of the text file.
    Combines separate parsing functions to parse the entire file.

    Args:
        lines (List[str]): Lines from the text file content.
        text_config (dict): Text configuration dictionary.
        data_type (str): Data type identifier.
        MongoDB_config (dict): MongoDB configuration dictionary.

    Returns:
        List[Dict[str, Any]]:
            A list of structured data suitable for MongoDB insertion.
        metadata:
            Metadata dictionary.
        bounding_box:
            Bounding box coordinates (of all events parsed for this station).
        observations:
            List of observation dictionaries.
    """
    # initialize
    metadata = {}  # no metadata in simple format
    bounding_box = None
    observations = []
    
    # Find header index
    header_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == text_config['header'][data_type]:
            header_idx = idx
            break
    if header_idx is None:
            raise ValueError(f"Header '{text_config['header'][data_type]}' not found.")
    # By default, to the end of file 
    end_idx = -1
    for idx, line in enumerate(lines):
        if line.strip() == "End ###":
            end_idx = idx
            break
    try:
        # Extract lines between header and the end, read into DataFrame
        filtered_lines = lines[header_idx:] if end_idx == -1 else lines[header_idx:end_idx]
        clean_data = "\n".join(filtered_lines)
        df = pd.read_csv(StringIO(clean_data), sep="\t")
        if df.empty:
            raise ValueError("No data found after the header.")
        
        # Change the column name "#Date" to "Date" if exists
        if "#Date" in df.columns:
            df.rename(columns={"#Date": "Date"}, inplace=True)
        # Combine 'Date' and 'Time' into 'timestamp' column
        if "Date" in df.columns and "Time" in df.columns:
            df["timestamp"] = pd.to_datetime(
                df["Date"].astype(str) + " " + df["Time"].astype(str),
                format=f"{text_config['date_format']} {text_config['time_format']}",
                errors="coerce",
            )
        # Convert 'Date', 'Time' and 'PC_Time' format to  MongoDB_config specified format
        if "Date" in df.columns:
            df["date_str"] = pd.to_datetime(df["Date"], format=text_config['date_format']).dt.strftime(MongoDB_config['date_format'])
        if "Time" in df.columns:
            df["time_str"] = pd.to_datetime(df["Time"], format=text_config['time_format']).dt.strftime(MongoDB_config['time_format'])
        if "PC_Time" in df.columns:
            df["PC_Time"] = pd.to_datetime(df["PC_Time"], format=text_config['pc_time_format'])
        # for ID_Name, remove ID_Number and a space in front of specis name
        if "ID_Name" in df.columns:
            df["ID_Name"] = df["ID_Name"].str.replace(r"^\[.*?\]\s*", "", regex=True).str.strip()
        # for ID_Number, remove []
        if "ID_Number" in df.columns:
            df["ID_Number"] = df["ID_Number"].str.replace(r"[\[\]]", "", regex=True).str.strip()
        # for Image-Video Path, remove []
        if "Image-Video Path" in df.columns:
            df["Image-Video Path"] = df["Image-Video Path"].str.replace(r"^\[.*?\]\s*", "", regex=True).str.strip()

        # Get headers
        headers = df.columns.tolist()
        logger.info(f"Detected headers: {headers} at line {header_idx}")

        # Convert DataFrame to list of dictionaries
        observations = df.to_dict(orient="records")

        # Caculcate bounding box requires ("SHIP_Lat", "SHIP_Lon") or ("SUB1_Lat", "SUB1_Lon")
        if "SHIP_Lat" in df.columns and "SHIP_Lon" in df.columns:
            bounding_box= {
                "type": "Polygon",
                "coordinates": [
                    [
                        [df["SHIP_Lon"].min(), df["SHIP_Lat"].min()],
                        [df["SHIP_Lon"].max(), df["SHIP_Lat"].min()],
                        [df["SHIP_Lon"].max(), df["SHIP_Lat"].max()],
                        [df["SHIP_Lon"].min(), df["SHIP_Lat"].max()],
                        [df["SHIP_Lon"].min(), df["SHIP_Lat"].min()],
                    ]
                ],
            }
            logging.info("Calculated bounding box from SHIP_Lat and SHIP_Lon.")
        elif "SUB1_Lat" in df.columns and "SUB1_Lon" in df.columns:
            bounding_box= {
                "type": "Polygon",
                "coordinates": [
                    [
                        [df["SUB1_Lon"].min(), df["SUB1_Lat"].min()],
                        [df["SUB1_Lon"].max(), df["SUB1_Lat"].min()],
                        [df["SUB1_Lon"].max(), df["SUB1_Lat"].max()],
                        [df["SUB1_Lon"].min(), df["SUB1_Lat"].max()],
                        [df["SUB1_Lon"].min(), df["SUB1_Lat"].min()],
                    ]
                ],
            }
            logging.info("Calculated bounding box from SUB1_Lat and SUB1_Lon.")
        else:
            logger.warning("Both ('SHIP_Lat', 'SHIP_Lon') or ('SUB1_Lat', 'SUB1_Lon') are missing for bounding box calculation.")
    except Exception as e:
        raise ValueError(f"Error reading data into DataFrame: {e}")
    return {
        "metadata": metadata,
        "bounding_box": bounding_box,
        "observations": observations,
    }

def parse_file_content(file_content: str, 
                       key: str, 
                       ingress_collection: Collection, 
                       cruise_config: dict, 
                       MongoDB_config: dict, 
                       data_type: str) -> Tuple[
    str,   # List of documents (as a string or serialized format)
    str,   # File format
    Tuple, # Bounding box or tuple of coordinates
    str,   # Cruise name
    str,   # Station name
    Dict   # Metadata
]:

    """
    Parses the file content and returns a list of documents
    and the file format.

    Args:
        file_content: The file content as a string.
        key: The S3 object key.
        ingress_collection: The MongoDB collection for ingresses.
        headers: The headers configuration.
        data_type: The type of data being processed.

    Returns:
        List[str, Any]:
            A list of parsed documents.
        file_format:
            (str, from detection algorithm).
        bounding_box:
            (tuple of coordinates, from the last parsed document).
        cruise_from_name:
            (str, from file name).
        station_from_name:
            (str, from file name).
    """
    logger.debug(f"file_content: {file_content[:100]}...")

    try:
        cruise = key.split("/")[0].upper()
        station = key.split("/")[1].upper()
    except ValueError:
        raise ValueError(f"Invalid key format: {key}")

    logger.debug(
        "From file name we know - cruise: %s, station: %s",
        cruise,
        station,
    )

    try:
        # split the file content into indivdual lines
        lines = file_content.splitlines()

        # Detect file format
        file_format = detect_file_format(lines)
        logger.info(
            "Detected file format: %s",
            file_format,
        )

        # Parse based on file format:
        if file_format == "original":
            logger.info("Parsing 'original' format file.")
            parsed_data = parse_original_format(lines)
        elif file_format == "latest" or file_format == "simple":
            logger.info("Parsing 'latest'/'simple' format file.")
            parsed_data = parse_adaptive_format(lines, cruise_config[cruise], data_type, MongoDB_config)
        else:
            raise ValueError("Unknown file format - cannot parse.")
        # Add metadata from file name
        parsed_data["metadata"]["Cruise"] = cruise
        parsed_data["metadata"]["Station"] = station
    except Exception as e:
        raise ValueError(f"Error parsing file content: {str(e)}")

    # Prepare documents for MongoDB insertion
    logging.debug("Preparing document for MongoDB insertion. %s", parsed_data)
    try:
        documents, metadata, image_docs, video_docs = prepare_documents(
            parsed_data, key, ingress_collection
        )
    except Exception as e:
        raise ValueError(f"Error preparing documents: {str(e)}")

    # # We will return the bounding box from the last parsed document
    bounding_box = parsed_data.get("bounding_box")

    if not documents:
        logger.warning("No parsed data found to create documents.")

    return (
        documents,
        file_format,
        bounding_box,
        cruise,
        station,
        metadata,
        image_docs,
        video_docs,
    )


def remove_brackets(text, default=""):
    """
    Removes bracketed content from the input text.

    Args:
        text (str): The input string containing bracketed content.
        default (str): The default value to return if the result is empty.

    Returns:
        str: The cleaned string without brackets or the default value.
    """
    # Remove brackets and any content inside them, along with any leading whitespace
    cleaned = re.sub(r"\[.*?\]\s*", "", text)
    # Return cleaned text if not empty, else return default
    return cleaned if cleaned else default


def check_source_key(source_key):
    # Determine if the source key indicates a rerun, prot, or obser file
    # Will deal with prot and obser files, but not posi files
    is_rerun = "rerun" in source_key
    is_prot = source_key.endswith("_prot.txt")
    is_obs = source_key.endswith("_obser.txt")
    is_posi = source_key.endswith("_posi.txt")

    return is_rerun, is_prot, is_obs, is_posi


def prepare_img_document(document):
    """
    Construct a document for MongoDB insertion for image data.
    add img_key to the document after extracting img_key from obs_text
    limitation: the generated img_key has 1000 image cap
    Args:
        document (Dict[str, Any]): The structured document.

    Returns:
        Dict[str, Any]:
            A structured document ready for MongoDB insertion.
        img_num:
            The image number extracted from the observation
    """
    cruise = document["cruise"]
    station = document["station"]
    obs_text = document["observation"]
    if "DTIS photo:" not in obs_text:
        img_num = int(obs_text.split("photo")[-1].strip())
    else:
        img_num = int(obs_text.split("DTIS photo:")[-1].split(";")[0].strip())
    img_key = f"{cruise}/{station}/images/"
    document["img_key"] = img_key

    return document, img_num


def prepare_video_document(document):
    """
    Construct a document for MongoDB insertion for video data.

    Args:
        document (Dict[str, Any]): The structured document.
    Returns:
        Dict[str, Any]: A structured document ready for MongoDB insertion.
    """
    cruise = document["cruise"]
    station = document["station"]
    timestamp = document["timestamp"].strftime("%Y%m%d%H%M%S")
    video_key = f"{cruise}/{station}/videos/"
    document["video_key"] = video_key
    return document


def prepare_prot_document(
    cruise, station, observation, file_key, is_rerun
):
    """
    Construct a document for MongoDB insertion for prot data.

    Args:
        cruise (str): The cruise name.
        station (str): The station name.
        observation (Dict[str, Any]): The raw observation data.
        file_key (str): The S3 key of the input file.
        is_rerun (bool): Whether the data is from a rerun file.

    Returns:
        Dict[str, Any]:
            A structured document ready for MongoDB insertion.
    """
    document = {
        "file_key": file_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cruise": cruise,
        "station": station,
        "timestamp": observation.get("timestamp", None),
        "pc_time": observation.get("PC_Time", None),
        "date": observation.get("date_str", None),
        "time": observation.get("time_str", None),
        # "tasks": tasks,
        "shipLocation": {
            "type": "Point",
            "coordinates": [
                float(observation.get("SHIP_Lon", None)),
                float(observation.get("SHIP_Lat", None)),
            ],
        },
        "speed": float(observation.get("SHIP_SOG", None)),
        "course": float(observation.get("SHIP_COG", None)),
        "heading": float(observation.get("SHIP_Hdg", None)),
        "depth": float(observation.get("Water_Depth", None)),
        "subLocation": {
            "type": "Point",
            "coordinates": [
                float(observation.get("SUB1_Lon", None)),
                float(observation.get("SUB1_Lat", None)),
            ],
        },
        "subDepth": float(observation.get("SUB1_Depth", None)),
        "subAltitude": float(observation.get("SUB1_Altitude", None)),
    }
    if is_rerun:
        document["observation2"] = observation.get("Image-Video Path", "")  #? observation.get("ID_Name", "")
    else:
        document["observation"] =  observation.get("Image-Video Path", "")  #? observation.get("ID_Name", "")
    return document


def prepare_obser_document(
    cruise, station, observation, file_key, is_rerun
):
    """
    Construct a document for MongoDB insertion for obser data.

    Args:
        cruise (str): The cruise name.
        station (str): The station name.
        observation (Dict[str, Any]): The raw observation data.
        file_key (str): The S3 key of the input file.
        is_rerun (bool): Whether the data is from a rerun file.

    Returns:
        Dict[str, Any]:
            A structured document ready for MongoDB insertion.
    """
    document = {
        "file_key": file_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cruise": cruise,
        "station": station,
        "timestamp": observation['timestamp'],
        "date": observation['date_str'],
        "time": observation['time_str'],
        "subLocation": {
            "type": "Point",
            "coordinates": [
                float(observation.get("SUB1_Lon", None)),
                float(observation.get("SUB1_Lat", None)),
            ],
        },
    }
    if is_rerun:
        document["observation2"] = observation.get("ID_Name", "")
    else:
        document["observation"] = observation.get("ID_Name", "")
    return document


def prepare_documents(
    parsed_data: Dict[str, Any], file_key: str, ingress_collection: Optional[Collection]
) -> List[Dict[str, Any]]:
    """
    Prepares a document for MongoDB insertion based on the parsed data .

    Args:
        parsed_data (Dict[str, Any]):
            The data parsed from the input file.
        file_key (str):
            The S3 key of the input file.
        ingress_collection (Optional[Collection]):
            MongoDB collection for ingresses.

    Returns:
        List[Dict[str, Any]]:
            A list of structured documents ready for MongoDB insertion
            (or None if preparation fails).
    """
    is_rerun, is_prot, is_obs, is_posi = check_source_key(file_key)
    cruise = parsed_data["metadata"]["Cruise"]
    station = parsed_data["metadata"]["Station"]
    logger.info(f"Extracted cruise: {cruise}, station: {station}")
    # # Remove keys that are not needed in metadata
    # keys_to_remove = ["Cruise", "Station"]
    # metadata = {k: v for k, v in metadata.items() if k not in keys_to_remove}

    logger.debug("Preparing document for MongoDB insertion.")
    logger.info("Assembling document")

    # Extracted bounding box (coordinates)
    logger.info("Extracted bounding box: %s", str(parsed_data['bounding_box']))

    # Extract detailed data table (observations)
    logger.info("Extracted %s observations.", len(parsed_data['observations']))

    documents = []
    image_docs = []  # store image docs only for original prot file
    video_docs = []  # store video docs only for original prot file
    image_nums = []  # store image numbers only for original prot file

    # Get the current ingressId
    current_ingress_id = 1

    # Extract ingressID from  MongoDB (using ingress_collection)
    if ingress_collection is not None:
        try:
            # use the first observation's timestamp as the date_created
            date_created_dt = parsed_data['observations'][0].get("timestamp", None)
            current_ingress_id = get_current_ingress_id(
                ingress_collection=ingress_collection,
                cruise=cruise,
                station=station,
                object_key=file_key,
                date_created=date_created_dt,
            )

            logger.info(
                "Updated ingress document with ingress_id: %s",
                current_ingress_id,
            )
        except Exception as e:
            logger.error("Failed to get current ingressId: %s", e)
            return []  # Return empty list if ingressId retrieval fails
        finally:
            logger.info("Current ingressId: %s", current_ingress_id)

    for observation in parsed_data['observations']:
        # Initialize the document
        if is_prot:
            document = prepare_prot_document(
                cruise=cruise,
                station=station,
                observation=observation,
                file_key=file_key,
                is_rerun=is_rerun,
            )
            documents.append(document)
            if "photo" in document['observation']:
                img_doc, img_num = prepare_img_document(document)
                image_docs.append(img_doc)
                image_nums.append(img_num)
            if "video" in document['observation']:
                video_doc = prepare_video_document(document)
                video_docs.append(video_doc)
        elif is_obs:
            document = prepare_obser_document(
                cruise=cruise,
                station=station,
                observation=observation,
                file_key=file_key,
                is_rerun=is_rerun,
            )
            documents.append(document)
        else:
            logger.warning(f"Unknown file type of {file_key}. Skipping...")
            continue

        logger.debug(f"Prepared document for observation: {document}")
    metadata = parsed_data.get("metadata", {})
    # count max image number
    max_img_num = max(image_nums) if image_nums else 0
    if max_img_num > 0:
        metadata["image_count"] = max_img_num
    # count video using start and stop entry documents
    if len(video_docs) > 0:
        metadata["video_count"] = int(len(video_docs) / 2)

    logger.info(f"Total documents prepared for insertion: {len(documents)}")
    return documents, metadata, image_docs, video_docs


def generate_lambda_payload(bucket_name, file_key):
    """
    Generate the payload for the MediaConvert Lambda function.

    Args:
        bucket_name (str): The name of the S3 bucket.
        file_key (str): The S3 object key.

    Returns:
        dict: The payload for the MediaConvert Lambda function.
    """
    return {
        "Records": [
            {"s3": {"bucket": {"name": bucket_name}, "object": {"key": file_key}}}
        ]
    }


def process_media_convert(bucket_name, file_key):
    try:
        # call media convert lambda function for video files
        lambda_client = boto3.client("lambda")
        lambda_payload = generate_lambda_payload(bucket_name, file_key)
        lambda_response = lambda_client.invoke(
            FunctionName=os.environ["MEDIA_CONVERT_LAMBDA_FUNCTION"],
            InvocationType="RequestResponse",
            Payload=json.dumps(lambda_payload),
        )
        logger.info("Triggered media convert for video file")
        logger.info("Lambda function response: %s", lambda_response)
    except Exception as e:
        logger.error(f"Error calling media convert lambda function: {str(e)}")


def process_text_file(
    record,
    file_key,
    bucket_name,
    collection_prot,
    collection_obser,
    ingress_collection,
    collection_image,
    collection_video,
    cruise_config,
    MongoDB_config
):
    documents = []
    # Verify if prot or obser or rerun file
    data_type = None
    is_rerun, is_prot, is_obs, is_posi = check_source_key(file_key)
    if is_prot:
        ofop_collection = collection_prot
        data_type = "prot"
    elif is_obs:
        ofop_collection = collection_obser
        data_type = "obser"
    elif is_posi:
        logger.info(f"POSI file detected for {file_key}. Skipping MongoDB ingestion.")
        return
    elif is_rerun:
        data_type = "rerun"
    else:
        logger.error(f"Unknown file type of {file_key}. Skipping...")
        return

    # Get file content from S3
    file_content = get_file_from_s3(
        s3_client=None,  # Replace with your S3 client if needed
        bucket=bucket_name,
        key=file_key,
    )

    logger.debug(
        f"file_content: {file_content[:100]}..."
    )  # Log first 100 chars for brevity
    try:
        # Parse file content
        (
            documents,
            file_format,
            bounding_box,
            cruise,
            station,
            metadata,
            image_docs,
            video_docs,
        ) = parse_file_content(
            file_content,
            file_key,
            ingress_collection,  # Pass the ingress collection
            cruise_config,
            MongoDB_config,
            data_type
        )
    except Exception as e:
        logger.error(f"Error parsing file content for {file_key}: {str(e)}")
        return []

    if len(documents) > 0:
        # Insert new documents, old documents need to update, take care of obs and obs2
        inserted_counts, updated_counts = insert_documents_to_mongodb(
            collection=ofop_collection, documents=documents, is_rerun=is_rerun
        )
        logger.info(
            "Inserted %s docs, updated %s docs in MongoDB, total %s docs.",
            inserted_counts,
            updated_counts,
            len(documents),
        )
        # Insert image documents
        if len(image_docs) > 0:
            inserted_image_counts, updated_image_counts = insert_documents_to_mongodb(
                collection=collection_image,
                documents=image_docs,
            )
            logger.info(
                "Inserted %s docs, updated %s docs in MongoDB, total %s image docs.",
                inserted_image_counts,
                updated_image_counts,
                len(image_docs),
            )
        # Insert video documents
        if len(video_docs) > 0:
            inserted_video_counts, updated_video_counts = insert_documents_to_mongodb(
                collection=collection_video,
                documents=video_docs,
            )
            logger.info(
                "Inserted %s docs, updated %s docs in MongoDB, total %s video docs.",
                inserted_video_counts,
                updated_video_counts,
                len(video_docs),
            )

        # Try to generate document summary and insert or update to MongoDB
        try:
            object_key = file_key.strip() if file_key else None
            cruise = cruise.strip()
            station = station.strip()

            # Update the ingress document with the additional info such as file_key, metadata, etc.
            logger.info(
                "Incrementing ingressId for cruise: %s, station: %s, object_key: %s, bounding_box: %s",
                cruise,
                station,
                object_key,
                bounding_box,
            )
            ingress_count = increment_ingress_id(
                ingress_collection=ingress_collection,
                cruise=cruise,
                station=station,
                object_key=object_key,
                bounding_box=bounding_box,
                document_counts=len(documents),
                date_created=datetime.now(timezone.utc),
                metadata=metadata,
            )
            logger.info(f"Final Ingress Count: {ingress_count}")
            logger.info("Parsed file format: %s", file_format)
            logger.info(
                "Bounding Box: %s",
                bounding_box,
            )
        except Exception as inner_e:
            logger.error(f"Error processing record {record}: {str(inner_e)}")
    else:
        logger.info("No documents to insert...")
    return documents


def lambda_handler(event, context):

    # 0, read the config file
    config = Configs()

    logger.info("Received event: %s", json.dumps(event))
    try:
        s3_client, mongo_client, db = initialize_resources()
        collection_prot = db[os.environ["MONGODB_COLLECTION_PROT"]]
        collection_obser = db[os.environ["MONGODB_COLLECTION_OBSER"]]
        ingress_collection = db[os.environ["INGRESS_COLLECTION_DTIS"]]
        collection_image = db[os.environ["MONGODB_COLLECTION_IMAGE"]]
        collection_video = db[os.environ["MONGODB_COLLECTION_VIDEO"]]

        documents = []
        for record in event["Records"]:
            try:
                # Parse SQS message body
                message_body = json.loads(record["body"])
                logger.info(f"Processing message body: {message_body}")

                # If it's from S3 event notification
                if "Records" in message_body:
                    for s3_event in message_body["Records"]:
                        try:
                            bucket_name = s3_event["s3"]["bucket"]["name"]
                            file_key = s3_event["s3"]["object"]["key"]
                            logger.info(
                                "Processing S3 file - Bucket: %s, Key: %s",
                                bucket_name,
                                file_key,
                            )
                            # detect file type
                            file_suffix = Path(file_key.lower()).suffix
                            for file_type, suffixes in config.file_suffixes.items():
                                if file_suffix in suffixes:
                                    logger.info(
                                        f"Detected {file_type} file with {file_suffix} suffix"
                                    )
                                    break

                            if file_type == "videos":
                                logger.info("Detected video file: %s", file_key)
                                if file_type != ".mp4":
                                    # call media convert lambda function for .m2t video files
                                    process_media_convert(bucket_name, file_key)
                                else:
                                    logger.info(
                                        "Skip media convert for .mp4 video files"
                                    )
                                logger.info("Skip MongoDB ingress for video files")
                                continue
                            elif file_type == "images":
                                logger.info("Detected image file: %s", file_key)
                                logger.info("Skip MongoDB ingress for image files")
                                continue
                            elif file_type in ["ofop", "ofop_rerun"]:
                                documents = process_text_file(
                                    record,
                                    file_key,
                                    bucket_name,
                                    collection_prot,
                                    collection_obser,
                                    ingress_collection,
                                    collection_image,
                                    collection_video,
                                    config.cruises,
                                    config.MongoDB_config
                                )
                        except Exception as e:
                            logger.error(
                                f"Error processing S3 event record {s3_event}: {str(e)}"
                            )
                            continue
            except Exception as e:
                logger.error(f"Error processing record: {str(e)}")
                # Optionally, handle failed records
                continue

        # Close the MongoDB client
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

if __name__ == "__main__":
    # for local testing only
    # get event name for the command line argument
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=str, required=False, default="sample_event.json", help="Event file name")
    args = parser.parse_args()

    with open(args.event, "r") as f:
        sample_event = json.load(f)
    lambda_handler(sample_event, None)