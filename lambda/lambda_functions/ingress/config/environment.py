#
#        file: environment.py
# description: Environment Test Configuration class and functions.
#
#

import logging

logger = logging.getLogger(__name__)

# Local Constants
DB_COLLECTION_NAME = "example_collection"


# Environment class provides integration test configuration settings.
class Environment:
    _collection_name = None

    def __init__(self, collection_name=DB_COLLECTION_NAME):
        self._collection_name = collection_name


    @property
    def collection_name(self):
        return self._collection_name
