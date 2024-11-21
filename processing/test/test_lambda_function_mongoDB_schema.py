"""
This test suite covers:

* test_parse_data_line: parsing of a valid data line in prot.file
* test_parse_data_line_invalid_format/source_key: Handling of invalid/incomplete lines in prot.file
* test_parse_data_line_media_types: Photo detection and path construction
* test_parse_data_line_complete_video_sequence: : check video observations and their timing work
* test_parse_data_line_video_stop/Video start/stop event detection: check video observations and their timing work (these are older tests)
* test_parse_data_line_video_duration: Video duration calculation

* Time parsing:

should we use the 'pendulum' library so we're better able to deal with dates/times?
*TBD test_parse_data_line_time_parsing: Tests the time parsing logic for the date and time fields


* Media type detection
* Complete video sequence handling
* test_get_posi_file_content_success: Tests the path where the posi file exists and can be retrieved successfully.
* test_get_posi_file_content_no_file: Tests the error handling when the posi file doesn't exist.
* test_get_posi_file_content_file_name_transformation: Specifically tests the file name transformation logic from "_prot.txt" to "_posi.txt".
* test_get_posi_file_content_various_paths: Uses parametrize to test multiple input scenarios for different file paths and names.

Tests for refactored code (after removal of various functions from Lambda Handler):

* initialize_resources: Tests that resources are initialized correctly.
* get_file_from_s3: Tests both successful file retrieval and handling of a missing file.
* parse_file_content: Tests parsing of file content.
* prepare_documents: Tests preparation of documents.
* insert_documents_to_mongodb: Tests insertion of documents into MongoDB.
* lambda_handler: Tests the overall lambda handler function using mocks for dependencies.


Summary of new Tests for re-factored code:

test_parse_metadata: Tests the parse_metadata function.
test_detect_header_line: Tests the detect_header_line function.
test_parse_tasks: Tests the parse_tasks function.
test_parse_data_rows: Tests the parse_data_rows function.
test_parse_latest_format: Tests the parse_latest_format function, which combines all the smaller functions.

"""

import json
import os
import sys

# Adjust the path to ensure the module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest
from botocore.exceptions import ClientError
from lambda_function_mongoDB_schema import (
    detect_file_format,
    detect_header_line,
    get_file_from_s3,
    get_posi_file_content,
    initialize_resources,
    insert_documents_to_mongodb,
    lambda_handler,
    parse_data_line,
    parse_data_rows,
    parse_datetime,
    parse_file_content,
    parse_latest_format,
    parse_metadata,
    parse_original_format,
    parse_posi_file,
    parse_simple_format,
    parse_tasks,
    parse_time_only,
    prepare_documents,
)

"""
Summary of new Tests for re-factored code:

test_parse_metadata: Tests the parse_metadata function.
test_detect_header_line: Tests the detect_header_line function.
test_parse_tasks: Tests the parse_tasks function.
test_parse_data_rows: Tests the parse_data_rows function.
test_parse_latest_format: Tests the parse_latest_format function, which combines all the smaller functions.
"""


@pytest.fixture
def basic_line():
    return "12:34:56\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tgeneral observation"


@pytest.fixture
def source_key():
    return "TAN2306_123_prot.txt"


# Added for rerun_XX_obser.txt format:
@pytest.fixture
def new_format_line():
    return "11/14/2006\t14:08:08\t173.6320797\t-42.5125708\t[29]\t[29] OBSCURED"


# Added for rerun_XX_obser.txt format:
@pytest.fixture
def new_format_header():
    return "#Date\tTime\tSUB1_Lon\tSUB1_Lat\tID_Number\tID_Name"


@pytest.fixture
def mock_object_id_fixture():
    with patch("lambda_function_mongoDB_schema.ObjectId") as mock_object_id:
        mock_object_id.return_value = "673bc96288f3596d483ba885"
        yield mock_object_id


@pytest.fixture
def mock_datetime_fixture():
    with patch("lambda_function_mongoDB_schema.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(
            2024, 11, 18, 23, 10, 26, 905034, tzinfo=timezone.utc
        )
        yield mock_datetime


# # Mock environment variables
# os.environ["MONGODB_URI"] = "mongodb://localhost:27017"
# os.environ["MONGODB_DATABASE"] = "test_db"
# os.environ["MONGODB_COLLECTION"] = "test_collection"
# os.environ["INGRESS_COLLECTION_DTIS"] = "ingress_collection"
# os.environ["S3_BUCKET_NAME"] = "test_bucket"


@pytest.fixture(autouse=True)
def set_env_vars(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGODB_DATABASE", "test_db")
    monkeypatch.setenv("MONGODB_COLLECTION", "test_collection")
    monkeypatch.setenv("INGRESS_COLLECTION_DTIS", "ingress_collection")
    monkeypatch.setenv("S3_BUCKET_NAME", "test_bucket")


@pytest.fixture
def s3_client():
    return Mock()


@pytest.fixture
def mongo_client():
    return Mock()


@pytest.fixture
def db(mongo_client):
    return MagicMock()


def test_initialize_resources():
    """
    Test that resources are initialized correctly.
    """
    s3_client, mongo_client, db = initialize_resources()
    assert s3_client is not None
    assert mongo_client is not None
    assert db is not None


def test_get_file_from_s3_success(s3_client):
    """
    Test successful file retrieval from S3.
    """
    s3_client.get_object.return_value = {"Body": Mock(read=lambda: b"file content")}
    result = get_file_from_s3(s3_client, "test_bucket", "test_key")
    assert result == "file content"


def test_get_file_from_s3_no_file(s3_client):
    """
    Test handling of a missing file in S3.
    """
    s3_client.get_object.side_effect = ClientError(
        {
            "Error": {
                "Code": "NoSuchKey",
                "Message": "The specified key does not exist.",
            }
        },
        "GetObject",
    )
    with pytest.raises(FileNotFoundError):
        get_file_from_s3(s3_client, "test_bucket", "test_key")


def test_parse_file_content():
    """
    Test parsing of file content.
    """
    file_content = "#Date\tTime\n12.12.2020\t12:34:56\n"
    key = "TAN0616_009_prot.txt"
    result, fileformat = parse_file_content(file_content, key)
    # assert that some 'fileformat' is returned, one of 'original', 'new', 'latest', 'simple':
    assert fileformat in ["original", "new", "latest", "simple"]
    assert result is not None


def DEPCRECATED_test_prepare_documents():
    """
    Test preparation of documents for MongoDB insertion.
    """
    data_lines = [
        "06:19:45\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tgeneral observation"
    ]
    file_key = "test_key_prot.txt"
    posi_content = """#Date\tTime\tPC_Time\tSHIP_Lat\tSHIP_Lon\tSHIP_SOG\tSHIP_COG\tWater_Depth\tSHIP_Hdg\tSUB1_Lat\tSUB1_Lon\tREF_Lat\tREF_Lon
04.11.2006\t06:19:45\t04.11.2006 19:19:44\t-40.0301167\t178.1399167\t1.3\t205.1\t842.1\t305.8\t0\t0\t-40.0300107\t178.1397275
04.11.2006\t06:19:50\t04.11.2006 19:19:49\t-40.0301333\t178.1399\t1.2\t208.4\t839.8\t305\t0\t0\t-40.0300291\t178.1397086
04.11.2006\t06:19:55\t04.11.2006 19:19:54\t-40.0301667\t178.1398833\t1.2\t205.7\t840.9\t304.2\t-40.0301828\t178.1400298\t-40.0300661\t178.1396898
04.11.2006\t06:20:00\t04.11.2006 19:19:59\t-40.0301833\t178.1398833\t1.2\t205.3\t842.1\t303.5\t-40.0301828\t178.1400298\t-40.0300819\t178.1396898
04.11.2006\t06:20:05\t04.11.2006 19:20:04\t-40.0302167\t178.1398667\t1.2\t199.2\t844.5\t302.7\t-40.0301828\t178.1400298\t-40.0301188\t178.1396709
04.11.2006\t06:20:10\t04.11.2006 19:20:09\t-40.0302333\t178.1398667\t1.3\t199.8\t843.6\t302.2\t-40.0301828\t178.1400298\t-40.0301373\t178.1396692"""
    posi_data = parse_posi_file(posi_content)
    cruise = "cruise"
    station = "station"
    remarks = "remarks"
    ingress_collection = MagicMock()

    # Mock the get_current_ingress_id function to return a real value
    with patch(
        "lambda_function_mongoDB_schema.get_current_ingress_id",
        return_value="mock_ingress_id",
    ):
        # Call the actual prepare_documents function
        documents, sub_coordinates = prepare_documents(
            ingress_collection,
            data_lines,
            file_key,
            posi_data,
            cruise,
            station,
            remarks,
            file_format="original",
        )

    assert len(documents) == 1
    assert "meta" in documents[0]
    assert "subLocation" in documents[0]
    assert documents[0]["meta"]["cruise"] == cruise
    assert documents[0]["meta"]["station"] == station
    assert documents[0]["meta"]["remarks"] == remarks
    assert documents[0]["meta"]["ingressId"] == "mock_ingress_id"
    assert documents[0]["subLocation"]["coordinates"] == [174.9876, -41.2345]
    # Check that sub_coordinates is a GeoJSON polygon with 5 coordinate pairs
    assert "type" in sub_coordinates
    assert sub_coordinates["type"] == "Polygon"
    assert "coordinates" in sub_coordinates
    assert len(sub_coordinates["coordinates"]) == 1  # One polygon
    assert len(sub_coordinates["coordinates"][0]) == 5  # Five coordinate pairs


def test_insert_documents_to_mongodb(db):
    """
    Test insertion of documents into MongoDB.
    """
    collection = db[os.environ["MONGODB_COLLECTION"]]
    documents = [{"_id": 1}, {"_id": 2}]
    collection.insert_many.return_value = Mock(inserted_ids=[1, 2])
    result = insert_documents_to_mongodb(collection, documents)
    assert result == [1, 2]


def test_insert_one_document_to_mongodb(db, mongo_client, test_document={"_id": 1}):
    """
    Test insertion a single document into MongoDB.
    """
    # # Assuming mongo_client_mock is a fixture that mocks MongoDB client
    # db = mongo_client.return_value.__getitem__.return_value
    # collection = db.__getitem__.return_value

    # Call the function under test
    insert_documents_to_mongodb(db, test_document)

    collection = db[os.environ["MONGODB_COLLECTION"]]
    # Verify that insert_one was called with the correct document
    collection.insert_one.assert_called_once_with(test_document)


@patch("lambda_function_mongoDB_schema.initialize_resources")
@patch("lambda_function_mongoDB_schema.get_file_from_s3")
@patch("lambda_function_mongoDB_schema.parse_file_content")
@patch("lambda_function_mongoDB_schema.prepare_documents")
@patch("lambda_function_mongoDB_schema.insert_documents_to_mongodb")
@patch("lambda_function_mongoDB_schema.get_posi_file_content")
def test_lambda_handler(
    mock_get_posi_file_content,
    mock_insert_documents_to_mongodb,
    mock_prepare_documents,
    mock_parse_file_content,
    mock_get_file_from_s3,
    mock_initialize_resources,
):
    """
    Test the overall lambda handler function using mocks for dependencies.

    Mocking Dependencies: The test function mocks the necessary dependencies
    (initialize_resources, get_file_from_s3, parse_file_content, prepare_documents, insert_documents_to_mongodb, and get_posi_file_content) to isolate the lambda_handler function.

    Mocking SQS Message Body: The event is updated to include a body with
      the bucket name and file key in JSON format.

    Mocking MongoDB Client: The MongoDB client is mocked to ensure that the
      client.close() method is called.

    Configuring db Mock: The db mock object is configured to return a mock collection when subscripted with os.environ["MONGODB_COLLECTION"] and os.environ["INGRESS_COLLECTION_DTIS"].
      This is necessary to simulate the behavior of the MongoDB client and collection.

    Assertions: The assertions check that the lambda_handler function
      returns a status code of 200 and that the response body contains the
      message "Successfully processed all messages."

    Additionally, the test verifies that the MongoDB connection is closed
    by checking that mock_mongo_client.close is called once.
    """
    mock_s3_client = Mock()
    mock_mongo_client = Mock()
    mock_db = MagicMock()
    mock_collection = Mock()
    mock_ingress_collection = Mock()

    # Configure the db mock to return mock collections when subscripted
    mock_db.__getitem__.side_effect = lambda name: (
        mock_collection
        if name == os.environ["MONGODB_COLLECTION"]
        else mock_ingress_collection
    )

    mock_initialize_resources.return_value = (
        mock_s3_client,
        mock_mongo_client,
        mock_db,
    )
    mock_get_file_from_s3.return_value = "file content"
    mock_parse_file_content.return_value = {
        "header": "header",
        "data_lines": ["data line"],
        "cruise": "cruise",
        "station": "station",
        "remarks": "remarks",
        "file_format": "original",
    }
    mock_prepare_documents.return_value = (
        ["document"],
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [174.9876, -41.2345],
                    [174.9876, -41.2345],
                    [174.9876, -41.2345],
                    [174.9876, -41.2345],
                    [174.9876, -41.2345],
                ]
            ],
        },
    )
    mock_insert_documents_to_mongodb.return_value = [1, 2]
    mock_get_posi_file_content.return_value = "posi file content"

    event = {
        "Records": [
            {"body": json.dumps({"bucket": "test_bucket", "key": "TAN0313_prot.txt"})}
        ]
    }
    context = Mock()

    result = lambda_handler(event, context)
    assert result["statusCode"] == 200
    assert "Successfully processed all messages." in json.loads(result["body"])

    # Ensure the MongoDB connection is closed
    mock_mongo_client.close.assert_called_once()


