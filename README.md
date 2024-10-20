# NIWA data seafloor

To manage data operations (data upload, data processing) for the seafloor data.

## Git repository structure

* [infrastructure](infrastructure/) - contains Terraform code that manages AWS resources (e.g. Amazon S3 buckets)
* [upload](upload/) - contains files needed to upload data to AWS

## Local testing

### Linting with ShellCheck - for shell scripts

[ShellCheck](https://github.com/koalaman/shellcheck) is a CLI tool which provides static analysis for shell scripts.

Run it using Docker:
```
./tasks shellcheck
```


Alternative ways to run it:
* running it without Docker
```
sudo apt install shellcheck
shellcheck ./upload/data_upload.sh
```
* running the Docker command directly - copy the command from the `tasks` script
```
docker run -ti --rm -v $PWD:/tmp/niwa --entrypoint=/bin/sh koalaman/shellcheck-alpine:v0.10.0 -c "shellcheck /tmp/niwa/upload/data_upload.sh"
```
