from typing import Optional, List, Dict, Any
import base64
import time
import uuid
from io import BytesIO
from boto3.dynamodb.conditions import Key, Attr
from PIL import Image, ExifTags
from ..core.config import settings
from .clients import s3 as s3_client_factory, dynamodb_table as dynamodb_table_factory

"""Storage helpers for putting, listing, signing and deleting images.
"""


def _extract_image_metadata(data_bytes: bytes) -> Dict[str, Any]:
    """Open the image and extract a small, useful set of metadata.

    Returns a dict containing width/height, format, and selected tags
    when available. Fails soft by returning an empty dict if parsing fails.
    """
    meta: Dict[str, Any] = {}
    try:
        with Image.open(BytesIO(data_bytes)) as img:
            width, height = img.size
            meta.update(
                {
                    "width": width,
                    "height": height,
                    "pixels": f"{width}x{height}",
                    "format": img.format,
                    "mode": img.mode,
                }
            )

            # Map tag ids to names
            exif_data = {}
            try:
                raw = getattr(img, "_getexif", lambda: None)()  # type: ignore[attr-defined]
                if raw:
                    tag_map = {ExifTags.TAGS.get(k, str(k)): v for k, v in raw.items()}
                    for key in [
                        "Make",
                        "Model",
                        "Software",
                        "DateTimeOriginal",
                        "Orientation",
                        "PixelXDimension",
                        "PixelYDimension",
                    ]:
                        if key in tag_map:
                            exif_data[key] = tag_map[key]
            except Exception:
                pass

            if exif_data:
                meta["exif"] = exif_data
    except Exception:
       
        return {}

    return meta



def _store_image(
    *,
    data_bytes: bytes,
    user_id: str,
    filename: str,
    content_type: str,
    metadata: Optional[dict] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> dict:
    # Validate the file type
    try:
        with Image.open(BytesIO(data_bytes)) as img:
            fmt = (img.format or '').upper()
            if fmt not in {"JPEG", "PNG"}:
                raise ValueError("unsupported_image_type")
    except Exception:
        raise ValueError("unsupported_image_type")
    if not user_id or not filename or not content_type or data_bytes is None:
        raise ValueError("missing_required_fields")

    image_id = uuid.uuid4().hex
    created_at = int(time.time())
    object_key = f"{user_id}/{image_id}/{filename}"

    s3 = s3_client_factory()
    table = dynamodb_table_factory()

    # Upload object to S3 
    s3.put_object(
        Bucket=settings.bucket_name,
        Key=object_key,
        Body=data_bytes,
        ContentType=content_type,
        Metadata={},
    )

    item: Dict[str, Any] = {
        "image_id": image_id,
        "user_id": user_id,
        "created_at": created_at,
        "filename": filename,
        "content_type": content_type,
        "size": len(data_bytes),
        "bucket_name": settings.bucket_name,
        "object_key": object_key,
    }
    if title is not None:
        item["title"] = title
    if description is not None:
        item["description"] = description
    if tags is not None:
        item["tags"] = tags

    # Auto-extract image metadata;
    auto_meta = _extract_image_metadata(data_bytes)
    if auto_meta:
        item["auto_metadata"] = auto_meta
    if metadata is not None:
        item["user_metadata"] = metadata

    table.put_item(Item=item)

    url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": settings.bucket_name, "Key": object_key},
        ExpiresIn=int(settings.url_expiry),
    )

    return {"image_id": image_id, "url": url}


