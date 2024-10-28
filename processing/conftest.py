#
#        file: conftest.py
# description: All our common pytest fixtures should live in this file.
#
# TODO:
# * Abstract away admin / root CLI command execution.
#
#

import logging
import pytest

from config.environment import Environment


# TODO: Extend Logging options
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Add custom runtime arguments that we then retrieve and use in fixture_environment.
def pytest_addoption(parser):
    parser.addoption("--collection", default="pytest_runtime_default", help="MongoDB Collection Name.")

@pytest.fixture(scope="session")
def fixture_environment(
    request,
    record_testsuite_property) -> pytest.fixture:

    # Retrieve runtime arguments and use them to instantiate an Environment object.
    collection_name = request.config.getoption("--collection")

    logger.info(f"runtime-argument --collection: {collection_name}")

    # Add global Environment values as testsuite properties in JUnitXML report.
    record_testsuite_property("Environment.collection_name", collection_name)

    logger.info(f"Environment.collection: {collection_name}")

    environment = Environment(collection_name = collection_name)

    yield environment
