# Cloud Run 비동기 작업 분리 최적화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI의 `BackgroundTasks`로 처리하던 무거운 PDF 변환 작업을 Google Cloud Tasks와 별도의 Worker 인스턴스로 분리하여 유휴 비용을 최적화합니다.

**Architecture:** 
1. `backend/services/flipbook_service.py`에 구현된 `process_pdf_task` 로직을 별도의 Worker API 엔드포인트로 노출합니다.
2. `backend/routers/flipbooks.py`의 `/upload` 엔드포인트에서 Cloud Tasks를 호출하여 Worker 엔드포인트로 작업을 위임합니다.
3. `deploy.sh`를 수정하여 단일 Cloud Run 서비스(`flipbook-backend`)를 API(`flipbook-api`)와 Worker(`flipbook-worker`) 두 개의 서비스로 분리 배포하고, API 서비스에는 `--cpu-throttling` 옵션을 적용합니다.

**Tech Stack:** `FastAPI`, `Google Cloud Tasks`, `Google Cloud Run`, `Bash`

---

### Task 1: Google Cloud Tasks 클라이언트 연동 모듈 작성

**Files:**
- Create: `backend/cloud_tasks.py`
- Modify: `backend/requirements.txt:23`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cloud_tasks.py
import pytest
from unittest.mock import patch, MagicMock

@patch('google.cloud.tasks_v2.CloudTasksClient')
def test_create_pdf_task(mock_client_class):
    mock_client = mock_client_class.return_value
    mock_client.create_task.return_value = MagicMock(name="tasks/test-task")
    
    from cloud_tasks import enqueue_pdf_processing_task
    
    result = enqueue_pdf_processing_task(
        project_id="test-project",
        location="asia-northeast3",
        queue="pdf-worker-queue",
        worker_url="https://worker.example.com/worker/process-pdf",
        payload={"pdf_path": "test.pdf", "book_storage": "/tmp/book", "uuid_key": "123", "date_str": "20240101", "split_pages": True}
    )
    
    assert result is not None
    mock_client.create_task.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_cloud_tasks.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cloud_tasks'" or "google-cloud-tasks not installed"

- [ ] **Step 3: Update requirements and write minimal implementation**

Modify `backend/requirements.txt` to append:
```text
google-cloud-tasks==2.14.3
```

Create `backend/cloud_tasks.py`:
```python
import json
from google.cloud import tasks_v2

def enqueue_pdf_processing_task(project_id: str, location: str, queue: str, worker_url: str, payload: dict):
    client = tasks_v2.CloudTasksClient()
    
    parent = client.queue_path(project_id, location, queue)
    
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": worker_url,
            "headers": {"Content-type": "application/json"},
            "body": json.dumps(payload).encode(),
        }
    }
    
    response = client.create_task(request={"parent": parent, "task": task})
    return response
```

Run: `backend/venv/bin/pip install -r backend/requirements.txt`

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_cloud_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/cloud_tasks.py backend/tests/test_cloud_tasks.py
git commit -m "feat(backend): add google-cloud-tasks client module"
```

---

### Task 2: Worker 엔드포인트 구현 (Worker 서비스용)

**Files:**
- Create: `backend/routers/worker.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_worker_api.py
from fastapi.testclient import TestClient
from main import app
from unittest.mock import patch

client = TestClient(app)

