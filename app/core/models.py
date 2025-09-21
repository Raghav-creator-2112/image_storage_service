from typing import Optional, List
from pydantic import BaseModel

class UploadRequest(BaseModel):
    user_id: str
    filename: str
    content_type: str
    data_base64: str
    metadata: Optional[dict] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None

class UploadResponse(BaseModel):
    image_id: str
    url: str

class ListResponse(BaseModel):
    count: int
    items: list

class UrlResponse(BaseModel):
    url: str