def put_image(
    user_id: str,
    filename: str,
    content_type: str,
    data_base64: str,
    metadata: Optional[dict] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> dict:
    if not user_id or not filename or not content_type or not data_base64:
        raise ValueError("missing_required_fields")
    try:
        data_bytes = base64.b64decode(data_base64)
    except Exception:
        raise ValueError("invalid_base64")
    return _store_image(
        data_bytes=data_bytes,
        user_id=user_id,
        filename=filename,
        content_type=content_type,
        metadata=metadata,
        title=title,
        description=description,
        tags=tags,
    )


def put_image_bytes(
    *,
    user_id: str,
    filename: str,
    content_type: str,
    data_bytes: bytes,
    metadata: Optional[dict] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> dict:
    return _store_image(
        data_bytes=data_bytes,
        user_id=user_id,
        filename=filename,
        content_type=content_type,
        metadata=metadata,
        title=title,
        description=description,
        tags=tags,
    )

def list_images(
    user_id: Optional[str] = None,
    tag: Optional[str] = None,
    created_after: Optional[int] = None,
    created_before: Optional[int] = None
) -> List:
    """List images with optional filters.

    If `user_id` is provided.
    """
    table = dynamodb_table_factory()

    items: List[Dict[str, Any]] = []
    exclusive_start_key = None

    if user_id:
        key_expr = Key("user_id").eq(user_id)
        if created_after is not None and created_before is not None:
            key_expr = key_expr & Key("created_at").between(int(created_after), int(created_before))
        elif created_after is not None:
            key_expr = key_expr & Key("created_at").gte(int(created_after))
        elif created_before is not None:
            key_expr = key_expr & Key("created_at").lte(int(created_before))

        filter_expr = None
        if tag:
            filter_expr = Attr("tags").contains(tag)

        while True:
            params: Dict[str, Any] = {
                "IndexName": "by_user_created",
                "KeyConditionExpression": key_expr,
            }
            if filter_expr is not None:
                params["FilterExpression"] = filter_expr
            if exclusive_start_key is not None:
                params["ExclusiveStartKey"] = exclusive_start_key

            resp = table.query(**params)
            items.extend(resp.get("Items", []))
            exclusive_start_key = resp.get("LastEvaluatedKey")
            if not exclusive_start_key:
                break
    else:
        # Fallback to full table scan (use sparingly in production)
        filter_expr = None
        if tag:
            filter_expr = Attr("tags").contains(tag)
        if created_after is not None:
            fe = Attr("created_at").gte(int(created_after))
            filter_expr = fe if filter_expr is None else (filter_expr & fe)
        if created_before is not None:
            fe = Attr("created_at").lte(int(created_before))
            filter_expr = fe if filter_expr is None else (filter_expr & fe)

        while True:
            params: Dict[str, Any] = {}
            if filter_expr is not None:
                params["FilterExpression"] = filter_expr
            if exclusive_start_key is not None:
                params["ExclusiveStartKey"] = exclusive_start_key

            resp = table.scan(**params)
            items.extend(resp.get("Items", []))
            exclusive_start_key = resp.get("LastEvaluatedKey")
            if not exclusive_start_key:
                break

    return items

def presigned_get(image_id: str, download: bool = False) -> dict:
    """Create a short-lived URL to fetch an object from S3.

    Set `download=True` to suggest a download in the browser (attachment),
    otherwise it will try to display inline if supported.
    """
    table = dynamodb_table_factory()
    s3 = s3_client_factory()

    resp = table.get_item(Key={"image_id": image_id})
    item = resp.get("Item")
    if not item:
        raise KeyError("not_found")

    bucket = item["bucket_name"]
    key = item["object_key"]
    filename = item.get("filename", "file")

    disposition = "attachment" if download else "inline"
    content_disp = f"{disposition}; filename=\"{filename}\""

    url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": content_disp,
        },
        ExpiresIn=int(settings.url_expiry),
    )
    return {"url": url}

def delete_image(image_id: str) -> None:
    """Delete both the S3 object and the DynamoDB record."""
    table = dynamodb_table_factory()
    s3 = s3_client_factory()

    resp = table.get_item(Key={"image_id": image_id})
    item = resp.get("Item")
    if not item:
        raise KeyError("not_found")

    bucket = item["bucket_name"]
    key = item["object_key"]

    s3.delete_object(Bucket=bucket, Key=key)
    table.delete_item(Key={"image_id": image_id})


def get_image_stream(image_id: str) -> Dict[str, Any]:
    """Fetch S3 object stream and basic headers for an image by id.

    Returns a dict with keys: body (StreamingBody), content_type, filename,
    content_length, bucket, key.
    """
    table = dynamodb_table_factory()
    s3 = s3_client_factory()

    resp = table.get_item(Key={"image_id": image_id})
    item = resp.get("Item")
    if not item:
        raise KeyError("not_found")

    bucket = item["bucket_name"]
    key = item["object_key"]
    filename = item.get("filename", "file")

    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"]
    content_type = obj.get("ContentType") or item.get("content_type") or "application/octet-stream"
    content_length = obj.get("ContentLength")

    return {
        "body": body,
        "content_type": content_type,
        "content_length": content_length,
        "filename": filename,
        "bucket": bucket,
        "key": key,
    }


def finalize_image(
    *,
    user_id: str,
    image_id: str,
    filename: str,
    content_type: Optional[str] = None,
    metadata: Optional[dict] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create/overwrite the DynamoDB record for an object that already exists in S3.

    This is intended for serverless presigned-upload flows where the client uploads
    directly to S3, and we later (or via S3 event) persist metadata in DynamoDB.
    The function reads the object to auto-extract metadata and records item fields.
    """
    table = dynamodb_table_factory()
    s3 = s3_client_factory()

    object_key = f"{user_id}/{image_id}/{filename}"
    try:
        head = s3.head_object(Bucket=settings.bucket_name, Key=object_key)
    except Exception as e:
        raise KeyError("not_found") from e

    # Fetch the object to extract auto metadata (dimensions/EXIF)
    obj = s3.get_object(Bucket=settings.bucket_name, Key=object_key)
    data_bytes = obj["Body"].read()
    auto_meta = _extract_image_metadata(data_bytes)

    created_at = int(time.time())
    size = int(head.get("ContentLength", len(data_bytes)))
    ctype = content_type or head.get("ContentType") or "application/octet-stream"

    item: Dict[str, Any] = {
        "image_id": image_id,
        "user_id": user_id,
        "created_at": created_at,
        "filename": filename,
        "content_type": ctype,
        "size": size,
        "bucket_name": settings.bucket_name,
        "object_key": object_key,
    }
    if auto_meta:
        item["auto_metadata"] = auto_meta
    if metadata is not None:
        item["user_metadata"] = metadata
    if title is not None:
        item["title"] = title
    if description is not None:
        item["description"] = description
    if tags is not None:
        item["tags"] = tags

    table.put_item(Item=item)
    return {"image_id": image_id}