@patch('services.flipbook_service.process_pdf_task')
def test_worker_process_pdf_endpoint(mock_process_task):
    payload = {
        "pdf_path": "/tmp/test.pdf",
        "book_storage": "/tmp/storage",
        "uuid_key": "test-uuid",
        "date_str": "20240101",
        "split_pages": True
    }
    response = client.post("/worker/process-pdf", json=payload)
    
    assert response.status_code == 200
    assert response.json() == {"status": "processing"}
    mock_process_task.assert_called_once_with(
        "/tmp/test.pdf", "/tmp/storage", "test-uuid", "20240101", True
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_worker_api.py -v`
Expected: FAIL with 404 Not Found (endpoint does not exist)

- [ ] **Step 3: Write minimal implementation**

Create `backend/routers/worker.py`:
```python
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from services.flipbook_service import process_pdf_task

router = APIRouter(prefix="/worker", tags=["Worker"])

class ProcessPdfPayload(BaseModel):
    pdf_path: str
    book_storage: str
    uuid_key: str
    date_str: str
    split_pages: bool = True

@router.post("/process-pdf")
async def handle_process_pdf(payload: ProcessPdfPayload, background_tasks: BackgroundTasks):
    # Cloud Tasks request is acknowledged immediately.
    # The actual processing can be done in background of the worker instance,
    # or directly if we configure Cloud Tasks timeout appropriately.
    # For now, we'll run it in background to return 200 OK quickly to Cloud Tasks.
    background_tasks.add_task(
        process_pdf_task,
        payload.pdf_path,
        payload.book_storage,
        payload.uuid_key,
        payload.date_str,
        payload.split_pages
    )
    return {"status": "processing"}
```

Modify `backend/main.py` to include the router:
```python
# ... existing imports ...
from routers import auth, flipbooks, folders, worker # Update this line

# ... existing code ...
app.include_router(auth.router)
app.include_router(flipbooks.router)
app.include_router(folders.router)
app.include_router(worker.router) # Add this line
# ... existing code ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_worker_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/worker.py backend/main.py backend/tests/test_worker_api.py
git commit -m "feat(backend): implement worker endpoint for pdf processing"
```

---

### Task 3: API 엔드포인트에서 BackgroundTasks 대신 Cloud Tasks 호출하도록 리팩토링

**Files:**
- Modify: `backend/routers/flipbooks.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_flipbooks_cloud_tasks.py
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app

client = TestClient(app)

@patch('routers.flipbooks.enqueue_pdf_processing_task')
@patch('routers.flipbooks.verify_api_key')
def test_upload_pdf_uses_cloud_tasks(mock_verify, mock_enqueue, tmp_path):
    mock_verify.return_value = True
    
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_flipbooks_cloud_tasks.py -v`
Expected: FAIL with `AssertionError: Expected 'enqueue_pdf_processing_task' to be called once. Called 0 times.`

- [ ] **Step 3: Write minimal implementation**

Modify `backend/routers/flipbooks.py`:
```python
# Add imports at the top
from cloud_tasks import enqueue_pdf_processing_task
from database import GOOGLE_CLOUD_PROJECT

# Modify the /upload endpoint
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
    db.collection("flipbooks").document(book.uuid_key).set(data)
    
    book_dir = os.path.join(STORAGE_DIR, book.uuid_key)
    os.makedirs(book_dir, exist_ok=True)
    
    pdf_path = os.path.join(book_dir, "original.pdf")
    async with aiofiles.open(pdf_path, 'wb') as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)
            
    # --- CHANGED: Use Cloud Tasks instead of BackgroundTasks ---
    worker_url = os.getenv("WORKER_URL")
    if worker_url:
        # In production, dispatch to worker service via Cloud Tasks
        location = os.getenv("REGION", "asia-northeast3")
        queue_name = os.getenv("TASK_QUEUE_NAME", "pdf-worker-queue")
        
        payload = {
            "pdf_path": pdf_path,
            "book_storage": book_dir,
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
            # Fallback or log error. In a real system you might want to handle this better.
            print(f"Error enqueuing task: {e}")
            raise HTTPException(status_code=500, detail="Failed to enqueue processing task")
    else:
        # Fallback for local development if WORKER_URL is not set
        from fastapi import BackgroundTasks
        # We need to create a BackgroundTasks instance just for this local fallback
        # which is a bit hacky in FastAPI context if not injected, but acceptable for local mock
        # Better approach for local is to just call it synchronously or use threading.
        import threading
        thread = threading.Thread(target=process_pdf_task, args=(pdf_path, book_dir, book.uuid_key, date_str, split_pages))
        thread.start()
    
    return {
         "status": "ok", 
         "message": "PDF uploaded successfully. Processing queued.", 
         "book_id": book.uuid_key
    }
```
*Note: In `routers/flipbooks.py`, you'll also need to remove `background_tasks: BackgroundTasks` from the function signature of `upload_pdf` if you are fully replacing it. I removed it in the implementation above.*

- [ ] **Step 4: Run test to verify it passes**

Run: `WORKER_URL="http://mock-worker" PYTHONPATH=./backend backend/venv/bin/pytest backend/tests/test_flipbooks_cloud_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/flipbooks.py backend/tests/test_flipbooks_cloud_tasks.py
git commit -m "refactor(backend): delegate pdf processing to cloud tasks worker"
```

---

### Task 4: 배포 스크립트(`deploy.sh`) 업데이트 - API/Worker 분리 배포

**Files:**
- Modify: `deploy.sh`

- [ ] **Step 1: Update `deploy.sh` to deploy two backend services**

Modify `deploy.sh` around line 115-140 to deploy `flipbook-api` and `flipbook-worker`.

```bash
# In deploy.sh, replace the single backend deploy block with:

echo "----------------------------------------"
echo "🌐 [2-1/4] Backend Worker Cloud Run 배포 중... (CPU Throttling 비활성화, 2Gi/2Core)"
echo "----------------------------------------"
$GCLOUD_PATH run deploy flipbook-worker \
  --project=$PROJECT_ID \
  --image $DOCKER_REPO/flipbook-backend \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --no-cpu-throttling \
  --min-instances=0 \
  --max-instances=10 \
  $VPC_OPTIONS \
  $INGRESS_OPTIONS \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT_ID,FIRESTORE_DB_NAME=$FIRESTORE_DB_NAME,GCS_BUCKET_NAME=$GCS_BUCKET_NAME

WORKER_URL=$($GCLOUD_PATH run services describe flipbook-worker --project=$PROJECT_ID --region $REGION --format 'value(status.url)')
echo "✅ Worker URL 발급 완료: $WORKER_URL"

echo "----------------------------------------"
echo "🌐 [2-2/4] Backend API Cloud Run 배포 중... (CPU Throttling 활성화, 512Mi/1Core)"
echo "----------------------------------------"
$GCLOUD_PATH run deploy flipbook-api \
  --project=$PROJECT_ID \
  --image $DOCKER_REPO/flipbook-backend \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=20 \
  $VPC_OPTIONS \
  $INGRESS_OPTIONS \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT_ID,FIRESTORE_DB_NAME=$FIRESTORE_DB_NAME,GCS_BUCKET_NAME=$GCS_BUCKET_NAME,WORKER_URL=$WORKER_URL,TASK_QUEUE_NAME=pdf-worker-queue,REGION=$REGION

BACKEND_URL=$($GCLOUD_PATH run services describe flipbook-api --project=$PROJECT_ID --region $REGION --format 'value(status.url)')
echo "✅ Backend API URL 발급 완료: $BACKEND_URL"

# Then ensure Cloud Tasks Queue exists
echo "----------------------------------------"
echo "🗄️ [2-3/4] Cloud Tasks Queue (pdf-worker-queue) 생성 확인 중..."
echo "----------------------------------------"
$GCLOUD_PATH tasks queues describe pdf-worker-queue --project=$PROJECT_ID --location=$REGION || \
$GCLOUD_PATH tasks queues create pdf-worker-queue --project=$PROJECT_ID --location=$REGION
```
*(Also ensure that downstream uses of `BACKEND_URL` in frontend build are pointing to the `flipbook-api` URL, which is handled by reusing the variable name `BACKEND_URL` in the block above).*

- [ ] **Step 2: Commit**

```bash
git add deploy.sh
git commit -m "chore: split backend deployment into api and worker services"
```
