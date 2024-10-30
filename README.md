# NIWA Ocean Floor DTIS Data Platform

To manage data operations (data upload, data processing) for the ocean floor DTIS data platform.

## Git repository structure

- [infrastructure](infrastructure/) - contains Terraform code that manages AWS resources (e.g. Amazon S3 buckets)
- [upload](upload/) - contains files needed to upload data to AWS
- [processing](processing/) - contains Lambda function (deployed as Python script in AWS) for the conversion of uploaded (text) files into MongoDB documents


## Running the data upload script

### For the Scientists

1. **Run the Bash script, with dryrun**. Start with running this Bash command:
```
NIWA_DRY_RUN=true NIWA_ENVIRONMENT=testing \
	NIWA_CRUISE_ID=<TODO_set_me_please> \
	NIWA_IMAGES_DIR=<TODO_set_me_please> \
	NIWA_VIDEOS_DIR=<TODO_set_me_please> \
	NIWA_OFOP_DIR=<TODO_set_me_please> \
	./upload/data_upload.sh
```

	Please set the following variables:
	* `NIWA_CRUISE_ID` - this is the ID of the ship voyage, should be e.g. TAN0616
	* `NIWA_ENVIRONMENT` - set it to either `testing` or `production`. This decides which S3 bucket to use. Since the script works, but it's in its initial version, let's use the testing S3 bucket first.
	* `NIWA_IMAGES_DIR`, `NIWA_VIDEOS_DIR`, `NIWA_OFOP_DIR` - should be set to paths to local directories containing respectivelly: images, videos, text files


The above command will run locally, using your files, and it will **not** interact with AWS at all, thanks to setting `NIWA_DRY_RUN=true`. Therefore, **it is always safe to run the above command**.

2. **Inspect the output**. Please go through the output of the above command, printed in your terminal. The output from the script is also written to the local log files. The log files contain the same information as the terminal output but split across:
	* `error.txt` - contains only warnings and errors
	* `success.txt` - contains successful messages
	* `sync_logs.txt` - contains AWS S3 upload logs

If you are looking for an error message, it might be faster to go look for it in the `error.txt` file, rather than trying to find it in the terminal output.

The Bash script command will show you errors, such as:
* a file name did not meet a naming convention
* a file extension was not a real video/image/text file
* there was a problem to deduct the station ID basing on the file path

3. **Edit your local files**. You may need to edit your local files, and run the Bash script again, until there are no errors.

4. **Run the Bash script again, this time with no dryrun**. If you are happy with the output of the data upload script, please run the above command again, but please do set now `NIWA_DRY_RUN=false`, e.g.
```
NIWA_DRY_RUN=false NIWA_ENVIRONMENT=testing \
	NIWA_CRUISE_ID=<TODO_set_me_please> \
	NIWA_IMAGES_DIR=<TODO_set_me_please> \
	NIWA_VIDEOS_DIR=<TODO_set_me_please> \
	NIWA_OFOP_DIR=<TODO_set_me_please> \
	./upload/data_upload.sh
```


### For the Script Developers

Example command:
```
NIWA_DRY_RUN=true NIWA_ENVIRONMENT=testing \
	NIWA_CRUISE_ID=TAN1802 \
	NIWA_IMAGES_DIR=./upload/test/test-data/images \
	NIWA_VIDEOS_DIR=./upload/test/test-data/2023 \
	NIWA_OFOP_DIR=./upload/test/test-data/text/TAN2203 \
	./upload/data_upload.sh
```

The above command will run locally, using the dummy test files, and it will not interact with AWS at all. Therefore, **it is always safe to run the above command**. Use it e.g. when you want to experiment, familiarise yourself with the script, or edit the script. The idea is that this should get you fast feedback, and it will not impact the production environment (the real data or production infrastructure resources).

Run the tests below to confirm the script works.


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
