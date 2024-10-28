# NIWA Ocean Floor DTIS Data Platform

To manage data operations (data upload, data processing) for the ocean floor DTIS data platform.

## Git repository structure

- [infrastructure](infrastructure/) - contains Terraform code that manages AWS resources (e.g. Amazon S3 buckets)
- [upload](upload/) - contains files needed to upload data to AWS
- [processing](processing/) - contains Lambda function (deployed as Python script in AWS) for the conversion of uploaded (text) files into MongoDB documents

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

### Running the upload script yourself

This comes handy when you want to familiarise yourself with the script, or experiment with new code added to the script, with getting fast feedback, and without impacting the production environment (production data or production infrastructure resources).

Please run the following:
```
NIWA_DRY_RUN=true NIWA_ENVIRONMENT=testing NIWA_IMAGES_DIR=./upload/test/test-data/images ./upload/data_upload.sh
```

Read the contents of the .txt log files.
