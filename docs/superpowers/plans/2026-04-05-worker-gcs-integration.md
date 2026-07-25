# Worker GCS 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분리된 Worker 컨테이너가 원본 PDF에 접근할 수 있도록, API 컨테이너가 GCS에 먼저 PDF를 업로드하고 Worker는 GCS에서 다운로드 받아 처리하는 Claim-Check 패턴을 구현합니다.

**Architecture:** 
1. `backend/routers/flipbooks.py` (`/upload`): PDF를 로컬 저장소뿐만 아니라 **즉시 GCS 버킷(`flipbooks/.../original.pdf`)에 업로드**합니다. Cloud Tasks 페이로드에는 로컬 경로 대신 GCS 오브젝트 이름(prefix)을 전달하도록 변경합니다.
2. `backend/services/flipbook_service.py` (`process_pdf_task`): 전달받은 식별자를 기반으로 로컬에 작업 폴더를 생성하고, **GCS에서 `original.pdf`를 다운로드**하여 변환 작업을 수행하도록 로직을 수정합니다. 기존 로컬 경로 의존성을 제거합니다.

**Tech Stack:** `FastAPI`, `Google Cloud Storage`, `Google Cloud Tasks`

---

### Task 1: `flipbook_service.py` 리팩토링 (Worker가 GCS에서 다운로드하도록 변경)

**Files:**
- Modify: `backend/services/flipbook_service.py`
- Modify: `backend/routers/worker.py`
- Modify: `backend/tests/test_worker_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_worker_api.py (modify existing)
from fastapi.testclient import TestClient
from main import app
from unittest.mock import patch, MagicMock
from routers.worker import ProcessPdfPayload

client = TestClient(app)

@patch('routers.worker.process_pdf_task')
def test_worker_process_pdf_endpoint(mock_process_task):
    payload = {
        "uuid_key": "test-uuid",
        "date_str": "20240101",
        "split_pages": True
    }
    response = client.post("/worker/process-pdf", json=payload)
    
    assert response.status_code == 200
    assert response.json() == {"status": "processing"}
    # The new signature doesn't need local paths in the payload
    mock_process_task.assert_called_once_with(
        "test-uuid", "20240101", True
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_worker_api.py -v`
Expected: FAIL due to signature mismatch in `ProcessPdfPayload` and `assert_called_once_with` mismatch.

- [ ] **Step 3: Write minimal implementation for router**

Modify `backend/routers/worker.py`:
```python
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from services.flipbook_service import process_pdf_task

router = APIRouter(prefix="/worker", tags=["Worker"])

class ProcessPdfPayload(BaseModel):
    uuid_key: str
    date_str: str
    split_pages: bool = True

@router.post("/process-pdf")
async def handle_process_pdf(payload: ProcessPdfPayload, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        process_pdf_task,
        payload.uuid_key,
        payload.date_str,
        payload.split_pages
    )
    return {"status": "processing"}
```

Modify `backend/services/flipbook_service.py` to change the signature and download from GCS:
```python
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from database import db, bucket, GCS_BUCKET_NAME
from pdf_utils import convert_pdf_to_images

logger = logging.getLogger(__name__)

# ... keep delete_single_flipbook ...

def process_pdf_task(uuid_key: str, date_str: str, split_pages: bool = True):
    """백그라운드에서 GCS에서 PDF를 받아 이미지로 변환하고 GCS에 업로드 후 Firestore 업데이트."""
    # 로컬 작업 디렉토리 생성
    STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
    book_storage = os.path.join(STORAGE_DIR, uuid_key)
    os.makedirs(book_storage, exist_ok=True)
    pdf_path = os.path.join(book_storage, "original.pdf")
    
    try:
        # [NEW] 1. GCS에서 원본 PDF 다운로드
        pdf_blob_name = f"flipbooks/{date_str}/{uuid_key}/original.pdf" if date_str else f"flipbooks/{uuid_key}/original.pdf"
        pdf_blob = bucket.blob(pdf_blob_name)
        
        # 파일이 존재하는지 먼저 확인
        if not pdf_blob.exists():
            raise FileNotFoundError(f"Original PDF not found in GCS: {pdf_blob_name}")
            
        pdf_blob.download_to_filename(pdf_path)
        logger.info(f"✅ [Background] Downloaded original PDF from GCS for {uuid_key}")
        
        # 2. 로컬에 임시 변환 저장
        filenames = convert_pdf_to_images(pdf_path, book_storage, split_pages=split_pages)
        
        # 3. GCS 버킷에 이미지 업로드 및 URL 수집 (병렬 처리)
        def upload_worker(fname: str):
            local_path = os.path.join(book_storage, fname)
            blob = bucket.blob(f"flipbooks/{date_str}/{uuid_key}/{fname}")
            blob.upload_from_filename(local_path)
            return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/flipbooks/{date_str}/{uuid_key}/{fname}"
            
        with ThreadPoolExecutor(max_workers=5) as executor:
            uploaded_urls = list(executor.map(upload_worker, filenames))
            
        pdf_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{pdf_blob_name}"
            
        # 4. Firestore 도큐먼트 업데이트
        db.collection("flipbooks").document(uuid_key).update({
            "page_count": len(filenames),
            "image_urls": uploaded_urls,
            "pdf_url": pdf_url,
            "status": "success"
        })
        logger.info(f"✅ [Background] Flipbook-{uuid_key} Firestore Updated successfully. ({len(filenames)} pages)")
             
    except Exception as e:
        logger.error(f"❌ [Background] Error processing PDF-{uuid_key}: {str(e)}")
        # 실패 상태 Firestore 기록
        try:
             db.collection("flipbooks").document(uuid_key).update({
                  "status": "failed",
                  "error_message": str(e)
             })
        except Exception as fe:
             logger.error(f"❌ [Background] Failed to update fail status for {uuid_key}: {str(fe)}")
    finally:
        # 5. 로컬 템플러리 스페이스 소거 정리 (Clean up)
        import shutil
        if os.path.exists(book_storage):
             shutil.rmtree(book_storage)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_worker_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/flipbook_service.py backend/routers/worker.py backend/tests/test_worker_api.py
git commit -m "refactor(backend): worker downloads pdf from gcs instead of local path"
```

