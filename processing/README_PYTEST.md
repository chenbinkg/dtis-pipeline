# Linux Embedded Device Integration Test Suite

## Introduction

TODO: Aim and scope of what the goal and use-cases are for tests.


## Setting up Python Environment on Linux (Integration Test Suite Prerequisites)

From here (https://www.digitalocean.com/community/tutorials/how-to-install-python-3-and-set-up-a-programming-environment-on-an-ubuntu-20-04-server)


First install the necessary system dependencies on the Ubuntu 20.04 environment.

    sudo apt update && sudo apt -y upgrade
    ...
    sudo apt install -y python3-pip
    ...
    sudo apt install -y build-essential libssl-dev libffi-dev python3-dev
    ...
    sudo apt install -y python3-venv
    ...

Alternatively install the necessary system dependencies on Arch Linux environment.

    sudo pacman -Syu
    ...
    sudo pacman -S base-devel openssl libffi
    ...
    sudo pacman -S python python-pip


## Create a Python virtual environment and install the neccessary dependencies

We then need to setup a python virtual environment (it is good practise to keep our python environments organised by project) and install `pytest` and its dependencies - these are all listed in the `requirements.txt` file.

    python3 -m venv venv
    . venv/bin/activate

    pip install -r requirements.txt


## Updating the virtual environment and neccessary dependencies

To add new packages to the activated environment install the new package `<package_name>` via `pip`.

    pip install <package_name>

And update the `requirements.txt` file using `pip freeze`.

    pip freeze > requirements.txt



## To Run Tests (Assumes Integration Test Suite Prerequisites are installed and virtual environment is activated)

The minimum required run-time argument is the `--swpack-version` followed by a
valid software-pack version.

E.g.

    pytest


Some other usage examples follow.

    pytest --collection some_collection_name


You can execute `pytest --help` to see many of the pytest options. Under the help section `custom options` you will see the device specific options.

E.g.

    pytest --help

    ...
    
    custom options:
      --ip=IP               Device IPv4 Address.
      --signed              Device Signed Mode.
      --swpack-version=SWPACK_VERSION
                            Device swpack Version Number (x.y.z or LABEL.z).
      --build={ci,nightly,pre,local}
                            Specify the build-type (used to infer the swpack path).
                            ci:      swpack is located in file-share ci directory (default).
                            nightly: swpack is located in file-share nightly-ci directory.
                            pre:     swpack is located in file-share pre-ga-release directory.
                            local:   swpack is located at the local build path "$HOME/build_path".
      --mode={normal,dev,test-dev}
                            Specify the test mode.
                            normal:   no tests are skipped (deafult).
                            dev:      software load and rollback tests are skipped.
                            test-dev: software init load, load, and, rollback tests are skipped.
    
    ...



# Some useful pytest runtime options.

Note these entries have been taken from the pytest documentation. This documentation serves as an excellent reference, but, it is very detailed.

https://docs.pytest.org/en/6.2.x/contents.html


## Run tests by keyword expressions

    pytest -k "MyClass and not method"

This will run tests which contain names that match the given string expression (case-insensitive), which can include Python operators that use filenames, class names and function names as variables. The example above will run TestMyClass.test_something but not TestMyClass.test_method_simple.


## Run tests with Live Logging

Live logging is disabled by default; to enable it, set log_cli = 1 in the pytest.ini file.

Alternatively we can override ini options from command line via the -o/--override option. For example simply call:

    pytest -o log_cli=true ...


See https://docs.pytest.org/en/6.2.x/logging.html and https://stackoverflow.com/questions/4673373/logging-within-pytest-tests for more details.


Note. For quick-and-dirty print statment debugging pytest will capture stdout and print what it has captured when the offending test fails.

Alternatively provide the '-s' flag when invoking pytest to see print statements in realtime.

See https://stackoverflow.com/questions/24617397/how-to-print-to-console-in-pytest for more details.


## Creating JUnitXML format files (for simple CI-system Integration)

To create result files which can be read by Jenkins or other Continuous integration servers, use this invocation:

    pytest --junitxml=path

to create an XML file at path.


## Detailed summary report

The -r flag can be used to display a “short test summary info” at the end of the test session, making it easy in large test suites to get a clear picture of all failures, skips, xfails, etc.

It defaults to fE to list failures and errors.

The -r options accepts a number of characters after it. E.g. -ra means “all except passes”.

Here is the full list of available characters that can be used:

    f - failed
    E - error
    s - skipped
    x - xfailed
    X - xpassed
    p - passed
    P - passed with output

Special characters for (de)selection of groups:

    a - all except pP
    A - all
    N - none, this can be used to display nothing (since fE is the default)

More than one character can be used.


## The pytest conftest.py File

The pytest conftest.py file defines pytest test-run properties and common fixtures.

See the following link for a good overview of the conftest.py file in the context of pytest.

https://stackoverflow.com/questions/34466027/in-pytest-what-is-the-use-of-conftest-py-files


The conftest.py file also enables some not-so-well documented pytest magic. 
 
Test root path: This is a bit of a hidden feature. By defining conftest.py in
your root path, you will have pytest recognizing your application modules
without specifying PYTHONPATH.
 
See the following link for more details.

https://stackoverflow.com/questions/34466027/in-pytest-what-is-the-use-of-conftest-py-files


## pytest Fixtures

Fixtures conveniently encapsulate setup and tear-down of resources required for a test to run. 

Think of fixtures as test dependencies and prerequisites. 

See the following links for more details on fixtures.

https://docs.pytest.org/en/latest/explanation/fixtures.html#about-fixtures
https://docs.pytest.org/en/latest/how-to/fixtures.html#how-to-fixtures
https://docs.pytest.org/en/latest/reference/fixtures.html#reference-fixtures


## A note about pytest fixture scopes

Fixtures are created when first requested by a test, and are destroyed based on their scope:

    function: the default scope, the fixture is destroyed at the end of the test.
    class: the fixture is destroyed during teardown of the last test in the class.
    module: the fixture is destroyed during teardown of the last test in the module.
    package: the fixture is destroyed during teardown of the last test in the package.
    session: the fixture is destroyed at the end of the test session.


## Conventions for Python test discovery

pytest implements the following standard test discovery:

* If no arguments are specified then collection starts from testpaths (if configured) or the current directory. Alternatively, command line arguments can be used in any combination of directories, file names or node ids.

* Recurse into directories, unless they match norecursedirs.

* In those directories, search for test\_\*.py or \*\_test.py files, imported by their test package name.

* From those files, collect test items:

* test prefixed test functions or methods outside of class.

* test prefixed test functions or methods inside Test prefixed test classes (without an \_\_init\_\_ method).