def test_get_posi_file_content_success():
    """
    Tests the path where the posi file exists and can be retrieved successfully.
    """
    # Arrange
    mock_s3 = Mock()
    mock_response = {"Body": Mock()}
    mock_response["Body"].read.return_value = b"sample posi content"
    mock_s3.get_object.return_value = mock_response

    # Act
    result = get_posi_file_content(mock_s3, "test-bucket", "sample_prot.txt")

    # Assert
    assert result == "sample posi content"
    mock_s3.get_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="sample_posi.txt",
    )


def test_get_posi_file_content_no_file():
    """
    Tests the error handling when the posi file doesn't exist.
    """
    # Arrange
    mock_s3 = Mock()
    mock_s3.exceptions.NoSuchKey = ClientError
    mock_s3.get_object.side_effect = ClientError(
        {
            "Error": {
                "Code": "NoSuchKey",
                "Message": "The specified key does not exist.",
            }
        },
        "GetObject",
    )

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        get_posi_file_content(mock_s3, "test-bucket", "sample_prot.txt")


def test_get_posi_file_content_file_name_transformation():
    """
    Test that the get_posi_file_content function correctly transforms the file name.
    """
    # Arrange
    mock_s3 = Mock()
    mock_response = {"Body": Mock()}
    mock_response["Body"].read.return_value = b"sample posi content"
    mock_s3.get_object.return_value = mock_response

    # Act
    result = get_posi_file_content(mock_s3, "test-bucket", "test123_prot.txt")

    # Assert
    mock_s3.get_object.assert_called_once_with(
        Bucket="test-bucket", Key="test123_posi.txt"
    )


@pytest.mark.parametrize(
    "input_key,expected_posi_key",
    [
        ("sample_prot.txt", "sample_posi.txt"),
        ("test123_prot.txt", "test123_posi.txt"),
        ("path/to/file_prot.txt", "path/to/file_posi.txt"),
    ],
)
def test_get_posi_file_content_various_paths(input_key, expected_posi_key):
    """
    Test that the get_posi_file_content function correctly transforms various file paths.
    """
    # Arrange
    mock_s3 = Mock()
    mock_response = {"Body": Mock()}
    mock_response["Body"].read.return_value = b"sample posi content"
    mock_s3.get_object.return_value = mock_response

    # Act
    get_posi_file_content(mock_s3, "test-bucket", input_key)

    # Assert
    mock_s3.get_object.assert_called_once_with(
        Bucket="test-bucket", Key=expected_posi_key
    )


@pytest.mark.parametrize(
    "expected_output",
    [
        {
            "file_key": "KH0212_123_prot.txt",
            "metadata": {
                "Cruise": "Test Cruise",
                "Station": "001",
                "Remarks": "Test remarks",
            },
            "descriptive_text": "",
            "task_table": [
                {
                    "Task": "Sample Task",
                    "PC_Date_and_Time": None,
                    "UTC_Time": "2024-04-27T06:19:45+00:00",
                    "UTC_Date": None,
                    "SHIP_Latitude": -41.2345,
                    "SHIP_Longitude": 174.9876,
                    "SUB_1_Latitude": None,
                    "SUB_1_Longitude": None,
                    "Water_Depth": 2.5,
                }
            ],
            "detailed_data_table": [
                {
                    "Date": None,
                    "Time": "2024-04-27T06:19:45+00:00",
                    "PC_Time": None,
                    "SHIP_Lon": -41.2345,
                    "SHIP_Lat": 174.9876,
                    "SHIP_SOG": 2.5,
                    "SHIP_COG": 180.0,
                    "SHIP_Hdg": 100.5,
                    "Water_Depth": 45.0,
                    "SUB1_Lon": 0.0,
                    "SUB1_Lat": -41.2345,
                    "SUB1_Depth": 174.9876,
                    "SUB1_Altitude": None,
                    "Elapsed_video_Time": "ignored",
                    "Observations_Comments": "general observation",
                    "Image_Video_Path": None,
                }
            ],
        }
    ],
)
def test_parse_detailed_data_line(basic_line, expected_output):
    file_key = "text/KH0212_123_prot.txt"
    file_content = "\n".join(
        [
            "Cruise: Test Cruise",
            "Station: 001",
            "Remarks: Test remarks",
            "",
            "Task: Sample Task",
            "----",
            "#Date\tTime\tPC_Time\tSHIP_Lon\tSHIP_Lat\tSHIP_SOG\tSHIP_COG\tSHIP_Hdg\tWater_Depth\tSUB1_Lon\tSUB1_Lat\tSUB1_Depth\tSUB1_Altitude\tElapsed_video_Time\tObservations_Comments\tImage_Video_Path",
            "06:19:45\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tgeneral observation",
        ]
    )

    result = parse_file_content(file_content, file_key)
    # self.assertEqual(result, expected_output)


# @pytest.mark.parametrize(
#     "file_key, file_content, expected_output",
#     [
#         (
#             "TAN0616_004_obser.txt",
#             """Cruise :\tTAN0616
#             Station :\tDTIS_4_#5
#             Remarks :\tlittle nose west of slump site

#             UTC time\tPC time\tLat\tLon\tSpeed\tCourse\tDepth\tHeading\tSub Lat\tSub Lon\tNotes
#             14:07:27\t04.11.2006 03:07:26\t-40.04765\t178.14625\t1.4\t308.5\t1006.9\t331.9\t0\t0\ttest
#             14:08:56\t04.11.2006 03:08:55\t-40.0395\t178.1433\t0.8\t334.8\t749.8\t344.6\t-40.0432856\t178.14325402\tAT THE BOTTOM""",
#             {
#                 "file_key": "TAN0616_004_obser.txt",
#                 "metadata": {
#                     "Cruise": "TAN0616",
#                     "Station": "DTIS_4_#5",
#                     "Remarks": "little nose west of slump site",
#                 },
#                 "detailed_data_table": [
#                     {
#                         "UTC_time": "2006-11-04T14:07:27+00:00",
#                         "PC_time": "2006-11-04T03:07:26+00:00",
#                         "Lat": -40.04765,
#                         "Lon": 178.14625,
#                         "Speed": 1.4,
#                         "Course": 308.5,
#                         "Depth": 1006.9,
#                         "Heading": 331.9,
#                         "Sub_Lat": 0.0,
#                         "Sub_Lon": 0.0,
#                         "Notes": "test",
#                     },
#                     {
#                         "UTC_time": "2006-11-04T14:08:56+00:00",
#                         "PC_time": "2006-11-04T03:08:55+00:00",
#                         "Lat": -40.0395,
#                         "Lon": 178.1433,
#                         "Speed": 0.8,
#                         "Course": 334.8,
#                         "Depth": 749.8,
#                         "Heading": 344.6,
#                         "Sub_Lat": -40.0432856,
#                         "Sub_Lon": 178.14325402,
#                         "Notes": "AT THE BOTTOM",
#                     },
#                 ],
#             },
#         ),
#         # Add additional parameter sets here...
#     ],
#     ids=[
#         "valid_original_format_test_case_1",
#         # Add matching ids for each parameter set, e.g.,
#         # "valid_original_format_test_case_2",
#         # ...
#     ],
# )
# def test_parse_original_format(file_key, file_content, expected_output):
#     result = parse_file_content(file_content, file_key)
#     assert result == expected_output