---

### Task 2: `/upload` API 변경 (GCS에 즉시 업로드)

**Files:**
- Modify: `backend/routers/flipbooks.py`
- Modify: `backend/tests/test_flipbooks_cloud_tasks.py`
- Modify: `backend/tests/test_api_local.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_flipbooks_cloud_tasks.py (modify existing)
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app
from utils import verify_api_key

client = TestClient(app)

@patch('routers.flipbooks.bucket')
@patch('routers.flipbooks.enqueue_pdf_processing_task')
def test_upload_pdf_uses_cloud_tasks(mock_enqueue, mock_bucket, tmp_path, monkeypatch):
    app.dependency_overrides[verify_api_key] = lambda: True
    monkeypatch.setenv("WORKER_URL", "http://mock-worker")
    
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    
    # Create a dummy pdf file
    pdf_file = tmp_path / "dummy.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy content")
    
    with open(pdf_file, "rb") as f:
        response = client.post(
            "/upload",
            files={"file": ("dummy.pdf", f, "application/pdf")},
            params={"split_pages": "true"}
        )
    
    assert response.status_code == 200
    mock_enqueue.assert_called_once()
    mock_bucket.blob.assert_called_once()
    mock_blob.upload_from_filename.assert_called_once()
    
    # Verify payload changed
    call_args = mock_enqueue.call_args[1]
    assert "pdf_path" not in call_args["payload"]
    assert "uuid_key" in call_args["payload"]
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_flipbooks_cloud_tasks.py -v`
Expected: FAIL because `mock_bucket.blob` is not called in the upload endpoint currently.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/routers/flipbooks.py`:
```python
import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Query
from database import db, bucket, GOOGLE_CLOUD_PROJECT
from models import Flipbook, Overlay
from utils import verify_api_key
from services.flipbook_service import process_pdf_task, delete_single_flipbook
from cloud_tasks import enqueue_pdf_processing_task
import aiofiles
from datetime import datetime, timezone

router = APIRouter(tags=["Flipbooks"])

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")

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
    # 상태를 'uploading'으로 초기 세팅 (옵션)
    data["status"] = "uploading"
    db.collection("flipbooks").document(book.uuid_key).set(data)
    
    book_dir = os.path.join(STORAGE_DIR, book.uuid_key)
    os.makedirs(book_dir, exist_ok=True)
    
    # 1. 로컬에 임시 저장 (FastAPI UploadFile 처리를 위함)
    pdf_path = os.path.join(book_dir, "original.pdf")
    async with aiofiles.open(pdf_path, 'wb') as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)
            
    # [NEW] 2. 로컬에 저장된 원본을 GCS에 즉시 업로드 (Claim-Check 패턴)
    pdf_blob_name = f"flipbooks/{date_str}/{book.uuid_key}/original.pdf"
    pdf_blob = bucket.blob(pdf_blob_name)
    pdf_blob.upload_from_filename(pdf_path)
    
    # DB 상태 업데이트
    db.collection("flipbooks").document(book.uuid_key).update({"status": "processing"})
            
    worker_url = os.getenv("WORKER_URL")
    if worker_url:
        location = os.getenv("REGION", "asia-northeast3")
        queue_name = os.getenv("TASK_QUEUE_NAME", "pdf-worker-queue")
        
        # Payload에서 로컬 경로(pdf_path, book_storage) 제거
        payload = {
            "uuid_key": book.uuid_key,
            "date_str": date_str,
            "split_pages": split_pages
        }
        
        try:
            enqueue_pdf_processing_task(
                project_id=GOOGLE_CLOUD_PROJECT,
                location=location,
                queue=queue_name,
                worker_url=f"{worker_url}/worker/process-pdf",
                payload=payload
            )
        except Exception as e:
            # 실패 시 상태 롤백
            db.collection("flipbooks").document(book.uuid_key).update({"status": "failed", "error_message": "Task enqueue failed"})
            raise HTTPException(status_code=500, detail=f"Failed to enqueue processing task: {str(e)}")
    else:
        import threading
        thread = threading.Thread(target=process_pdf_task, args=(book.uuid_key, date_str, split_pages))
        thread.start()
        
    # (Optional) 임시 파일 삭제 로직 추가 가능하지만, Worker가 다른 컨테이너라면 여기서 지워도 됨. 
    # 로컬 개발 환경(동일 프로세스)을 위해 일단 놔두거나 분기 처리.
    if worker_url:
        import shutil
        if os.path.exists(book_dir):
            shutil.rmtree(book_dir)
    
    return {
         "status": "ok", 
         "message": "PDF uploaded to GCS successfully. Processing queued.", 
         "book_id": book.uuid_key
    }

# ... rest of file (list_flipbooks, get_flipbook, etc.) ...
```

In `backend/tests/test_api_local.py`, modify line 46-47 in `test_local_pdf_upload` to match the new signature:
```python
    # Ensure to mock bucket if not already done, or adjust assertion
    mock_process.assert_called_once()
    # verify payload or just that it's called
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/flipbooks.py backend/tests/test_flipbooks_cloud_tasks.py backend/tests/test_api_local.py
git commit -m "feat(backend): api uploads original pdf to gcs for worker access"
```
