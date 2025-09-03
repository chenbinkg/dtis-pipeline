import logging
import boto3
from botocore.config import Config
from typing import Optional, Callable, Any

class AWSBucketManager:
    def __init__(
        self,
        environment: str,
        aws_region: str,
        s3_config: Optional[Config] = None,
        credential_provider: Optional[Callable] = None,
        bucket_name: Optional[str] = None,
        lambda_function_name: Optional[str] = None,
    ):
        self.environment = environment
        self.aws_region = aws_region
        self.s3_config = s3_config or Config()
        self.credential_provider = (
            credential_provider or self.default_credential_provider
        )
        self.session = None
        self.s3_client = None
        self.sts_client = None
        self.lambda_client = None
        self.account_id = None
        self.bucket_name = bucket_name
        self.lambda_function_name = lambda_function_name

    def default_credential_provider(self):
        # Placeholder for default credential logic
        raise NotImplementedError(
            "Provide a credential provider or override this method."
        )

    def initialize_clients(self):
        aws_access_key_id, aws_secret_access_key, aws_session_token = (
            self.credential_provider()
        )

        self.session = boto3.Session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            region_name=self.aws_region,
        )

        self.sts_client = self.session.client("sts")
        self.s3_client = self.session.client("s3", config=self.s3_config)
        self.lambda_client = self.session.client("lambda")

        identity = self.sts_client.get_caller_identity()
        self.account_id = identity.get("Account")
        logging.info(f"Authenticated IAM user: {identity}")

        self.bucket_name = self.bucket_name.replace("AWSACCOUNT", self.account_id) if self.bucket_name else None
        logging.info(f"Using S3 bucket: {self.bucket_name}")
        logging.info(f"Using Lambda function: {self.lambda_function_name}")
        
    def verify_bucket(self):
        if not self.s3_client or not self.bucket_name:
            raise RuntimeError("S3 client or bucket name not initialized.")
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logging.info(f"S3 bucket '{self.bucket_name}' exists and is accessible.")
        except self.s3_client.exceptions.NoSuchBucket:
            logging.error(f"S3 bucket '{self.bucket_name}' does not exist.")
            raise
        except Exception as e:
            logging.error(f"Error verifying S3 bucket: {e}")
            raise

    def setup(self):
        self.initialize_clients()
        self.verify_bucket()
        return {
            "bucket_name": self.bucket_name,
            "lambda_function_name": self.lambda_function_name,
            "account_id": self.account_id,
            "s3_client": self.s3_client
        }
