import os, sys, importlib, boto3, pytest
from moto import mock_aws
from fastapi.testclient import TestClient
from PIL import Image
from io import BytesIO

REGION = "us-east-1"


def _png_bytes():
    img = Image.new("RGB", (2, 2), color=(1, 2, 3))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@mock_aws
def test_images_upload_download_delete_success():
    os.environ["AWS_REGION"] = REGION
    os.environ["BUCKET_NAME"] = "images-bucket"
    os.environ["TABLE_NAME"] = "Images"

    boto3.client("s3", region_name=REGION).create_bucket(Bucket="images-bucket")
    ddb = boto3.client("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName="Images",
        AttributeDefinitions=[
            {"AttributeName": "image_id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "N"},
        ],
        KeySchema=[{"AttributeName": "image_id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[{
            "IndexName":"by_user_created",
            "KeySchema":[
                {"AttributeName":"user_id","KeyType":"HASH"},
                {"AttributeName":"created_at","KeyType":"RANGE"}
            ],
            "Projection":{"ProjectionType":"ALL"}
        }],
    )

    # Ensure runtime settings align with moto resources
    from app.core.config import settings as runtime_settings
    runtime_settings.aws_endpoint_url = None
    runtime_settings.aws_region = REGION
    runtime_settings.bucket_name = "images-bucket"
    runtime_settings.table_name = "Images"

    # Ensure project root on path
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    app_module = importlib.import_module("app.main")
    client = TestClient(app_module.app)

    # Upload via multipart
    data = _png_bytes()
    files = {"file": ("a.png", data, "image/png")}
    r = client.post("/images/upload-file", data={"user_id": "u1", "tags": "t1,t2", "title": "T", "description": "D"}, files=files)
    assert r.status_code == 201
    image_id = r.json()["image_id"]

    r = client.get("/images", params={"user_id": "u1", "tag": "t2"})
    assert r.status_code == 200
    assert r.json()["count"] == 1

    # Download streams the exact bytes
    r = client.get(f"/images/{image_id}/download")
    assert r.status_code == 200
    assert r.content == data

    r = client.delete(f"/images/{image_id}")
    assert r.status_code == 200
