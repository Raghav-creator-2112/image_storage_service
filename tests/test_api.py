import os, sys, json
from io import BytesIO

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from PIL import Image

# Ensure project root on sys.path so `import app...` works
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.config import settings
from app.main import app
from app.aws.clients import dynamodb_table as dynamodb_table_factory


def _png_bytes(size=(3, 2), color=(0, 128, 255)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def api_mock(monkeypatch):
    with mock_aws():
        # Route boto3 to moto (no endpoint), use test resources
        monkeypatch.setattr(settings, "aws_endpoint_url", None)
        monkeypatch.setattr(settings, "aws_region", "us-east-1")
        monkeypatch.setattr(settings, "bucket_name", "test-bucket")
        monkeypatch.setattr(settings, "table_name", "Images")

        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.create_bucket(Bucket=settings.bucket_name)
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
        yield TestClient(app)


def test_images_uploadfile_list_download_delete_success(api_mock):
    client = api_mock
    data = _png_bytes()

    # Upload a valid PNG
    files = {
        "file": ("img.png", data, "image/png"),
    }
    form = {"user_id": "u1", "tags": "tagA,tagB", "title": "t1"}
    r = client.post("/images/upload-file", files=files, data=form)
    assert r.status_code == 201, r.text
    payload = r.json()
    image_id = payload["image_id"]
    assert image_id

    # List by user
    r = client.get("/images", params={"user_id": "u1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["user_id"] == "u1"
    assert body["items"][0].get("tags") == ["tagA", "tagB"]

    # Download stream
    r = client.get(f"/images/{image_id}/download")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/")
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert r.content == data

    # Delete and verify gone
    r = client.delete(f"/images/{image_id}")
    assert r.status_code == 200
    # download again -> 404
    r = client.get(f"/images/{image_id}/download")
    assert r.status_code == 404


def test_images_uploadfile_unsupported_type_failure(api_mock):
    client = api_mock
    files = {"file": ("bad.txt", b"hello", "text/plain")}
    r = client.post("/images/upload-file", files=files, data={"user_id": "u1"})
    assert r.status_code == 400
    assert r.json()["detail"] == "unsupported_image_type"


def test_images_uploadfile_metadata_parsing_success(api_mock):
    client = api_mock
    data = _png_bytes()

    # Invalid JSON
    files = {"file": ("img.png", data, "image/png")}
    r = client.post(
        "/images/upload-file",
        files=files,
        data={"user_id": "u1", "metadata": "not-json"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_metadata_json"

    # Valid JSON; ensure stored item contains auto_metadata and user_metadata
    files = {"file": ("img2.png", data, "image/png")}
    meta = json.dumps({"custom": "yes"})
    r = client.post(
        "/images/upload-file",
        files=files,
        data={"user_id": "u2", "metadata": meta},
    )
    assert r.status_code == 201
    image_id = r.json()["image_id"]

    table = dynamodb_table_factory()
    item = table.get_item(Key={"image_id": image_id}).get("Item")
    assert item is not None
    assert "auto_metadata" in item
    assert item["auto_metadata"]["width"] > 0
    assert item.get("user_metadata", {}).get("custom") == "yes"


def test_images_uploadfile_mismatched_extension_failure(api_mock):
    client = api_mock
    data = _png_bytes()
    # Filename says .jpg but content-type is image/png → reject
    files = {"file": ("a.jpg", data, "image/png")}
    r = client.post("/images/upload-file", files=files, data={"user_id": "u1"})
    assert r.status_code == 400
    assert r.json()["detail"] == "unsupported_image_type"


def test_images_uploadfile_invalid_image_bytes_failure(api_mock):
    client = api_mock
    # Content type looks fine, but bytes are not an image → reject by Pillow validation
    files = {"file": ("a.png", b"not_an_image", "image/png")}
    r = client.post("/images/upload-file", files=files, data={"user_id": "u1"})
    assert r.status_code == 400
    assert r.json()["detail"] == "unsupported_image_type"


def test_images_delete_404_failure(api_mock):
    client = api_mock
    r = client.delete("/images/not-found-id")
    assert r.status_code == 404


def test_images_list_without_filters_success(api_mock):
    client = api_mock
    d1 = _png_bytes(); d2 = _png_bytes()
    r = client.post("/images/upload-file", files={"file": ("a.png", d1, "image/png")}, data={"user_id": "u1"})
    assert r.status_code == 201
    r = client.post("/images/upload-file", files={"file": ("b.png", d2, "image/png")}, data={"user_id": "u2"})
    assert r.status_code == 201
    r = client.get("/images")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