@pytest.mark.parametrize(
    "line,expected_results,file_format",
    [
        (
            "04/16/2022 20:33:30\t20:33:30\t-178.102472\t-24.003802\t0.45\t239.99\t25.03\t2607.8\t0\t0\t0\t0\t\00:00:00\tDTIS photo: 1; volt: 25.7; magn. fs: 7954",
            {
                "timestamp": "04/16/2022 20:33:30",
                "shipLocation": {
                    "type": "Point",
                    "coordinates": [-178.102472, -23.003802],
                },
                "subLocation": {
                    "type": "Point",
                    "coordinates": [0, 0],
                },
                "feature": {
                    "media": "",
                    "mediaType": "",
                    "mediaOffset": None,
                    "observation": "DTIS photo: 1; volt: 25.7; magn. fs: 7954",
                    "observation2": None,
                    "observation_source": "new",
                    "observationRef": "<a href='https://www.marinespecies.org/rest/AphiaRecordsByMatchNames?scientificnames%5B%5D=SUB&marine_only=true'>Try a WORMS search for SUB</a>",
                },
            },
            "latest",
        ),
        (
            "04/16/2022\t23:07:19\t-178.094219\t-23.995539\t[-99]\t[-99] SUB",
            {
                "timestamp": "04/16/2022 23:07:19",
                "shipLocation": {
                    "type": "Point",
                    "coordinates": [-178.094219, -23.995539],
                },
                "subLocation": {
                    "type": "Point",
                    "coordinates": [-178.094219, -23.995539],
                },
                "feature": {
                    "media": "",
                    "mediaType": "",
                    "mediaOffset": None,
                    "observation": "SUB",
                    "observation2": None,
                    "observation_source": "new",
                    "observationRef": "<a href='https://www.marinespecies.org/rest/AphiaRecordsByMatchNames?scientificnames%5B%5D=SUB&marine_only=true'>Try a WORMS search for SUB</a>",
                },
            },
            "new",
        ),
        (
            "12:34:56\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tgeneral observation",
            {
                "timestamp": "12:34:56",
                "shipLocation": {
                    "type": "Point",
                    "coordinates": [174.9876, -41.2345],
                },
                "speed": 2.5,
                "course": 180.0,
                "depth": 100.5,
                "heading": 45.0,
                "subLocation": {
                    "type": "Point",
                    "coordinates": [174.9876, -41.2345],
                },
                "feature": {
                    "media": "",
                    "mediaType": "",
                    "mediaOffset": None,
                    "observation": "general observation",
                    "observation2": None,
                    "observation_source": "original",
                    "observationRef": "<a href='https://www.marinespecies.org/rest/AphiaRecordsByMatchNames?scientificnames%5B%5D=general observation&marine_only=true'>Try a WORMS search for general observation</a>",
                },
            },
            "original",
        ),
        ("12:34:56\tonly_three_fields\tfield3", None, "original"),
    ],
)
def test_parse_data_line(line, expected_results, source_key, file_format):
    """
    Test parsing of a data line.
    """
    result, video_start, video_events = parse_data_line(
        line, source_key, None, [], file_format
    )

    if expected_results is None:
        assert result is None
    else:
        assert result is not None
        # Verify each top-level key exists
        for key in expected_results:
            assert key in result, f"Expected key '{key}' not found in result"

            # Handle nested dictionaries for location data
            if key in ["shipLocation", "subLocation"]:
                assert result[key]["type"] == "Point"
                assert len(result[key]["coordinates"]) == 2
                assert (
                    abs(
                        result[key]["coordinates"][0]
                        - expected_results[key]["coordinates"][0]
                    )
                    < 0.0001
                )
                assert (
                    abs(
                        result[key]["coordinates"][1]
                        - expected_results[key]["coordinates"][1]
                    )
                    < 0.0001
                )
            # Handle regular numeric values
            elif key in ["speed", "course", "depth", "heading"]:
                assert abs(float(result[key]) - expected_results[key]) < 0.0001
            # Handle feature dictionary
            elif key == "feature":
                for feature_key in expected_results[key]:
                    assert feature_key in result[key]
                    assert (
                        result[key][feature_key] == expected_results[key][feature_key]
                    )
            # Handle other values
            else:
                assert result[key] == expected_results[key]


def test_parse_data_line_new_format(new_format_line, new_format_header, source_key):
    """
    Test parsing of a data line in the new format (for reruns).
    """
    result, video_start, video_events = parse_data_line(
        new_format_line,
        source_key,
        None,
        [],
        file_format="new",
    )

    expected_results = {
        "timestamp": "14:08:08",
        "shipLocation": {"type": "Point", "coordinates": [173.6320797, -42.5125708]},
        "subLocation": {"type": "Point", "coordinates": [173.6320797, -42.5125708]},
        "speed": None,
        "course": None,
        "depth": None,
        "heading": None,
        "feature": {
            "media": "",
            "mediaType": "",
            "mediaOffset": None,
            "observation": "[29] OBSCURED",
            "observation2": None,
            "observation_source": "new",
            "observationRef": "<a href='https://www.marinespecies.org/rest/AphiaRecordsByMatchNames?scientificnames%5B%5D=OBSCURED&marine_only=true'>Try a WORMS search for OBSCURED</a>",
        },
    }

    assert result is not None
    for key in expected_results:
        assert key in result
        if key in ["shipLocation", "subLocation"]:
            assert result[key]["type"] == "Point"
            assert len(result[key]["coordinates"]) == 2
            assert (
                abs(
                    result[key]["coordinates"][0]
                    - expected_results[key]["coordinates"][0]
                )
                < 0.0001
            )
            assert (
                abs(
                    result[key]["coordinates"][1]
                    - expected_results[key]["coordinates"][1]
                )
                < 0.0001
            )


@pytest.mark.parametrize(
    "observation,expected_video_state",
    [
        (
            "video started",
            {"event_count": 1, "event_type": "start", "has_video_start": True},
        ),
        (
            "start video",
            {"event_count": 1, "event_type": "start", "has_video_start": True},
        ),
        (
            "Video Started at surface",
            {"event_count": 1, "event_type": "start", "has_video_start": True},
        ),
        (
            "video stopped",
            {"event_count": 1, "event_type": "stop", "has_video_start": False},
        ),
        (
            "general observation",
            {"event_count": 0, "event_type": None, "has_video_start": False},
        ),
    ],
)
def test_parse_data_line_video_events(
    basic_line, source_key, observation, expected_video_state
):
    """
    Test parsing of data lines with video events.
    """
    # Arrange
    line = basic_line.rsplit("\t", 1)[0] + "\t" + observation
    video_events = []

    # For stop events, we need to simulate a previous start event
    if observation.lower().find("stop") >= 0:
        video_start = "12:34:00"  # Keep as string, parse_data_line will convert it
    else:
        video_start = None

    # Act
    result, video_start_after, video_events = parse_data_line(
        line, source_key, video_start, video_events
    )

    # Debug output
    print(f"\nObservation: {observation}")
    print(f"Video start: {video_start}")
    print(f"Video start after: {video_start_after}")
    print(f"Video events: {video_events}")
    print(f"Result: {result}")

    # Assert
    assert len(video_events) == expected_video_state["event_count"]

    if expected_video_state["event_count"] > 0:
        assert video_events[0]["event"] == expected_video_state["event_type"]


def time_test_cases():
    """
    Return test cases for time parsing.
    """
    return [
        {"time_str": "23:59:59", "expected": "23:59:59"},
        {"time_str": "00:00:00", "expected": "00:00:00"},
        # Add more test cases as needed
    ]


@pytest.mark.parametrize("test_case", time_test_cases())
def test_parse_data_line_time_parsing(test_case, basic_line):
    """
    Test parsing of data lines with different time formats.
    """
    line = test_case["time_str"] + basic_line[8:]  # Replace time in basic line

    result, _, _ = parse_data_line(line, "test_key_prot.txt", None, [])

    assert isinstance(result["timestamp"], str)
    assert result["timestamp"] == test_case["expected"]
    # assert result["timestamp"].hour == test_case["expected"]["hour"]
    # assert result["timestamp"].minute == test_case["expected"]["minute"]
    # assert result["timestamp"].second == test_case["expected"]["second"]


@pytest.mark.parametrize(
    "input_str, expected_output",
    [
        # Valid time strings
        ("08:41:57", "08:41:57"),
        ("00:00:00", "00:00:00"),
        ("23:59:59", "23:59:59"),
        # Invalid time formats
        ("8:41:57", None),  # Leading zero missing
        ("08:41", None),  # Seconds missing
        ("24:00:00", None),  # Invalid hour
        ("12:60:00", None),  # Invalid minute
        ("12:00:60", None),  # Invalid second
        ("", None),
        (None, None),
        # Edge cases
        ("12:34:56", "12:34:56"),
        ("01:01:01", "01:01:01"),
    ],
)
def test_parse_time_only(input_str, expected_output):
    assert parse_time_only(input_str) == expected_output


@pytest.mark.parametrize(
    "input_str, expected_output",
    [
        # Valid datetime strings with timezone
        ("16/04/2022 08:41:57", "2022-04-16T08:41:57+00:00"),
        ("01/01/2023 00:00:00", "2023-01-01T00:00:00+00:00"),
        ("31/12/2021 23:59:59", "2021-12-31T23:59:59+00:00"),
        # Invalid datetime formats
        ("2022-04-16 08:41:57", None),
        ("16-04-2022 08:41", None),
        ("16/04/22 08:41:57", None),
        ("", None),
        (None, None),
        # Edge cases - we are converting the times with timezone information for UTC
        ("29/02/2020 12:00:00", "2020-02-29T12:00:00+00:00"),  # Leap year
        ("31/04/2022 10:30:00", None),  # Invalid date (April has 30 days)
    ],
)
def test_parse_datetime(input_str, expected_output):
    assert parse_datetime(input_str) == expected_output


