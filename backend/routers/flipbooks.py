import os
import uuid as uuid_module
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from database import get_container, sign_url
from models import Flipbook
from utils import verify_api_key
from services.flipbook_service import process_pdf_task, delete_single_flipbook
from services.errors import (
    AssetDeletionError,
    PdfProcessingError,
    PDF_PROCESSING_FAILED_MESSAGE,
)
import aiofiles
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool

router = APIRouter(tags=["Flipbooks"])

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")


def _sign_doc(doc: dict) -> dict:
    """Cosmos 문서의 image_urls / pdf_url 필드에 SAS 서명을 적용한다."""
    doc = dict(doc)
    doc.pop("error_message", None)
    if doc.get("image_urls"):
        doc["image_urls"] = [sign_url(u) for u in doc["image_urls"]]
    if doc.get("pdf_url"):
        doc["pdf_url"] = sign_url(doc["pdf_url"])
    return doc


def _sign_summary_doc(doc: dict) -> dict:
    summary = dict(doc)
    summary.pop("error_message", None)
    cover_urls = summary.get("image_urls") or []
    summary["image_urls"] = [sign_url(cover_urls[0])] if cover_urls else []
    return summary


def _read_flipbook_or_404(uuid_key: str) -> dict:
    try:
        return get_container("flipbooks").read_item(item=uuid_key, partition_key=uuid_key)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Flipbook not found")


@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    split_pages: bool = Query(True),
    folder_id: str = Query(None),
    validated: bool = Depends(verify_api_key)
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files allowed")

    book = Flipbook(title=file.filename, folder_id=folder_id)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    data = book.model_dump(mode="json")
    data["id"] = book.uuid_key
    data["date_folder"] = date_str
    data["status"] = "processing"
    get_container("flipbooks").create_item(data)

    book_dir = os.path.join(STORAGE_DIR, book.uuid_key)
    os.makedirs(book_dir, exist_ok=True)

    pdf_path = os.path.join(book_dir, "original.pdf")
    async with aiofiles.open(pdf_path, 'wb') as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    # 응답 전에 변환을 완료해야 하므로 쓰레드풀에서 동기 대기
    try:
        await run_in_threadpool(process_pdf_task, pdf_path, book_dir, book.uuid_key, date_str, split_pages)
    except PdfProcessingError as exc:
        raise HTTPException(status_code=500, detail=PDF_PROCESSING_FAILED_MESSAGE) from exc

    return {
        "status": "ok",
        "message": "PDF uploaded and processed successfully.",
        "book_id": book.uuid_key
    }


@router.get("/flipbooks")
def list_flipbooks():
    docs = get_container("flipbooks").query_items(
        query="""
        SELECT
            c.id,
            c.uuid_key,
            c.title,
            c.folder_id,
            c.user_id,
            c.page_count,
            c.created_at,
            c.status,
            ARRAY_SLICE(c.image_urls, 0, 1) AS image_urls
        FROM c
        ORDER BY c.created_at DESC
        OFFSET 0 LIMIT 50
        """,
        enable_cross_partition_query=True,
    )
    return [_sign_summary_doc(doc) for doc in docs]


@router.get("/flipbook/{uuid_key}")
def get_flipbook(uuid_key: str):
    return _sign_doc(_read_flipbook_or_404(uuid_key))


@router.get("/flipbook/{uuid_key}/overlays")
def get_overlays(uuid_key: str):
    _read_flipbook_or_404(uuid_key)
    docs = get_container("overlays").query_items(
        query="SELECT * FROM c", partition_key=uuid_key
    )
    return list(docs)


@router.post("/flipbook/{uuid_key}/overlays")
def update_overlays(uuid_key: str, overlays: list[dict], validated: bool = Depends(verify_api_key)):
    _read_flipbook_or_404(uuid_key)
    container = get_container("overlays")

    # 기존 오버레이 전체 삭제 후 재삽입 (파티션 단위)
    existing_ids = [
        item["id"]
        for item in container.query_items(query="SELECT c.id FROM c", partition_key=uuid_key)
    ]
    for oid in existing_ids:
        container.delete_item(item=oid, partition_key=uuid_key)

    for data in overlays:
        doc = dict(data)
        doc["id"] = str(uuid_module.uuid4())
        doc["bookId"] = uuid_key
        container.create_item(doc)

    return {"status": "ok", "message": f"{len(overlays)} overlays updated"}


@router.delete("/flipbook/{uuid_key}")
def delete_flipbook(uuid_key: str, validated: bool = Depends(verify_api_key)):
    doc = _read_flipbook_or_404(uuid_key)
    date_str = doc.get("date_folder", "")
    try:
        delete_single_flipbook(uuid_key, date_str)
    except AssetDeletionError as exc:
        raise HTTPException(
            status_code=502,
            detail="Flipbook assets could not be deleted",
        ) from exc
    return {"status": "ok", "message": "Flipbook deleted successfully"}
