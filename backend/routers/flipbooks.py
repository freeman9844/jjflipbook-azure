import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Query
from database import get_db
from models import Flipbook, Overlay
from utils import verify_api_key
from services.flipbook_service import process_pdf_task, delete_single_flipbook
import aiofiles
from datetime import datetime, timezone

router = APIRouter(tags=["Flipbooks"])

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")

from fastapi.concurrency import run_in_threadpool

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
    
    data = book.model_dump()
    data["date_folder"] = date_str
    data["status"] = "processing"
    get_db().collection("flipbooks").document(book.uuid_key).set(data)
    
    book_dir = os.path.join(STORAGE_DIR, book.uuid_key)
    os.makedirs(book_dir, exist_ok=True)
    
    pdf_path = os.path.join(book_dir, "original.pdf")
    async with aiofiles.open(pdf_path, 'wb') as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    # CPU Request-based(Throttled) 모드 최적화를 위해 쓰레드풀에서 동기 대기
    # 응답(200 OK)이 나가면 CPU가 0에 가깝게 줄어들므로, 변환을 마치고 응답해야 합니다.
    await run_in_threadpool(process_pdf_task, pdf_path, book_dir, book.uuid_key, date_str, split_pages)

    return {
         "status": "ok", 
         "message": "PDF uploaded and processed successfully.", 
         "book_id": book.uuid_key
    }
@router.get("/flipbooks")
def list_flipbooks():
    docs = (
        get_db().collection("flipbooks")
        .order_by("created_at", direction="DESCENDING")
        .limit(50)
        .stream()
    )
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results.append(d)
    return results

@router.get("/flipbook/{uuid_key}")
def get_flipbook(uuid_key: str):
    doc_ref = get_db().collection("flipbooks").document(uuid_key)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Flipbook not found")
        
    book = doc.to_dict()
    book["id"] = uuid_key
    return book

@router.get("/flipbook/{uuid_key}/overlays")
def get_overlays(uuid_key: str):
    doc_ref = get_db().collection("flipbooks").document(uuid_key)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Flipbook not found")

    docs = doc_ref.collection("overlays").stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results.append(d)
    return results

@router.post("/flipbook/{uuid_key}/overlays")
def update_overlays(uuid_key: str, overlays: list[dict]):
    doc_ref = get_db().collection("flipbooks").document(uuid_key)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Flipbook not found")

    # 삭제 + 추가를 단일 batch로 원자적 처리
    batch = get_db().batch()

    existing_docs = doc_ref.collection("overlays").stream()
    for d in existing_docs:
        batch.delete(d.reference)

    for data in overlays:
        new_ref = doc_ref.collection("overlays").document()
        batch.set(new_ref, data)

    batch.commit()
    return {"status": "ok", "message": f"{len(overlays)} overlays updated"}

@router.delete("/flipbook/{uuid_key}")
def delete_flipbook(uuid_key: str, validated: bool = Depends(verify_api_key)):
    doc = get_db().collection("flipbooks").document(uuid_key).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Flipbook not found")

    date_str = (doc.to_dict() or {}).get("date_folder", "")
    delete_single_flipbook(uuid_key, date_str)
    return {"status": "ok", "message": "Flipbook deleted successfully"}