@pytest.mark.parametrize(
    "sequence_times,expected_duration",
    [
        (["12:34:00", "12:34:30", "12:35:00"], timedelta(minutes=1)),
        (["12:34:00", "12:34:15", "12:34:30"], timedelta(seconds=30)),
    ],
)
def test_parse_data_line_video_sequences(sequence_times, expected_duration):
    """
    Test parsing of data lines with video sequences.
    """
    # Create the test lines with video events
    lines = [
        f"{time}\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\t{event}"
        for time, event in zip(
            sequence_times, ["video started", "general observation", "video stopped"]
        )
    ]

    video_events = []
    video_start = None

    # Process each line
    for line in lines:
        _, video_start, video_events = parse_data_line(
            line, "test_key_prot.txt", video_start, video_events
        )

    # Verify the results
    assert len(video_events) == 2
    assert video_events[0]["event"] == "start"
    assert video_events[1]["event"] == "stop"
    assert video_events[1]["duration"] == str(expected_duration)


def test_parse_data_line_invalid_format():
    """
    Test parsing of data lines with an invalid format.
    """
    # Arrange
    invalid_line = "12:34:56\tonly_three_fields\tfield3"

    # Act
    result, video_start, video_events = parse_data_line(
        invalid_line, "test_key", None, []
    )

    # Assert
    assert result is None
    assert video_start is None
    assert len(video_events) == 0


@pytest.mark.parametrize(
    "observation,expected_media_type,expected_media_path",
    [
        ("photo 123", "photo", "/images/TAN2306_123/TAN2306_123_12.jpg"),
        ("taking photo 456", "photo", "/images/TAN2306_123/TAN2306_123_12.jpg"),
        ("general observation", "", ""),
    ],
)
@pytest.mark.skip(
    reason="Not properly implemented yet - currently not expecting this test to pass"
)
def test_parse_data_line_media_types(
    basic_line, source_key, observation, expected_media_type, expected_media_path
):
    """
    Test parsing of data lines to extract different media types (video/photo).
    """
    # Arrange
    line = basic_line.rsplit("\t", 1)[0] + "\t" + observation

    # Act
    result, _, _ = parse_data_line(line, source_key, None, [])

    # Debug output
    print(f"\nObservation: {observation}")
    print(f"Result: {result}")
    print(f"Feature dict: {result['feature']}")

    # Assert
    assert result["feature"]["mediaType"] == expected_media_type
    assert result["feature"]["media"] == expected_media_path


def test_parse_data_line_complete_video_sequence():
    """
    Test parsing of complete set of data lines with video sequences.
    """
    # Arrange
    lines = [
        "12:34:00\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tvideo started",
        "12:34:30\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tgeneral observation",
        "12:35:00\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tvideo stopped",
    ]
    video_events = []
    video_start = None

    # Act
    for line in lines:
        _, video_start, video_events = parse_data_line(
            line, "test_key_prot.txt", video_start, video_events, "original"
        )

    # Assert
    assert len(video_events) == 2
    assert video_events[0]["event"] == "start"
    assert video_events[1]["event"] == "stop"
    assert video_events[1]["duration"] == str(timedelta(minutes=1))


@pytest.mark.skip(
    reason="Not properly implemented yet - currently not expecting this test to pass"
)
@pytest.mark.parametrize(
    "file_key, file_content, expected_output",
    [
        (
            "TAN0616_DTIS_4_#5_prot.txt",
            "\n".join(
                [
                    "Cruise :\tTAN0616",
                    "Station :\tDTIS_4_#5",
                    "Remarks :\tlittle nose west of slump site",
                    "",
                    "UTC time\tPC time\tLat\tLon\tSpeed\tCourse\tDepth\tHeading\tSub Lat\tSub Lon\t\t\t\tNotes",
                    "14:07:27\t04.11.2006 03:07:26\t-40.04765\t178.14625\t1.4\t308.5\t1006.9\t331.9\t0\t0\t-40.04754795\t178.14616817\t\ttest",
                ]
            ),
            [
                {
                    "file_key": "TAN0616_005_prot.txt",
                    "metadata": {
                        "Cruise": "TAN0616",
                        "Station": "DTIS_4_#5",
                        "Remarks": "little nose west of slump site",
                    },
                    "detailed_data_table": [
                        {
                            "UTC_time": "2006-11-04T14:07:27+00:00",
                            "PC_time": "2006-04-16T03:07:26+00:00",
                            "Lat": -40.04765,
                            "Lon": 178.14625,
                            "Speed": 1.4,
                            "Course": 308.5,
                            "Depth": 1006.9,
                            "Heading": 331.9,
                            "Sub_Lat": 0.0,
                            "Sub_Lon": 0.0,
                            "Notes": "test",
                        }
                    ],
                },
                "original",
            ],
        ),
    ],
)
def test_parse_original_format(file_key, file_content, expected_output):
    result, fileformat = parse_file_content(file_content, file_key)
    assert result == expected_output
    assert fileformat == "original"


@pytest.mark.skip(
    reason="Not properly implemented yet - currently not expecting this test to pass"
)
@pytest.mark.parametrize(
    "file_key, file_content, expected_output",
    [
        (
            "TAN2206_009_obser.txt",
            """Cruise     :	TAN2206
Station    :	9
Remarks    :	Far field site 1
Sadie calling, Rob OFOP, Neill DTIS
Very flat seafloor at a depth of 2507 m. Very consistant substrate of muddy sediment with gravels, pebbles, cobbles and the occasional boulder. Fauna was sparse with a few shrimps, holothurians, hexactinellid sponges and one Umbellula se pen. 
Low numbers of fish and eels but one rattail was observed.
OFOP entries were sometimes made for for long straight objects as either sea pens/hexactinellids which were difficult to determine. But confirmed ID's were made of both groups. 

Task             :	PC Date and Time   	UTC Time	UTC Date	SHIP Latitude	SHIP Longitude	SUB_1 Latitude	SUB_1 Longitude	Water Depth
In the Water     :	16/04/2022 08:41:57	20:41:57	16/04/2022 06:33:55	-24:0.222	-178:6.154	0:00.0000	0:00.0000	2607.8
At the Bottom    :	16/04/2022 09:26:48	21:26:48	16/04/2022 06:33:55	-24:0.155	-178:6.113	-24:00.2055	-178:06.1496	2607.1
Off the Bottom   :	16/04/2022 10:28:55	22:28:55	16/04/2022 06:33:55	-23:59.713	-178:5.635	-23:59.8844	-178:05.7859	2606.3
On Deck          :	16/04/2022 11:09:01	23:09:01	16/04/2022 06:33:55	-23:59.723	-178:5.649	-23:59.7294	-178:05.6544	2606.3
Gear deployed    :	  :  :  
--------------------------------------------------------------------------------------------------------------------------------------------
#Date	Time	PC_Time	SHIP_Lon	SHIP_Lat	SHIP_SOG	SHIP_COG	SHIP_Hdg	Water_Depth	SUB1_Lon	SUB1_Lat	SUB1_Depth	SUB1_Altitude	Elapsed video Time	Observations/Comments	Image-Video Path
04/16/2022	20:33:30	16/04/2022 08:33:30	-178.102472	-24.0038202	0.45	239.99	25.03	2607.8	0	0	0	0	00:00:00		DTIS photo: 1; volt: 25.7; magn. fs: 7954 
04/16/2022	20:41:55	16/04/2022 08:41:55	-178.1025627	-24.0037027	0.76	194	46.09	2607.8	0	0	0	0	00:00:00		[-81] IN THE WATER
04/16/2022	21:26:46	16/04/2022 09:26:46	-178.1018923	-24.002586	0.97	90.85	52.01	2607.1	-178.102493	-24.003425	0	0	00:00:00		[-82] AT THE BOTTOM
04/16/2022	21:27:52	16/04/2022 09:27:52	-178.1017558	-24.0024527	1.16	23.51	47.37	2607.1	-178.102426	-24.003378	0	0	00:00:00		[-86] Start video recording: Tape 1
04/16/2022	21:28:00	16/04/2022 09:27:59	-178.1017397	-24.002429	1.58	50.32	48.38	2606.3	-178.102426	-24.003378	0	34	00:00:07		[7] Muddy sed.
04/16/2022	21:28:01	16/04/2022 09:28:01	-178.1017355	-24.0024235	1.21	33	48.82	2607.1	-178.102408	-24.003371	0	34	00:00:09		DTIS photo: 2; volt: 24.5; magn. fs: 9418 
04/16/2022	21:28:02	16/04/2022 09:28:02	-178.1017335	-24.0024222	0.29	130.55	49.18	2607.1	-178.102408	-24.003371	0	34	00:00:10		[29] OBSCURED
""",
            {
                "file_key": "TAN2206_009_obser.txt",
                "metadata": {
                    "Cruise": "TAN2206",
                    "Station": "009",
                    "Remarks": "Far field site 1",
                },
                "tasks": [
                    {
                        "Task": "In the Water",
                        "PC Date and Time": "2022-04-16T08:41:57",
                        "UTC Time": "20:41:57",
                        "UTC Date": "16/04/2022",
                        "SHIP Latitude": -24.0,  # Example conversion
                        "SHIP Longitude": -178.6,  # Example conversion
                        "SUB_1 Latitude": 0.0,
                        "SUB_1 Longitude": 0.0,
                        "Water Depth": 2607.8,
                    },
                    # Add more task entries as needed...
                ],
                "detailed_data_table": [
                    {
                        "Date": "2022-04-16T00:00:00",
                        "Time": "20:33:30",
                        "PC_Time": "2022-04-16T08:33:30",
                        "SHIP_Lon": -178.102472,
                        "SHIP_Lat": -24.0038202,
                        "SHIP_SOG": 0.45,
                        "SHIP_COG": 239.99,
                        "SHIP_Hdg": 25.03,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "DTIS photo: 1; volt: 25.7; magn. fs: 7954",
                        "Image-Video Path": "",
                    },
                    # Add more data entries as needed...
                ],
            },
        ),
        # Add additional parameter sets here...
    ],
    ids=[
        "test_latest_format_case_1",
        # "test_latest_format_case_2",
        # ...
    ],
)
def DEPRECATED_test_parse_latest_format(file_key, file_content, expected_output):
    result, fileformat = parse_file_content(file_content, file_key)
    assert result == expected_output
    assert fileformat == "latest"


