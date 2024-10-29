# NIWA Ocean Floor DTIS Data Platform

To manage data operations (data upload, data processing) for the ocean floor DTIS data platform.

## Git repository structure

- [infrastructure](infrastructure/) - contains Terraform code that manages AWS resources (e.g. Amazon S3 buckets)
- [upload](upload/) - contains files needed to upload data to AWS
- [processing](processing/) - contains Lambda function (deployed as Python script in AWS) for the conversion of uploaded (text) files into MongoDB documents


## Running the upload script

Example command:
```
NIWA_DRY_RUN=true NIWA_ENVIRONMENT=testing \
	NIWA_CRUISE_ID=TAN0616 \
	NIWA_IMAGES_DIR=./upload/test/test-data/images \
	NIWA_VIDEOS_DIR=./upload/test/test-data/2023 \
	NIWA_OFOP_DIR=./upload/test/test-data/text/TAN2203 \
	./upload/data_upload.sh
```

The above command will run locally, using the test files, and it will not connect to Amazon S3. Therefore, **it is always safe to run the above command** (e.g. when you want to experiment, familiarise yourself with the script, or edit the script). The idea is that this should get you fast feedback, and it will not impact the production environment (the real data or production infrastructure resources).

Please set the following variables yourself:
* `NIWA_DRY_RUN`, set it to false, if you want the script to upload the files to S3. Otherwise, the script will just run local verificaction checks.
* `NIWA_ENVIRONMENT` - TODO
* TODO

To troubleshoot - please read the output printed in your terminal, and also please read the contents of the error.txt, success.txt, and sync_logs.txt log files. The log files contain the same information as the terminal output (but if you are expecting an error message, it might be faster to go look for it in error.txt file, rather than trying to find it in the output).

## Local testing

### Linting with ShellCheck - for shell scripts

[ShellCheck](https://github.com/koalaman/shellcheck) is a CLI tool which provides static analysis for shell scripts.

Run it using Docker:

```
./tasks shellcheck
```

Alternative ways to run it:

- running it without Docker

```
sudo apt install shellcheck
shellcheck ./upload/data_upload.sh
```

- running the Docker command directly - copy the command from the `tasks` script

### Unit testing with bats-core

[Bats-core](https://github.com/bats-core/bats-core) is a CLI tool, a unit tests framework to verify that the UNIX programs you write behave as expected.

Run it using Docker:

```
./tasks bats
```

Alternative ways to run it:

- running it without Docker. First install Bats using [these instructions](https://bats-core.readthedocs.io/en/stable/installation.html), then run this:

```
bats ./upload/test/bats/*
```

- running the Docker command directly - copy the command from the `tasks` script
