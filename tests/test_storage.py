import os, sys
import urllib.parse as urlparse

import pytest
from moto import mock_aws
import boto3
from PIL import Image
from io import BytesIO

# Ensure project root on path for `import app...`
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.config import settings
from app.aws import storage
from app.aws.clients import s3 as s3_client_factory, dynamodb_table as dynamodb_table_factory


@pytest.fixture(autouse=False)
def aws_mock(monkeypatch):
    with mock_aws():
        # Ensure our clients do not try to hit a custom endpoint in tests
        monkeypatch.setattr(settings, "aws_endpoint_url", None)
        monkeypatch.setattr(settings, "aws_region", "us-east-1")
        monkeypatch.setattr(settings, "bucket_name", "test-bucket")
        monkeypatch.setattr(settings, "table_name", "Images")
        monkeypatch.setattr(settings, "url_expiry", 60)

        # Create S3 bucket
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.create_bucket(Bucket=settings.bucket_name)

        # Create DynamoDB table with expected schema and GSI
        dynamodb = boto3.client("dynamodb", region_name=settings.aws_region)
        dynamodb.create_table(
            TableName=settings.table_name,
            AttributeDefinitions=[
                {"AttributeName": "image_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "N"},
            ],
            KeySchema=[{"AttributeName": "image_id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by_user_created",
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )

        yield


def _query_params(url: str) -> dict:
    parsed = urlparse.urlparse(url)
    return dict(urlparse.parse_qsl(parsed.query))


def _png_bytes():
    # Generate a tiny 2x2 PNG in-memory
    img = Image.new('RGB', (2, 2), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def test_storage_put_presign_delete_flow_success(aws_mock, monkeypatch):
    # Freeze time for deterministic created_at
    monkeypatch.setattr("app.aws.storage.time.time", lambda: 1000)

    content = _png_bytes()
    resp = storage.put_image_bytes(
        user_id="u1",
        filename="pic.png",
        content_type="image/png",
        data_bytes=content,
        metadata={"a": "b"},
        title="t",
        description="d",
        tags=["red", "fun"],
    )

    assert "image_id" in resp and resp["image_id"]
    assert "url" in resp and resp["url"].startswith("http")

    image_id = resp["image_id"]

    # Validate DynamoDB item exists
    table = dynamodb_table_factory()
    item = table.get_item(Key={"image_id": image_id}).get("Item")
    assert item is not None
    assert item["user_id"] == "u1"
    assert item["filename"] == "pic.png"
    assert item["created_at"] == 1000
    assert item["tags"] == ["red", "fun"]
    # Auto metadata should be present for image files
    assert "auto_metadata" in item
    assert item["auto_metadata"]["width"] > 0
    assert item["auto_metadata"]["height"] > 0

    # Validate S3 object exists
    s3 = s3_client_factory()
    obj = s3.get_object(Bucket=item["bucket_name"], Key=item["object_key"])  # no exception
    assert int(obj["ContentLength"]) == len(content)

    # Presigned URL (inline)
    url_inline = storage.presigned_get(image_id=image_id, download=False)["url"]
    qp = _query_params(url_inline)
    assert "response-content-disposition" in qp
    assert "inline" in urlparse.unquote(qp["response-content-disposition"]).lower()

    # Presigned URL (attachment)
    url_attach = storage.presigned_get(image_id=image_id, download=True)["url"]
    qp = _query_params(url_attach)
    assert "response-content-disposition" in qp
    assert "attachment" in urlparse.unquote(qp["response-content-disposition"]).lower()

    # Delete
    storage.delete_image(image_id)
    assert table.get_item(Key={"image_id": image_id}).get("Item") is None
    with pytest.raises(Exception):
        s3.get_object(Bucket=item["bucket_name"], Key=item["object_key"])  # should be gone


def test_storage_list_images_filters_success(aws_mock, monkeypatch):
    # Create three images with controlled timestamps via a simple counter
    counter = {"t": 1000}
    def fake_time():
        v = counter["t"]
        counter["t"] += 500  # 1000, 1500, 2000
        return v
    monkeypatch.setattr("app.aws.storage.time.time", fake_time)

    def up(user, tags):
        return storage.put_image_bytes(
            user_id=user,
            filename="img.png",
            content_type="image/png",
            data_bytes=_png_bytes(),
            tags=tags,
        )

    up("u1", ["tag1"])   # created_at 1000
    up("u1", ["tag2"])   # created_at 1500
    up("u2", ["tag1", "tag3"])  # created_at 2000

    # By user
    items = storage.list_images(user_id="u1")
    assert len(items) == 2
    assert all(i["user_id"] == "u1" for i in items)

    # By user + created_after
    items = storage.list_images(user_id="u1", created_after=1500)
    assert len(items) == 1
    # Only the second u1 item has created_at >= 1500 in this sequence
    assert all(i["user_id"] == "u1" and int(i["created_at"]) >= 1500 for i in items)

    # By tag (scan path)
    items = storage.list_images(tag="tag1")
    assert len(items) == 2
    assert set(i["user_id"] for i in items) == {"u1", "u2"}

    # By created_before (scan path)
    items = storage.list_images(created_before=1600)
    # Should include all items with created_at <= 1600 (at least one expected)
    assert len(items) >= 1
    assert all(int(i["created_at"]) <= 1600 for i in items)