@pytest.mark.parametrize(
    "file_key, file_content, expected_output",
    [
        (
            "TAN2206_009_obser.txt",
            """#Date	Time	PC_Time	SHIP_Lon	SHIP_Lat	SHIP_SOG	SHIP_COG	SHIP_Hdg	Water_Depth	SUB1_Lon	SUB1_Lat	SUB1_Depth	SUB1_Altitude	Elapsed video Time	Observations/Comments	Image-Video Path
04/16/2022	20:33:30	16/04/2022 08:33:30	-178.102472	-24.0038202	0.45	239.99	25.03	2607.8	0	0	0	0	00:00:00		DTIS photo: 1; volt: 25.7; magn. fs: 7954 
04/16/2022	20:41:55	16/04/2022 08:41:55	-178.1025627	-24.0037027	0.76	194	46.09	2607.8	0	0	0	0	00:00:00		[-81] IN THE WATER
04/16/2022	21:26:46	16/04/2022 09:26:46	-178.1018923	-24.002586	0.97	90.85	52.01	2607.1	-178.102493	-24.003425	0	0	00:00:00		[-82] AT THE BOTTOM
04/16/2022	21:27:52	16/04/2022 09:27:52	-178.1017558	-24.0024527	1.16	23.51	47.37	2607.1	-178.102426	-24.003378	0	0	00:00:00		[-86] Start video recording: Tape 1
04/16/2022	21:28:00	16/04/2022 09:27:59	-178.1017397	-24.002429	1.58	50.32	48.38	2606.3	-178.102426	-24.003378	0	34	00:00:07		[7] Muddy sed.
04/16/2022	21:28:01	16/04/2022 09:28:01	-178.1017355	-24.0024235	1.21	33	48.82	2607.1	-178.102408	-24.003371	0	34	00:00:09		DTIS photo: 2; volt: 24.5; magn. fs: 9418 
04/16/2022	21:28:02	16/04/2022 09:28:02	-178.1017335	-24.0024222	0.29	130.55	49.18	2607.1	-178.102408	-24.003371	0	34	00:00:10		[29] OBSCURED
""",
            {
                "file_key": "TAN2206_009_obser.txt",
                "metadata": {},
                "tasks": [],
                "detailed_data_table": [
                    {
                        "Date": "2022/04/16T00:00:00",
                        "Time": "20:33:30",
                        "PC_Time": "2022/04/16T08:33:30",
                        "SHIP_Lon": -178.102472,
                        "SHIP_Lat": -24.0038202,
                        "SHIP_SOG": 0.45,
                        "SHIP_COG": 239.99,
                        "SHIP_Hdg": 25.03,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "DTIS photo: 1; volt: 25.7; magn. fs: 7954",
                    },
                    # Add more data entries as needed...
                ],
            },
        ),
        # Add additional parameter sets here...
    ],
    ids=[
        "test_latest_format_case_1",
        # "test_latest_format_case_2",
        # ...
    ],
)
def test_parse_simple_format(file_key, file_content, expected_output):
    result, fileformat = parse_file_content(file_content, file_key)
    assert result == expected_output
    assert fileformat == "simple"


def test_parse_unknown_format(self):
    file_key = "unknown/prot.txt"
    file_content = "\n".join(
        [
            "Some random header",
            "Another random header",
            "Data\tWithout\tProper\tFormat",
        ]
    )

    expected_output = []

    result = parse_file_content(file_content, file_key)
    self.assertEqual(result, expected_output)
    self.assertEqual(result, expected_output)


def test_print_document_format_for_latest_format():
    """
    Test to print the document format for the 'latest' file format.
    """
    file_key = "TAN2206_009_obser.txt"
    file_content = """Cruise     :	TAN2206
Station    :	9
Remarks    :	Far field site 1
Sadie calling, Rob OFOP, Neill DTIS
Very flat seafloor at a depth of 2507 m. Very consistant substrate of muddy sediment with gravels, pebbles, cobbles and the occasional boulder. Fauna was sparse with a few shrimps, holothurians, hexactinellid sponges and one Umbellula se pen. 
Low numbers of fish and eels but one rattail was observed.
OFOP entries were sometimes made for for long straight objects as either sea pens/hexactinellids which were difficult to determine. But confirmed ID's were made of both groups. 

Task             :	PC Date and Time   	UTC Time	UTC Date	SHIP Latitude	SHIP Longitude	SUB_1 Latitude	SUB_1 Longitude	Water Depth
In the Water     :	16/04/2022 08:41:57	20:41:57	16/04/2022 06:33:55	-24:0.222	-178:6.154	0:00.0000	0:00.0000	2607.8
At the Bottom    :	16/04/2022 09:26:48	21:26:48	16/04/2022 06:33:55	-24:0.155	-178:6.113	-24:00.2055	-178:06.1496	2607.1
Off the Bottom   :	16/04/2022 10:28:55	22:28:55	16/04/2022 06:33:55	-23:59.713	-178:5.635	-23:59.8844	-178:05.7859	2606.3
On Deck          :	16/04/2022 11:09:01	23:09:01	16/04/2022 06:33:55	-23:59.723	-178:5.649	-23:59.7294	-178:05.6544	2606.3
Gear deployed    :	  :  :  
--------------------------------------------------------------------------------------------------------------------------------------------
#Date	Time	PC_Time	SHIP_Lon	SHIP_Lat	SHIP_SOG	SHIP_COG	SHIP_Hdg	Water_Depth	SUB1_Lon	SUB1_Lat	SUB1_Depth	SUB1_Altitude	Elapsed video Time	Observations/Comments	Image-Video Path
04/16/2022	20:33:30	16/04/2022 08:33:30	-178.102472	-24.0038202	0.45	239.99	25.03	2607.8	0	0	0	0	00:00:00		DTIS photo: 1; volt: 25.7; magn. fs: 7954 
04/16/2022	20:41:55	16/04/2022 08:41:55	-178.1025627	-24.0037027	0.76	194	46.09	2607.8	0	0	0	0	00:00:00		[-81] IN THE WATER
04/16/2022	21:26:46	16/04/2022 09:26:46	-178.1018923	-24.002586	0.97	90.85	52.01	2607.1	-178.102493	-24.003425	0	0	00:00:00		[-82] AT THE BOTTOM
04/16/2022	21:27:52	16/04/2022 09:27:52	-178.1017558	-24.0024527	1.16	23.51	47.37	2607.1	-178.102426	-24.003378	0	0	00:00:00		[-86] Start video recording: Tape 1
04/16/2022	21:28:00	16/04/2022 09:27:59	-178.1017397	-24.002429	1.58	50.32	48.38	2606.3	-178.102426	-24.003378	0	34	00:00:07		[7] Muddy sed.
04/16/2022	21:28:01	16/04/2022 09:28:01	-178.1017355	-24.0024235	1.21	33	48.82	2607.1	-178.102408	-24.003371	0	34	00:00:09		DTIS photo: 2; volt: 24.5; magn. fs: 9418 
04/16/2022	21:28:02	16/04/2022 09:28:02	-178.1017335	-24.0024222	0.29	130.55	49.18	2607.1	-178.102408	-24.003371	0	34	00:00:10		[29] OBSCURED
"""
    result, fileformat = parse_file_content(file_content, file_key)
    documents, sub_coordinates = prepare_documents(
        MagicMock(),
        result["detailed_data_table"],
        file_key,
        {},
        "TAN2206",
        "9",
        "Far field site 1",
        file_format="latest",
    )
    # Add assertions to verify the expected structure and content
    assert isinstance(documents, list)
    assert len(documents) > 0
    # Add more specific assertions about the expected document format
    print("fileformat: ", fileformat)
    print(json.dumps(documents, indent=2))


@pytest.mark.parametrize(
    "lines, expected_format",
    [
        (["Cruise : Test Cruise", "UTC Time\tPC Time\tLat"], "original"),
        (["Cruise : Test Cruise", "#Date\tTime\tPC_Time\tSHIP_Lon"], "latest"),
        (["Cruise : Test Cruise", "#Date\tTime\tPC_Time"], "new"),
        (["#Date\tTime\tPC_Time"], "latest"),
        (["#Date\tTime\tSUB1_Lon\tSUB1_Lat\tID_Number\tID_Name"], "simple"),
        (["#Date\tTime\tPC_Time\tSHIP_Lon"], "latest"),
        (["#Date\sTime\sPC_Time"], "unknown"),
        (["Some random text"], "unknown"),
        # New test case for 'latest' format
        (
            [
                "Cruise     :\tTAN2206",
                "Station    :\t9",
                "Remarks    :\tFar field site 1",
                "Sadie calling, Rob OFOP, Neill DTIS",
                "Very flat seafloor at a depth of 2507 m. Very consistant substrate of muddy sediment with gravels, pebbles, cobbles and the occasional boulder. Fauna was sparse with a few shrimps, holothurians, hexactinellid sponges and one Umbellula se pen. ",
                "Low numbers of fish and eels but one rattail was observed.",
                "OFOP entries were sometimes made for for long straight objects as either sea pens/hexactinellids which were difficult to determine. But confirmed ID's were made of both groups. ",
                "",
                "Task             :\tPC Date and Time    \tUTC Time\tUTC Date\tSHIP Latitude\tSHIP Longitude\tSUB_1 Latitude\tSUB_1 Longitude\tWater Depth",
                "In the Water     :\t16/04/2022 08:41:57\t20:41:57\t16/04/2022 06:33:55\t-24:0.222\t-178:6.154\t0:00.0000\t0:00.0000\t2607.8",
                "At the Bottom    :\t16/04/2022 09:26:48\t21:26:48\t16/04/2022 06:33:55\t-24:0.155\t-178:6.113\t-24:00.2055\t-178:06.1496\t2607.1",
                "Off the Bottom   :\t16/04/2022 10:28:55\t22:28:55\t16/04/2022 06:33:55\t-23:59.713\t-178:5.635\t-23:59.8844\t-178:05.7859\t2606.3",
                "On Deck          :\t16/04/2022 11:09:01\t23:09:01\t16/04/2022 06:33:55\t-23:59.723\t-178:5.649\t-23:59.7294\t-178:05.6544\t2606.3",
                "Gear deployed    :\t  :  :  ",
                "--------------------------------------------------------------------------------------------------------------------------------------------",
                "#Date\tTime\tPC_Time\tSHIP_Lon\tSHIP_Lat\tSHIP_SOG\tSHIP_COG\tSHIP_Hdg\tWater_Depth\tSUB1_Lon\tSUB1_Lat\tSUB1_Depth\tSUB1_Altitude\tElapsed video Time\tObservations/Comments\tImage-Video Path",
                "04/16/2022\t20:33:30\t16/04/2022 08:33:30\t-178.102472\t-24.0038202\t0.45\t239.99\t25.03\t2607.8\t0\t0\t0\t0\t00:00:00\t\tDTIS photo: 1; volt: 25.7; magn. fs: 7954 ",
                "04/16/2022\t20:41:55\t16/04/2022 08:41:55\t-178.1025627\t-24.0037027\t0.76\t194\t46.09\t2607.8\t0\t0\t0\t0\t00:00:00\t\t[-81] IN THE WATER",
            ],
            "latest",
        ),
        # You can add more test cases here
    ],
)
def test_detect_file_format(lines, expected_format):
    """
    Test the detect_file_format function with various header patterns.
    """
    result = detect_file_format(lines)
    assert result == expected_format


