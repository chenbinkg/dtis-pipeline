import boto3
import os
import logging
from typing import Tuple, Optional


class AWSCredentialProvider:
    def __init__(self, profile_name: Optional[str] = None):
        """
        Initialize the credential provider.
        :param profile_name: Optional AWS CLI profile name.
        """
        self.aws_access_key_id = None
        self.aws_secret_access_key = None
        self.aws_session_token = None
        self.profile_name = profile_name

    def get_credentials_from_interaction(self) -> Tuple[str, str, Optional[str]]:
        """
        Interactively retrieves AWS credentials from the user.
        """
        print("Have You Set Up AWS Credentials In Your Environment Variables?")
        print("Or Set Up An AWS Profile With AWS Credentials?")
        auth_option = None
        while auth_option not in ["1", "2", "3"]:
            auth_option = input(
                "Please Enter Your Authentication Options (1, 2, or 3):\n"
                + "1 - by Environment Variables\n"
                + "2 - by AWS profile\n"
                + "3 - by Inputting AWS Credentials\n"
                + "Enter Your Option: "
            )

        if auth_option == "1":
            # attempt to get environment variables for aws access key and secret
            self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
            self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
            self.aws_session_token = os.getenv("AWS_SESSION_TOKEN")
            if (
                not self.aws_access_key_id
                or not self.aws_secret_access_key
                or not self.aws_session_token
            ):
                logging.error(
                    "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY or AWS_SESSION_TOKEN was not set. Please set a correct value"
                )

        if auth_option == "2":
            # attempt to get aws credentials from aws profile
            self.profile_name = input("Enter your AWS profile name: ")
            if not self.profile_name:
                logging.error("AWS profile was not set. Please set a correct value")

            try:
                session = boto3.Session(profile_name=self.profile_name)
                credentials = session.get_credentials()
                self.aws_access_key_id = credentials.access_key
                self.aws_secret_access_key = credentials.secret_key
                self.aws_session_token = credentials.token
                os.environ["AWS_ACCESS_KEY_ID"] = self.aws_access_key_id
                os.environ["AWS_SECRET_ACCESS_KEY"] = self.aws_secret_access_key
                if self.aws_session_token is not None:
                    os.environ["AWS_SESSION_TOKEN"] = self.aws_session_token
            except Exception as e:
                logging.error(
                    f"Failed to get AWS credentials from profile {self.profile_name}",
                )

        if auth_option == "3":
            # prompt for aws access key
            self.aws_access_key_id = input("Enter your AWS Access Key ID: ")
            # attempt to get environment variables for aws access key and secret
            if not self.aws_access_key_id:
                logging.error(
                    "AWS Access Key ID was not set. Please set a correct value"
                )
                # sys.exit(1)
            # prompt for aws secret access key
            self.aws_secret_access_key = input("Enter your AWS Secret Access Key: ")
            if not self.aws_secret_access_key:
                logging.error(
                    "AWS Secret Access Key was not set. Please set a correct value"
                )

            # prompt for aws session token
            self.aws_session_token = input("Enter your AWS Session Token: ")
            # if not aws_session_token:
            #     print("AWS Session Token was not set. Please set a correct value")
            #     sys.exit(1)
            os.environ["AWS_ACCESS_KEY_ID"] = self.aws_access_key_id
            os.environ["AWS_SECRET_ACCESS_KEY"] = self.aws_secret_access_key
            os.environ["AWS_SESSION_TOKEN"] = self.aws_session_token

        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError("Access Key ID and Secret Access Key are required.")

        logging.info("AWS credentials successfully retrieved from user interaction.")
        return (
            self.aws_access_key_id,
            self.aws_secret_access_key,
            self.aws_session_token,
        )