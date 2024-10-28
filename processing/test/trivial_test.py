# 
#        file: trivial_test.py
# description: Some trivial example tests.
#


import logging
import pytest
from config.environment import Environment


logger = logging.getLogger(__name__)


def test_trivial_1(fixture_environment):
    assert fixture_environment.collection_name == "pytest_runtime_default"

def test_trivial_2(fixture_environment):
    default_environment = Environment()
    assert fixture_environment.collection_name == default_environment.collection_name

def test_trivial_3(fixture_environment):
    assert type(fixture_environment) == Environment
    