def test_parse_tasks_latest_format():
    lines = [
        "Cruise     :\tTAN2206",
        "Station    :\t9",
        "Remarks    :\tFar field site 1",
        "Sadie calling, Rob OFOP, Neill DTIS",
        "Very flat seafloor at a depth of 2507 m. Very consistant substrate of muddy sediment with gravels, pebbles, cobbles and the occasional boulder. Fauna was sparse with a few shrimps, holothurians, hexactinellid sponges and one Umbellula se pen. ",
        "Low numbers of fish and eels but one rattail was observed.",
        "OFOP entries were sometimes made for for long straight objects as either sea pens/hexactinellids which were difficult to determine. But confirmed ID's were made of both groups. ",
        "",
        "Task             :\tPC Date and Time    \tUTC Time\tUTC Date\tSHIP Latitude\tSHIP Longitude\tSUB_1 Latitude\tSUB_1 Longitude\tWater Depth",
        "In the Water     :\t16/04/2022 08:41:57\t20:41:57\t16/04/2022 06:33:55\t-24:0.222\t-178:6.154\t0:00.0000\t0:00.0000\t2607.8",
        "At the Bottom    :\t16/04/2022 09:26:48\t21:26:48\t16/04/2022 06:33:55\t-24:0.155\t-178:6.113\t-24:00.2055\t-178:06.1496\t2607.1",
        "Off the Bottom   :\t16/04/2022 10:28:55\t22:28:55\t16/04/2022 06:33:55\t-23:59.713\t-178:5.635\t-23:59.8844\t-178:05.7859\t2606.3",
        "On Deck          :\t16/04/2022 11:09:01\t23:09:01\t16/04/2022 06:33:55\t-23:59.723\t-178:5.649\t-23:59.7294\t-178:05.6544\t2606.3",
        "Gear deployed    :\t  :  :  ",
        "--------------------------------------------------------------------------------------------------------------------------------------------",
        "#Date\tTime\tPC_Time\tSHIP_Lon\tSHIP_Lat\tSHIP_SOG\tSHIP_COG\tSHIP_Hdg\tWater_Depth\tSUB1_Lon\tSUB1_Lat\tSUB1_Depth\tSUB1_Altitude\tElapsed video Time\tObservations/Comments\tImage-Video Path",
        "04/16/2022\t20:33:30\t16/04/2022 08:33:30\t-178.102472\t-24.0038202\t0.45\t239.99\t25.03\t2607.8\t0\t0\t0\t0\t00:00:00\t\tDTIS photo: 1; volt: 25.7; magn. fs: 7954 ",
        "04/16/2022\t20:41:55\t16/04/2022 08:41:55\t-178.1025627\t-24.0037027\t0.76\t194\t46.09\t2607.8\t0\t0\t0\t0\t00:00:00\t\t[-81] IN THE WATER",
    ]
    start_idx = 0  # Adjust based on where tasks start in the actual implementation
    expected_tasks = [
        {
            "Task": "In the Water",
            "PC Date and Time": "2022-04-16T08:41:57",
            "UTC Time": "20:41:57",
            "UTC Date": "2022-04-16T06:33:55",
            "SHIP Latitude": "-24:0.222",
            "SHIP Longitude": "-178:6.154",
            "SUB_1 Latitude": "0:00.0000",
            "SUB_1 Longitude": "0:00.0000",
            "Water Depth": "2607.8",
        },
        {
            "Task": "At the Bottom",
            "PC Date and Time": "2022-04-16T09:26:48",
            "UTC Time": "21:26:48",
            "UTC Date": "2022-04-16T06:33:55",
            "SHIP Latitude": "-24:0.155",
            "SHIP Longitude": "-178:6.113",
            "SUB_1 Latitude": "-24:00.2055",
            "SUB_1 Longitude": "-178:06.1496",
            "Water Depth": "2607.1",
        },
        {
            "Task": "Off the Bottom",
            "PC Date and Time": "2022-04-16T10:28:55",
            "UTC Time": "22:28:55",
            "UTC Date": "2022-04-16T06:33:55",
            "SHIP Latitude": "-23:59.713",
            "SHIP Longitude": "-178:5.635",
            "SUB_1 Latitude": "-23:59.8844",
            "SUB_1 Longitude": "-178:05.7859",
            "Water Depth": "2606.3",
        },
        {
            "Task": "On Deck",
            "PC Date and Time": "2022-04-16T11:09:01",
            "UTC Time": "23:09:01",
            "UTC Date": "2022-04-16T06:33:55",
            "SHIP Latitude": "-23:59.723",
            "SHIP Longitude": "-178:5.649",
            "SUB_1 Latitude": "-23:59.7294",
            "SUB_1 Longitude": "-178:05.6544",
            "Water Depth": "2606.3",
        },
    ]

    parsed_tasks = parse_tasks(lines, start_idx)
    assert parsed_tasks == expected_tasks


@pytest.mark.parametrize(
    "parsed_data, file_key, expected_document",
    [
        (
            {
                "metadata": {
                    "Cruise": "TAN2206",
                    "Station": "9",
                    "Remarks": "Far field site 1",
                },
                "tasks": [
                    {
                        "Task_Name": "Sample Task",
                        "Task_Detail": "Detail of the task",
                    }
                ],
                "detailed_data_table": [
                    {
                        "Date": "2022-04-16",
                        "Time": "20:33:30",
                        "PC_Time": "2022-04-16T08:33:30",
                        "SHIP_Lon": -178.102472,
                        "SHIP_Lat": -24.0038202,
                        "SHIP_SOG": 0.45,
                        "SHIP_COG": 239.99,
                        "SHIP_Hdg": 25.03,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "DTIS photo: 1; volt: 25.7; magn. fs: 7954",
                    }
                ],
            },
            "TAN2206/009/text/TAN2206_009_prot.txt",
            {
                "file_key": "TAN2206/009/text/TAN2206_009_prot.txt",
                "meta": {
                    "cruiseStationId": "673bc96288f3596d483ba885",
                    "cruise": "TAN2206",
                    "station": "9",
                    "remarks": "Far field site 1",
                    "ingressId": 1,
                    "created_at": "2024-11-18T23:10:26.905034+00:00",
                },
                "timestamp": "2022-04-16T08:33:30",
                "shipLocation": {
                    "type": "Point",
                    "coordinates": [-178.102472, -24.0038202],
                },
                "speed": 0.45,
                "course": 239.99,
                "heading": 25.03,
                "depth": 2607.8,
                "subLocation": {"type": "Point", "coordinates": [0.0, 0.0]},
                "subDepth": 0.0,
                "feature": {
                    "Task_Name": "Sample Task",
                    "Task_Detail": "Detail of the task",
                },
            },
        ),
        # You can add more test cases as needed
        (
            {
                "metadata": {
                    "Cruise": "TAN2207",
                    "Station": "10",
                    "Remarks": "Another site",
                },
                "tasks": [],  # Empty tasks
                "detailed_data_table": [
                    {
                        "Date": "2022-05-17",
                        "Time": "21:43:31",
                        "PC_Time": "2022-05-17T09:43:31",
                        "SHIP_Lon": -179.102472,
                        "SHIP_Lat": -25.0038202,
                        "SHIP_SOG": 0.55,
                        "SHIP_COG": 250.99,
                        "SHIP_Hdg": 30.03,
                        "Water_Depth": 2707.8,
                        "SUB1_Lon": 1.0,
                        "SUB1_Lat": 1.0,
                        "SUB1_Depth": 1.0,
                        "SUB1_Altitude": 1.0,
                        "Elapsed video Time": "00:00:05",
                        "Observations/Comments": "",
                        "Image-Video Path": "DTIS photo: 2; volt: 26.7; magn. fs: 8054",
                    }
                ],
            },
            "TAN2207/010/text/TAN2207_010_prot.txt",
            {
                "file_key": "TAN2207/010/text/TAN2207_010_prot.txt",
                "meta": {
                    "cruiseStationId": "673bc96288f3596d483ba886",
                    "cruise": "TAN2207",
                    "station": "10",
                    "remarks": "Another site",
                    "ingressId": 1,
                    "created_at": "2024-11-18T23:10:26.905034+00:00",
                },
                "timestamp": "2022-05-17T09:43:31",
                "shipLocation": {
                    "type": "Point",
                    "coordinates": [-179.102472, -25.0038202],
                },
                "speed": 0.55,
                "course": 250.99,
                "heading": 30.03,
                "depth": 2707.8,
                "subLocation": {"type": "Point", "coordinates": [1.0, 1.0]},
                "subDepth": 1.0,
                "feature": {},  # Empty because 'tasks' is empty
            },
        ),
        # can add more test cases as needed
    ],
)
@patch("lambda_function_mongoDB_schema.get_current_ingress_id", return_value=1)
@patch("lambda_function_mongoDB_schema.ObjectId")
@patch("lambda_function_mongoDB_schema.datetime")
def DEPRECATED_test_prepare_documents(
    mock_datetime,
    mock_object_id,
    mock_get_current_ingress_id,
    parsed_data,
    file_key,
    expected_document,
):
    """
    Test the prepare_documents function to ensure it correctly transforms parsed data into the desired MongoDB schema.

    Args:
        mock_object_id (Mock): Mocked ObjectId instance.
        mock_datetime (Mock): Mocked datetime instance.
        parsed_data (dict): The input parsed data.
        file_key (str): The S3 file key.
        expected_document (dict): The expected MongoDB document.
    """
    # Setup the mock for ObjectId
    mock_object_id.return_value = "673bc96288f3596d483ba885"

    # Setup the mock for datetime.now()
    mock_datetime.now.return_value = datetime(
        2024, 11, 18, 23, 10, 26, 905034, tzinfo=timezone.utc
    )

    # Create a mock ingress_collection (if necessary)
    mock_ingress_collection = MagicMock()

    # Call the function under test
    document = prepare_documents(parsed_data, file_key, mock_ingress_collection)

    # Assertions to verify the correctness of the prepared document
    assert document["file_key"] == expected_document["file_key"]

    # Verify meta section
    assert (
        document["meta"]["cruiseStationId"]
        == expected_document["meta"]["cruiseStationId"]
    )
    assert document["meta"]["cruise"] == expected_document["meta"]["cruise"]
    assert document["meta"]["station"] == expected_document["meta"]["station"]
    assert document["meta"]["remarks"] == expected_document["meta"]["remarks"]
    assert document["meta"]["ingressId"] == expected_document["meta"]["ingressId"]
    assert document["meta"]["created_at"] == expected_document["meta"]["created_at"]

    # Verify other fields
    assert document["timestamp"] == expected_document["timestamp"]
    assert document["shipLocation"] == expected_document["shipLocation"]
    assert document["speed"] == expected_document["speed"]
    assert document["course"] == expected_document["course"]
    assert document["heading"] == expected_document["heading"]
    assert document["depth"] == expected_document["depth"]
    assert document["subLocation"] == expected_document["subLocation"]
    assert document["subDepth"] == expected_document["subDepth"]
    assert document["feature"] == expected_document["feature"]


