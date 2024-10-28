# 
#        file: generic_test.py
# description: Some generic example tests.
#


import logging
import pytest



logger = logging.getLogger(__name__)


def test_generic_1():
    assert True == True

def test_generic_2():
    assert True == False

def test_generic_3():
    sum = 1 + 2
    assert sum == 3
