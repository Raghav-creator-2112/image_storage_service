import os
from pydantic import BaseModel
from typing import Optional

class Settings(BaseModel):
    """for reading environment-driven configuration.

    Values have sensible defaults for LocalStack-based development.
    """
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "test")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    aws_endpoint_url: Optional[str] = os.getenv("AWS_ENDPOINT_URL")
    bucket_name: str = os.getenv("BUCKET_NAME", "images")
    table_name: str = os.getenv("TABLE_NAME", "images")
    url_expiry: int = int(os.getenv("URL_EXPIRY", "900"))

settings = Settings()