@pytest.mark.parametrize(
    "parsed_data, file_key, expected_documents",
    [
        # Test Case 1: Empty tasks and multiple observations
        (
            {
                "metadata": {
                    "Cruise": "TAN2206",
                    "Station": "9",
                    "Remarks": "Far field site 1",
                },
                # "tasks" field is removed
                "detailed_data_table": [
                    {
                        "Date": "2022-04-16",
                        "Time": "20:33:30",
                        "PC_Time": "2022-04-16T08:33:30",
                        "SHIP_Lon": -178.102472,
                        "SHIP_Lat": -24.0038202,
                        "SHIP_SOG": 0.45,
                        "SHIP_COG": 239.99,
                        "SHIP_Hdg": 25.03,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "DTIS photo: 1; volt: 25.7; magn. fs: 7954 ",
                    },
                    {
                        "Date": "2022-04-16",
                        "Time": "20:41:55",
                        "PC_Time": "2022-04-16T08:41:55",
                        "SHIP_Lon": -178.1025627,
                        "SHIP_Lat": -24.0037027,
                        "SHIP_SOG": 0.76,
                        "SHIP_COG": 194.0,
                        "SHIP_Hdg": 46.09,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "[-81] IN THE WATER",
                    },
                ],
            },
            "TEST_FILE_KEY",
            [
                {
                    "file_key": "TEST_FILE_KEY",
                    "metadata": {
                        "Cruise": "TAN2206",
                        "Station": "9",
                        "Remarks": "Far field site 1",
                    },
                    # "tasks" field is removed
                    "ingressId": 1,
                    "observation": {
                        "Date": "2022-04-16",
                        "Time": "20:33:30",
                        "PC_Time": "2022-04-16T08:33:30",
                        "SHIP_Lon": -178.102472,
                        "SHIP_Lat": -24.0038202,
                        "SHIP_SOG": 0.45,
                        "SHIP_COG": 239.99,
                        "SHIP_Hdg": 25.03,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "DTIS photo: 1; volt: 25.7; magn. fs: 7954 ",
                    },
                    "created_at": "2022-04-16T12:00:00+00:00",
                },
                {
                    "file_key": "TEST_FILE_KEY",
                    "metadata": {
                        "Cruise": "TAN2206",
                        "Station": "9",
                        "Remarks": "Far field site 1",
                    },
                    # "tasks" field is removed
                    "ingressId": 1,
                    "observation": {
                        "Date": "2022-04-16",
                        "Time": "20:41:55",
                        "PC_Time": "2022-04-16T08:41:55",
                        "SHIP_Lon": -178.1025627,
                        "SHIP_Lat": -24.0037027,
                        "SHIP_SOG": 0.76,
                        "SHIP_COG": 194.0,
                        "SHIP_Hdg": 46.09,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "[-81] IN THE WATER",
                    },
                    "created_at": "2022-04-16T12:00:00+00:00",
                },
            ],
        ),
        # Test Case 2: With tasks and single observation
        (
            {
                "metadata": {
                    "Cruise": "TAN2207",
                    "Station": "10",
                    "Remarks": "Near field site 2",
                },
                "tasks": [
                    # {
                    #     "Task": "At the Surface",
                    #     "PC Date and Time": "2022-04-16T09:00:00+00:00",
                    #     "UTC Time": "09:00:00",
                    #     "UTC Date": "2022-04-16T06:00:00+00:00",
                    #     "SHIP Latitude": "-24:0.300",
                    #     "SHIP Longitude": "-178:6.200",
                    #     "SUB_1 Latitude": "0:00.0000",
                    #     "SUB_1 Longitude": "0:00.0000",
                    #     "Water Depth": "2700.0",
                    # },
                ],
                "detailed_data_table": [
                    {
                        "Date": "2022-04-16",
                        "Time": "09:10:00",
                        "PC_Time": "2022-04-16T09:10:00",
                        "SHIP_Lon": -178.103000,
                        "SHIP_Lat": -24.004000,
                        "SHIP_SOG": 1.00,
                        "SHIP_COG": 180.00,
                        "SHIP_Hdg": 30.00,
                        "Water_Depth": 2700.0,
                        "SUB1_Lon": -178.102500,
                        "SUB1_Lat": -24.003500,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:05:00",
                        "Observations/Comments": "Sample observation",
                        "Image-Video Path": "Sample photo and video path",
                    },
                ],
            },
            "TEST_FILE_KEY_2",
            [
                {
                    "file_key": "TEST_FILE_KEY_2",
                    "metadata": {
                        "Cruise": "TAN2207",
                        "Station": "10",
                        "Remarks": "Near field site 2",
                    },
                    "tasks": [
                        # {
                        #     "Task": "At the Surface",
                        #     "PC Date and Time": "2022-04-16T09:00:00+00:00",
                        #     "UTC Time": "09:00:00",
                        #     "UTC Date": "2022-04-16T06:00:00+00:00",
                        #     "SHIP Latitude": "-24:0.300",
                        #     "SHIP Longitude": "-178:6.200",
                        #     "SUB_1 Latitude": "0:00.0000",
                        #     "SUB_1 Longitude": "0:00.0000",
                        #     "Water Depth": "2700.0",
                        # },
                    ],
                    "ingressId": 1,
                    "observation": {
                        "Date": "2022-04-16",
                        "Time": "09:10:00",
                        "PC_Time": "2022-04-16T09:10:00",
                        "SHIP_Lon": -178.103000,
                        "SHIP_Lat": -24.004000,
                        "SHIP_SOG": 1.00,
                        "SHIP_COG": 180.00,
                        "SHIP_Hdg": 30.00,
                        "Water_Depth": 2700.0,
                        "SUB1_Lon": -178.102500,
                        "SUB1_Lat": -24.003500,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:05:00",
                        "Observations/Comments": "Sample observation",
                        "Image-Video Path": "Sample photo and video path",
                    },
                    "created_at": "2022-04-16T12:00:00+00:00",
                },
            ],
        ),
        # Add more test cases as needed
    ],
)
@patch("lambda_function_mongoDB_schema.get_current_ingress_id", return_value=1)
@patch("lambda_function_mongoDB_schema.ObjectId")
@patch("lambda_function_mongoDB_schema.datetime")
def test_prepare_documents(
    mock_datetime,
    mock_object_id,
    mock_get_current_ingress_id,
    parsed_data,
    file_key,
    expected_documents,
):
    """
    Test the prepare_documents function to ensure it correctly transforms parsed data into the desired MongoDB schema.
    Test the prepare_documents function to ensure it correctly transforms parsed data into the desired MongoDB schema
    without the 'tasks' section.

    Args:
        mock_object_id (Mock): Mocked ObjectId instance.
        mock_datetime (Mock): Mocked datetime instance.
        mock_get_current_ingress_id (Mock): Mocked get_current_ingress_id function.
        parsed_data (dict): The input parsed data.
        file_key (str): The S3 file key.
        expected_documents (List[Dict[str, Any]]): The expected list of documents.

    Expecting a List of Documents:

    The expected_documents parameter is now a list of dictionaries, each representing an individual MongoDB document corresponding to an observation.
    Mocking datetime.now:

    The created_at field is set to a fixed datetime (2022-04-16T12:00:00+00:00) to ensure consistency across test runs.
    Handling Multiple Observations:

    Each observation in the detailed_data_table results in a separate document in the expected_documents list.
    Incorporating Metadata and Tasks:

    Each document includes the shared metadata and tasks fields, ensuring that these are correctly propagated to each MongoDB document.
    """
    # Configure the mock for datetime to return a fixed datetime
    fixed_datetime = datetime(2022, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_datetime

    # Call the function under test
    actual_documents = prepare_documents(parsed_data, file_key, None)

    # Assert that the actual_documents match the expected_documents
    assert actual_documents == expected_documents


"""
Summary of new Tests for re-factored code:

test_parse_metadata: Tests the parse_metadata function.
test_detect_header_line: Tests the detect_header_line function.
test_parse_tasks: Tests the parse_tasks function.
test_parse_data_rows: Tests the parse_data_rows function.
test_parse_latest_format: Tests the parse_latest_format function, which combines all the smaller functions.
"""


@pytest.mark.parametrize(
    "lines, expected_metadata, expected_data_start_idx",
    [
        (
            [
                "Cruise : TAN2206",
                "Station : 9",
                "Remarks : Far field site 1",
                "--------------------------------",
                "#Date\tTime\tPC_Time\tSHIP_Lon",
            ],
            {"Cruise": "TAN2206", "Station": "9", "Remarks": "Far field site 1"},
            4,
        ),
        (
            [
                "Cruise : TAN0616",
                "Station : DTIS_4_#5",
                "Remarks : little nose west of slump site",
                "In the water : PC 04.11.2006 03:08:55 / UTC-time 14:08:56",
                "--------------------------------",
                "UTC time\tPC time\tLat\tLon\tSpeed\tCourse\tDepth\tHeading\tSub Lat\tSub Lon",
            ],
            {
                "Cruise": "TAN0616",
                "Station": "DTIS_4_#5",
                "Remarks": "little nose west of slump site",
                "In the water": "PC 04.11.2006 03:08:55 / UTC-time 14:08:56",
            },
            5,
        ),
    ],
)
def test_parse_metadata(lines, expected_metadata, expected_data_start_idx):
    metadata, data_start_idx = parse_metadata(lines)
    assert metadata == expected_metadata
    assert data_start_idx == expected_data_start_idx


@pytest.mark.parametrize(
    "lines, start_idx, expected_headers, expected_next_idx",
    [
        (
            ["--------------------------------", "#Date\tTime\tPC_Time\tSHIP_Lon"],
            1,
            ["Date", "Time", "PC_Time", "SHIP_Lon"],
            2,
        )
    ],
)
def test_detect_header_line(lines, start_idx, expected_headers, expected_next_idx):
    headers, next_idx = detect_header_line(lines, start_idx)
    assert headers == expected_headers
    assert next_idx == expected_next_idx


@pytest.mark.parametrize(
    "lines, start_idx, expected_tasks",
    [
        (
            [
                "Task\tPC Date and Time\tUTC Time\tUTC Date\tSHIP Latitude\tSHIP Longitude\tSUB_1 Latitude\tSUB_1 Longitude\tWater Depth",
                "In the Water     :\t	16/04/2022 08:41:57	\t20:41:57\t	16/04/2022 06:33:55	\t-24:0.222\t-178:6.154\t0:00.0000\t0:00.0000\t2607.8",
            ],
            0,
            [
                {
                    "Task": "In the Water",
                    "PC Date and Time": "2022-04-16T08:41:57",
                    "UTC Time": "20:41:57",
                    "UTC Date": "16/04/2022",
                    "SHIP Latitude": "-24:0.222",
                    "SHIP Longitude": "-178:6.154",
                    "SUB_1 Latitude": "0:00.0000",
                    "SUB_1 Longitude": "0:00.0000",
                    "Water Depth": "2607.8",
                }
            ],
        )
    ],
)
def test_parse_tasks(lines, start_idx, expected_tasks):
    tasks = parse_tasks(lines, start_idx)
    assert tasks == expected_tasks


@pytest.mark.parametrize(
    "lines, start_idx, headers, expected_data_rows",
    [
        (
            [
                "#Date\tTime\tPC_Time\tSHIP_Lon\tSHIP_Lat\tSHIP_SOG\tSHIP_COG\tSHIP_Hdg\tWater_Depth\tSUB1_Lon\tSUB1_Lat\tSUB1_Depth\tSUB1_Altitude\tElapsed video Time\tObservations/Comments\tImage-Video Path",
                "04/16/2022\t20:33:30\t16/04/2022 08:33:30\t-178.102472\t-24.0038202\t0.45\t239.99\t25.03\t2607.8\t0\t0\t0\t0\t00:00:00\t\tDTIS photo: 1; volt: 25.7; magn. fs: 7954",
            ],
            1,
            [
                "Date",
                "Time",
                "PC_Time",
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
                "Elapsed video Time",
                "Observations/Comments",
                "Image-Video Path",
            ],
            [
                {
                    "Date": "2022-04-16",
                    "Time": "20:33:30",
                    "PC_Time": "2022-04-16T08:33:30",
                    "SHIP_Lon": -178.102472,
                    "SHIP_Lat": -24.0038202,
                    "SHIP_SOG": 0.45,
                    "SHIP_COG": 239.99,
                    "SHIP_Hdg": 25.03,
                    "Water_Depth": 2607.8,
                    "SUB1_Lon": 0.0,
                    "SUB1_Lat": 0.0,
                    "SUB1_Depth": 0.0,
                    "SUB1_Altitude": 0.0,
                    "Elapsed video Time": "00:00:00",
                    "Observations/Comments": "",
                    "Image-Video Path": "DTIS photo: 1; volt: 25.7; magn. fs: 7954",
                }
            ],
        )
    ],
)
def test_parse_data_rows(lines, start_idx, headers, expected_data_rows):
    data_rows = parse_data_rows(lines, start_idx, headers)
    assert data_rows == expected_data_rows


@pytest.mark.parametrize(
    "lines, expected_output",
    [
        (
            [
                "Cruise     :\t	TAN2206",
                "Station :\t 9",
                "Remarks :\t Far field site 1",
                "Sadie calling, Rob OFOP, Neill DTIS",
                "Very flat seafloor at a depth of 2507 m. Very consistant substrate of muddy sediment with gravels, pebbles, cobbles and the occasional boulder. Fauna was sparse with a few shrimps, holothurians, hexactinellid sponges and one Umbellula se pen.",
                "Low numbers of fish and eels but one rattail was observed.",
                "OFOP entries were sometimes made for for long straight objects as either sea pens/hexactinellids which were difficult to determine. But confirmed ID's were made of both groups.",
                "    ",
                "Task             :\t PC Date and Time\t UTC Time\t UTC Date\t SHIP Latitude\t SHIP Longitude\t SUB_1 Latitude\t SUB_1 Longitude\t Water Depth",
                "In the Water     :\t 16/04/2022 08:41:57\t 20:41:57\t 16/04/2022 06:33:55\t -24:0.222\t -178:6.154\t 0:00.0000\t 0:00.0000\t 2607.8",
                "At the Bottom    :\t 16/04/2022 09:26:48\t 21:26:48\t 16/04/2022 06:33:55\t -24:0.155\t -178:6.113\t -24:00.2055\t -178:06.1496\t 2607.1",
                "Off the Bottom   :\t 16/04/2022 10:28:55\t 22:28:55\t 16/04/2022 06:33:55\t -23:59.713\t -178:5.635\t -23:59.8844\t -178:05.7859\t 2606.3",
                "On Deck          :\t 16/04/2022 11:09:01\t 23:09:01\t 16/04/2022 06:33:55\t -23:59.723\t -178:5.649\t -23:59.7294\t -178:05.6544\t 2606.3",
                "Gear deployed    :\t  :  :  ",
                "--------------------------------",
                "#Date\tTime\tPC_Time\tSHIP_Lon\tSHIP_Lat\tSHIP_SOG\tSHIP_COG\tSHIP_Hdg\tWater_Depth\tSUB1_Lon\tSUB1_Lat\tSUB1_Depth\tSUB1_Altitude\tElapsed video Time\tObservations/Comments\tImage-Video Path",
                "04/16/2022\t20:33:30\t16/04/2022 08:33:30\t-178.102472\t-24.0038202\t0.45\t239.99\t25.03\t2607.8\t0\t0\t0\t0\t00:00:00\t\tDTIS photo: 1; volt: 25.7; magn. fs: 7954",
            ],
            {
                "metadata": {
                    "Cruise": "TAN2206",
                    "Station": "9",
                    "Remarks": "Far field site 1",
                },
                "tasks": {
                    "Task": "In the Water",
                    "PC Date and Time": "2022-04-16T08:41:57",
                    "UTC Time": "20:41:57",
                    "UTC Date": "16/04/2022",
                    "SHIP Latitude": "-24:0.222",
                    "SHIP Longitude": "-178:6.154",
                    "SUB_1 Latitude": "0:00.0000",
                    "SUB_1 Longitude": "0:00.0000",
                    "Water Depth": "2607.8",
                },
                "detailed_data_table": [
                    {
                        "Date": "2022-04-16",
                        "Time": "20:33:30",
                        "PC_Time": "2022-04-16T08:33:30",
                        "SHIP_Lon": -178.102472,
                        "SHIP_Lat": -24.0038202,
                        "SHIP_SOG": 0.45,
                        "SHIP_COG": 239.99,
                        "SHIP_Hdg": 25.03,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "DTIS photo: 1; volt: 25.7; magn. fs: 7954",
                    }
                ],
            },
        ),
        (
            [
                "Cruise     :\t	TAN2206",
                "Station :\t 9",
                "Remarks :\t Far field site 1",
                "--------------------------------",
                "#Date\tTime\tPC_Time\tSHIP_Lon",
                "04/16/2022\t20:33:30\t16/04/2022 08:33:30\t-178.102472\t-24.0038202\t0.45\t239.99\t25.03\t2607.8\t0\t0\t0\t0\t00:00:00\t\tDTIS photo: 1; volt: 25.7; magn. fs: 7954",
            ],
            {
                "metadata": {
                    "Cruise": "TAN2206",
                    "Station": "9",
                    "Remarks": "Far field site 1",
                },
                "tasks": [],
                "detailed_data_table": [
                    {
                        "Date": "2022-04-16",
                        "Time": "20:33:30",
                        "PC_Time": "2022-04-16T08:33:30",
                        "SHIP_Lon": -178.102472,
                        "SHIP_Lat": -24.0038202,
                        "SHIP_SOG": 0.45,
                        "SHIP_COG": 239.99,
                        "SHIP_Hdg": 25.03,
                        "Water_Depth": 2607.8,
                        "SUB1_Lon": 0.0,
                        "SUB1_Lat": 0.0,
                        "SUB1_Depth": 0.0,
                        "SUB1_Altitude": 0.0,
                        "Elapsed video Time": "00:00:00",
                        "Observations/Comments": "",
                        "Image-Video Path": "DTIS photo: 1; volt: 25.7; magn. fs: 7954",
                    }
                ],
            },
        ),
    ],
    ids=[
        "test_case_with_tasks",
        "test_case_without_tasks",
    ],
)
def test_parse_latest_format(lines, expected_output):
    """
    Test the parse_latest_format function to ensure it correctly parses input lines into the expected format.
    """
    output = parse_latest_format(lines)

    # Assert that the output is a list
    assert isinstance(output, list), "Expected output to be a list"

    # Assert that the list contains exactly one dictionary
    assert (
        len(output) == 1
    ), f"Expected output list to contain 1 item, got {len(output)}"

    # Access the first dictionary in the list
    parsed_output = output[0]

    # Perform assertions on the parsed_output

    assert (
        parsed_output["detailed_data_table"] == expected_output["detailed_data_table"]
    ), "Detailed data table does not match"
    assert (
        parsed_output["metadata"] == expected_output["metadata"]
    ), "Metadata does not match"
    assert parsed_output["tasks"] == expected_output["tasks"], "Tasks do not match"
    # Add more assertions as needed for other fields
