from fastapi import FastAPI
from .core.config import settings
from .routers.images import router as images_router

tags_metadata = [
    {
        "name": "images",
        "description": (
            "Endpoints to upload, list, download and delete images.\n\n"
            "- Upload via multipart .\n"
            "- JPEG/PNG validation + automatic EXIF/basic metadata extraction.\n"
            "- List with filters by user, tag, and time.\n"
            "- Download as an attachment."
        ),
    }
]

app = FastAPI(
    title="Image Storage Service",
    description=(
        "How to Use:\n\n"
        "1) Upload an image: use POST /images/upload-file, select a JPG/PNG file, and optionally pass `metadata` (JSON) and `tags` (comma-separated).\n"
        "2) List images: call GET /images with optional `user_id`, `tag`, `created_after`, `created_before`.\n"
        "3) Download: GET /images/{image_id}/download to save the file.\n"
        "4) Delete: DELETE /images/{image_id}` to remove both file and metadata.\n\n"
        "Notes: The service validates JPEG/PNG uploads and auto-extracts EXIF + basic metadata (dimensions, camera info when available)."
    ),
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.include_router(images_router)
