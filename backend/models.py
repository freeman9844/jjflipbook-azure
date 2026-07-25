from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid

def utc_now():
    return datetime.now(timezone.utc)

class User(BaseModel):
    id: Optional[str] = None # Firestore Document ID
    username: str
    password_hash: str
    created_at: datetime = Field(default_factory=utc_now)

class Folder(BaseModel):
    id: Optional[str] = None
    name: str
    user_id: str = "admin"
    created_at: datetime = Field(default_factory=utc_now)

class Flipbook(BaseModel):
    uuid_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    folder_id: Optional[str] = None # 속한 폴더의 ID (null 이면 최상단)
    user_id: str = "admin"
    page_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    # Firestore는 리스트(배열)를 직접 지원하므로 변경
    image_urls: List[str] = [] 
    pdf_url: Optional[str] = None

class Overlay(BaseModel):
    id: Optional[str] = None
    flipbook_id: str
    page: int
    type: str  # 'link', 'video'
    x: float
    y: float
    width: float
    height: float
    data_url: str # YouTube URL 또는 리다이렉트 링크
