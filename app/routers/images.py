from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import Optional, List
import json
from ..core.models import UploadResponse, ListResponse
from ..aws.storage import (
    put_image_bytes,
    list_images as list_store,
    delete_image as delete_store,
    get_image_stream,
)

router = APIRouter(prefix="/images", tags=["images"])

# Acceptable image types
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
CTYPE_TO_EXTS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
}


# Upload an image file via multipart form-data. This is easier for users
# (browse a file) and avoids base64 payloads entirely.
@router.post(
    "/upload-file",
    response_model=UploadResponse,
    status_code=201,
    summary="Upload an image (JPEG/PNG)",
    description=(
        "Select a JPG/PNG file to upload using multipart form-data.\n\n"
        "Fields:\n"
        "- `user_id` (required): owner of the image.\n"
        "- `file` (required): the image file.\n"
        "- `metadata` (optional): JSON string to attach custom metadata (e.g. {\"album\":\"trip\"}).\n"
        "- `tags` (optional): comma-separated list (e.g. 'summer,beach').\n\n"
        "The service validates JPEG/PNG and auto-extracts EXIF/basic metadata (dimensions, camera info when available)."
    ),
)
async def upload_file(
    user_id: str = Form(...),
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None, description="JSON object as a string (e.g. {\"album\":\"trip\"})"),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None, description="Comma-separated tags (e.g. 'summer,beach')"),
):
    try:
        data = await file.read()
        content_type = file.content_type or "application/octet-stream"

        # Basic validation: only allow JPEG or PNG, and common file extensions
        name_lower = (file.filename or "").lower()
        valid_ext = any(name_lower.endswith(e) for e in ALLOWED_IMAGE_EXTS)
        # Require both: supported content-type and extension, and they must match
        if content_type not in ALLOWED_IMAGE_CONTENT_TYPES or not valid_ext:
            raise ValueError("unsupported_image_type")
        # Ensure extension matches declared content-type
        expected_exts = CTYPE_TO_EXTS.get(content_type, set())
        if not any(name_lower.endswith(e) for e in expected_exts):
            raise ValueError("unsupported_image_type")
        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
                if not isinstance(parsed_metadata, dict):
                    raise ValueError("metadata_must_be_object")
            except Exception:
                raise ValueError("invalid_metadata_json")
        parsed_tags: Optional[List[str]] = None
        if tags:
            parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

        return UploadResponse(
            **put_image_bytes(
                user_id=user_id,
                filename=file.filename,
                content_type=content_type,
                data_bytes=data,
                metadata=parsed_metadata,
                title=title,
                description=description,
                tags=parsed_tags,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"upload_failed {e}")

@router.get(
    "",
    response_model=ListResponse,
    summary="List images",
    description=(
        "Returns images with optional filters.\n\n"
        "Query params:\n"
        "- `user_id`: return only images for this user.\n"
        "- `tag`: return only images that include this tag.\n"
        "- `created_after`/`created_before`: Unix seconds, inclusive.\n\n"
        "When `user_id` is provided the query uses an index for better performance."
    ),
)
def list_images(
    user_id: Optional[str] = Query(None, description="Filter by owner user id"),
    tag: Optional[str] = Query(None, description="Filter by a tag value"),
    created_after: Optional[int] = Query(None, description="Unix timestamp (seconds) inclusive"),
    created_before: Optional[int] = Query(None, description="Unix timestamp (seconds) inclusive"),
):
    try:
        items = list_store(user_id=user_id, tag=tag, created_after=created_after, created_before=created_before)
        return ListResponse(count=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_failed {e}")

# Note: The presigned-URL endpoint has been removed to avoid confusion.
# Use the streaming download endpoint below.

@router.delete(
    "/{image_id}",
    summary="Delete an image",
    description=(
        "Removes both the S3 object and the DynamoDB metadata item.\n"
        "Returns 404 if the image id does not exist."
    ),
)
def delete_image(image_id: str):
    try:
        delete_store(image_id)
        return {"deleted": image_id}
    except KeyError:
        raise HTTPException(status_code=404, detail="not_found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete_failed {e}")


@router.get(
    "/{image_id}/download",
    summary="Download an image",
    description=(
        "Streams the file through the API as an attachment and sets the original filename.\n"
        "Use this to save the file directly without dealing with presigned URLs."
    ),
)
def download_image(image_id: str):
    """Stream the image bytes directly from S3 through the API as an attachment.

    This avoids hostname rewrites in presigned URLs and works seamlessly from
    any client. Content-Disposition is set to attachment with the original
    filename when available.
    """
    try:
        info = get_image_stream(image_id)

        def _iter():
            stream = info["body"]
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                yield chunk

        headers = {
            "Content-Disposition": f"attachment; filename=\"{info['filename']}\""
        }
        if info.get("content_length") is not None:
            headers["Content-Length"] = str(info["content_length"])

        return StreamingResponse(_iter(), media_type=info["content_type"], headers=headers)
    except KeyError:
        raise HTTPException(status_code=404, detail="not_found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"download_failed {e}")
