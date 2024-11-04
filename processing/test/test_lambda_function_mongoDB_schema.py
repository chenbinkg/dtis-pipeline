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
*test_get_posi_file_content_success: Tests the path where the posi file exists and can be retrieved successfully.
*test_get_posi_file_content_no_file: Tests the error handling when the posi file doesn't exist.
*test_get_posi_file_content_file_name_transformation: Specifically tests the file name transformation logic from "_prot.txt" to "_posi.txt".
*test_get_posi_file_content_various_paths: Uses parametrize to test multiple input scenarios for different file paths and names.


"""

from datetime import datetime, timedelta
from unittest.mock import Mock

# import boto3
import pytest
from botocore.exceptions import ClientError
from lambda_function_mongoDB_schema import (get_posi_file_content,
                                            parse_data_line)


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


def test_get_posi_file_content_success():
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
        Bucket="test-bucket",  # Changed from "XXXXXXXXXXX" to match the input parameter
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
    "line,expected_results",
    [
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
                    "observation3": None,
                    "observationRef": "<a href='https://www.marinespecies.org/rest/AphiaRecordsByMatchNames?scientificnames%5B%5D=general observation&marine_only=true'>Try a WORMS search for general observation</a>",
                },
            },
        ),
        ("12:34:56\tonly_three_fields\tfield3", None),
    ],
)
def test_parse_data_line(line, expected_results, source_key):
    result, video_start, video_events = parse_data_line(line, source_key, None, [])

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
    result, video_start, video_events = parse_data_line(
        new_format_line,
        source_key,
        None,
        [],
        file_format="new",
        header=new_format_header,
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
            "observation3": None,
            "observationRef": f"<a href='https://www.marinespecies.org/rest/AphiaRecordsByMatchNames?scientificnames%5B%5D=OBSCURED&marine_only=true'>Try a WORMS search for OBSCURED</a>",
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
    return [
        {"time_str": "23:59:59", "expected": {"hour": 23, "minute": 59, "second": 59}},
        {"time_str": "00:00:00", "expected": {"hour": 0, "minute": 0, "second": 0}},
    ]


@pytest.mark.parametrize("test_case", time_test_cases())
def test_parse_data_line_time_parsing(test_case, basic_line):
    line = test_case["time_str"] + basic_line[8:]  # Replace time in basic line

    result, _, _ = parse_data_line(line, "test_key", None, [])

    assert isinstance(result["time"], datetime)
    assert result["time"].hour == test_case["expected"]["hour"]
    assert result["time"].minute == test_case["expected"]["minute"]
    assert result["time"].second == test_case["expected"]["second"]


@pytest.mark.parametrize(
    "sequence_times,expected_duration",
    [
        (["12:34:00", "12:34:30", "12:35:00"], timedelta(minutes=1)),
        (["12:34:00", "12:34:15", "12:34:30"], timedelta(seconds=30)),
    ],
)
def test_parse_data_line_video_sequences(sequence_times, expected_duration):
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
def test_parse_data_line_media_types(
    basic_line, source_key, observation, expected_media_type, expected_media_path
):
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
    reason="OLD (this can probably be removed, as it has been superseded)/ Work in progress."
)
@pytest.mark.parametrize(
    "observation,expected_events_count",
    [
        ("video started", 1),
        ("start video", 1),
        ("Video Started at surface", 1),
        ("general observation", 0),
    ],
)
def test_parse_data_line_video_start(
    basic_line, source_key, observation, expected_events_count
):
    # Arrange
    line = basic_line.rsplit("\t", 1)[0] + "\t" + observation
    video_events = []

    # Act
    result, video_start, video_events = parse_data_line(
        line, source_key, None, video_events
    )

    # Assert
    assert len(video_events) == expected_events_count
    if expected_events_count > 0:
        assert video_events[0]["event"] == "start"
        assert video_start is not None
        assert result["mediatype"] == "video"
        assert "/videos/" in result["media"]
        assert result["media"].endswith(".m2t")


@pytest.mark.skip(
    reason="OLD (this can probably be removed, as it has been superseded)/ Work in progress."
)
def test_parse_data_line_video_stop():
    # Arrange
    line = "12:35:00\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tvideo stopped"
    video_start = datetime.strptime("12:34:00", "%H:%M:%S")
    video_events = []

    # Act
    result, video_start_after, video_events = parse_data_line(
        line, "test_key", video_start, video_events
    )

    # Assert
    assert len(video_events) == 1
    assert video_events[0]["event"] == "stop"
    assert "duration" in video_events[0]
    assert video_start_after is None
    assert result["mediatype"] == "video"


@pytest.mark.skip(
    reason="OLD (this can probably be removed, as it has been superseded)/ Work in progress."
)
def test_parse_data_line_video_duration():
    # Arrange
    video_start = datetime.strptime("12:34:00", "%H:%M:%S")
    line = "12:34:30\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tgeneral observation"

    # Act
    result, _, _ = parse_data_line(line, "test_key", video_start, [])

    # Assert
    assert result["mediaoffset"] == timedelta(seconds=30)
    assert result["mediatype"] == "video"


@pytest.mark.skip(
    reason="OLD (this can probably be removed, as it has been superseded)/ Work in progress."
)
def test_parse_data_line_time_parsing():
    # Arrange
    line = "23:59:59\tignored\t-41.2345\t174.9876\t2.5\t180.0\t100.5\t45.0\t0\t0\t-41.2345\t174.9876\tignored\tgeneral observation"

    # Act
    result, _, _ = parse_data_line(line, "test_key", None, [])

    # Assert
    assert isinstance(result["time"], datetime)
    assert result["time"].hour == 23
    assert result["time"].minute == 59
    assert result["time"].second == 59
