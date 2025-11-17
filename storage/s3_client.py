"""AWS S3 client and operations for object storage."""
import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

# --- S3 Setup ---
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")

if not AWS_S3_BUCKET_NAME:
    print("Error: AWS_S3_BUCKET_NAME environment variable not set.")

s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    config=Config(signature_version="s3v4"),
)

def get_s3_url(key):
    """Get S3 URL reference for a given key."""
    return f"s3://{AWS_S3_BUCKET_NAME}/{key}"

def get_public_url(key):
    """Get the public HTTPS URL for an object (requires public bucket or CDN)."""
    return f"https://{AWS_S3_BUCKET_NAME}.s3.amazonaws.com/{key}"

def generate_presigned_upload_url(key, mime_type, expires_in=3600):
    """Generate a presigned URL for uploading an object to S3."""
    try:
        return s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": AWS_S3_BUCKET_NAME,
                "Key": key,
                "ContentType": mime_type,
            },
            ExpiresIn=expires_in,
        )
    except ClientError as e:
        raise Exception(f"S3 Error: {e}") from e

def generate_presigned_download_url(key, expires_in=3600):
    """Generate a presigned URL for downloading an object from S3."""
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": AWS_S3_BUCKET_NAME,
                "Key": key,
            },
            ExpiresIn=expires_in
        )
    except ClientError as e:
        raise Exception(f"S3 Error: {e}") from e

def delete_object(key):
    """Delete an object from S3."""
    try:
        s3.delete_object(Bucket=AWS_S3_BUCKET_NAME, Key=key)
    except ClientError as e:
        raise Exception(f"S3 DELETE Error: {e}") from e


