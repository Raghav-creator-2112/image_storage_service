import boto3
from . import storage  # keep import order for packaging
from ..core.config import settings

def s3():
    """Create an S3 client using our configured region/endpoint/creds.'.
    """
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

def dynamodb_table():
    """Return a DynamoDB Table handle for the configured table name."""
    return boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    ).Table(settings.table_name)
