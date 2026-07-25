import logging
from fastapi import APIRouter
from database import get_blob_container, sign_url, BLOB_BASE_URL

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Music"])


@router.get("/music/list")
def list_music():
    """BGM 목록을 SAS 서명된 URL로 반환한다."""
    try:
        blobs = get_blob_container().list_blobs(name_starts_with="bgm/")
        files = [
            sign_url(f"{BLOB_BASE_URL}/{b.name}")
            for b in blobs
            if b.name.endswith(".mp3")
        ]
        return {"files": files}
    except Exception as e:
        logger.warning(f"⚠️ [Music] Failed to list BGM blobs: {e}")
        return {"files": []}
