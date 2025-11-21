import os
from typing import Optional
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()


class S3Client:
    """
    This class is our little S3 toolbox.
    Instead of calling boto3 all over the project, we just use this one class.
    """

    def __init__(self, region: Optional[str] = None, bucket_name: Optional[str] = None):
        # Pull settings from the environment so we don’t hard-code secrets
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.bucket_name = bucket_name or os.getenv("AWS_S3_BUCKET_NAME")

        if not self.bucket_name:
            # If this blows up, it usually means we forgot:
            # export AWS_S3_BUCKET_NAME="your-bucket-name"
            raise ValueError("AWS_S3_BUCKET_NAME environment variable not set.")

        # Real boto3 S3 client that actually talks to AWS
        self._s3 = boto3.client(
            "s3",
            region_name=self.region,
            config=Config(signature_version="s3v4"),
        )

    # URL helpers
    # -----------------------
    def get_s3_url(self, key: str) -> str:
        """S3-style path, mostly useful for debugging / logging."""
        return f"s3://{self.bucket_name}/{key}"

    def get_public_url(self, key: str) -> str:
        """
        Public https URL.
        This only works if the bucket/object is readable (like for a public gallery).
        """
        safe_key = quote(key, safe="/")
        return f"https://{self.bucket_name}.s3.amazonaws.com/{safe_key}"

    # Presigned URLs
    # -----------------------
    def generate_presigned_upload_url(self, key: str, mime_type: str, expires_in: int = 3600) -> str:
        """
        Create a temporary upload link so the client can send the file
        straight to S3 without our Flask app streaming the bytes.
        """
        try:
            return self._s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                    "ContentType": mime_type,
                },
                ExpiresIn=expires_in,
            )
        except ClientError as e:
            raise Exception(f"S3 Error (upload): {e}") from e

    def generate_presigned_download_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Create a temporary download link.
        Good for private images because the link expires after a while.
        """
        try:
            return self._s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                },
                ExpiresIn=expires_in,
            )
        except ClientError as e:
            raise Exception(f"S3 Error (download): {e}") from e

    # Deleting files
    # -----------------------
    def delete_object(self, key: str) -> None:
        """Delete a file from S3. We use this when a user deletes an image."""
        try:
            self._s3.delete_object(Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            raise Exception(f"S3 DELETE Error: {e}") from e
