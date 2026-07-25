# Cloud Run Cold Start 최적화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend Cold Start 시간을 5~10s → 2~4s 로 단축한다. GCP 클라이언트 lazy init, 의존성 슬림화, multi-stage Docker, CPU Boost 4가지를 순서대로 적용한다.

**Architecture:** `database.py`의 GCP 클라이언트를 lazy singleton으로 전환해 임포트 시점 인증 오버헤드를 제거하고, multi-stage Docker build로 build 도구를 runtime 이미지에서 분리한다. requirements.txt에서 불필요한 패키지를 제거해 Python 임포트 시간을 줄이며, Cloud Run `--cpu-boost`로 startup CPU를 일시 증가시킨다.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, Google Cloud Firestore, Google Cloud Storage, Docker multi-stage build, Cloud Run

---

## 변경 파일 목록

| 파일 | 변경 유형 | 책임 |
|------|-----------|------|
| `backend/requirements.txt` | 수정 | 불필요 패키지 제거, fastapi[all] 분리 |
| `backend/Dockerfile` | 재작성 | Multi-stage build |
| `backend/database.py` | 재작성 | Lazy singleton init 패턴 |
| `backend/main.py` | 수정 | lifespan 비동기화, healthcheck 경량화 |
| `backend/pdf_utils.py` | 수정 | pdf2image lazy import |
| `backend/routers/auth.py` | 수정 | db → get_db() |
| `backend/routers/folders.py` | 수정 | db → get_db() |
| `backend/routers/flipbooks.py` | 수정 | db → get_db(), 테스트 mock 경로 반영 |
| `backend/services/flipbook_service.py` | 수정 | db/bucket → get_db()/get_bucket() |
| `backend/tests/test_api_local.py` | 수정 | mock 경로 업데이트 |
| `deploy.sh` | 수정 | --cpu-boost 추가 |

---

## Task 1: requirements.txt 슬림화

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 현재 requirements.txt 확인**

```bash
cat backend/requirements.txt
```

Expected output: `fastapi[all]`, `sqlmodel` 등이 포함되어 있음

- [ ] **Step 2: requirements.txt 교체**

`backend/requirements.txt` 전체를 아래 내용으로 교체한다:

```
fastapi
uvicorn[standard]
python-multipart
email-validator
pdf2image
google-auth
google-auth-oauthlib
google-auth-httplib2
pyOpenSSL
python-dotenv
Pillow
google-cloud-storage
google-cloud-firestore
passlib
bcrypt
aiofiles>=23.2.1

pytest>=8.0.0
requests>=2.31.0
```

주요 변경: `fastapi[all]` → 개별 패키지 명시, `sqlmodel` 제거, `bcrypt==3.2.0` 버전 핀 제거

- [ ] **Step 3: 변경 확인**

```bash
grep -E "sqlmodel|fastapi" backend/requirements.txt
```

Expected: 아무것도 출력되지 않거나 `fastapi` 한 줄만 출력됨 (sqlmodel 없음)

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(deps): slim requirements - remove sqlmodel, split fastapi[all]"
```

---

## Task 2: Dockerfile Multi-stage 재작성

**Files:**
- Modify: `backend/Dockerfile`

- [ ] **Step 1: 현재 Dockerfile 확인**

```bash
cat backend/Dockerfile
```

- [ ] **Step 2: Dockerfile 전체 교체**

`backend/Dockerfile` 전체를 아래 내용으로 교체한다:

```dockerfile
# Stage 1: Builder — bcrypt 등 C 확장 컴파일용 빌드 도구 포함
FROM python:3.11-slim AS builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /install
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Stage 2: Runtime — 런타임 의존성만, build 도구 없음
FROM python:3.11-slim AS runtime
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
WORKDIR /app
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: 로컬 빌드 검증 (Docker 사용 가능한 경우)**

```bash
docker build -t flipbook-backend-test backend/
```

Expected: `Successfully built ...` — Docker가 없는 환경이면 이 스텝은 skip

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile
git commit -m "build(docker): multi-stage build to remove build tools from runtime image"
```

---

## Task 3: database.py Lazy Initialization

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/tests/test_api_local.py` (lazy init 테스트 추가)

- [ ] **Step 1: 테스트 파일에 lazy init 검증 테스트 추가**

`backend/tests/test_api_local.py` 파일 맨 아래에 아래 테스트를 추가한다:

```python
def test_db_lazy_init_state():
    """database 모듈 임포트 후 _db, _bucket이 None이 아닌지 확인 (첫 요청 후 초기화됨)"""
    import database
    # get_db() / get_bucket() 함수가 존재하는지 확인
    assert callable(database.get_db), "get_db 함수가 존재해야 합니다"
    assert callable(database.get_bucket), "get_bucket 함수가 존재해야 합니다"
```

- [ ] **Step 2: 테스트 실행 — 현재 실패 예상 (get_db 미존재)**

```bash
cd /home/admin_/gemini/jjflipbook_test_001
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py::test_db_lazy_init_state -v
```

Expected: `FAILED` — `database` 모듈에 `get_db` 가 없으므로 AttributeError

- [ ] **Step 3: database.py 전체 교체**

`backend/database.py` 전체를 아래 내용으로 교체한다:

```python
import os
import threading
from google.cloud import storage, firestore

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "jjflipbook-gcs-001")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "jwlee-argolis-202104")
FIRESTORE_DB_NAME = os.getenv("FIRESTORE_DB_NAME", "jjflipbook")

_lock = threading.Lock()
_db = None
_bucket = None


def get_db() -> firestore.Client:
    """Firestore 클라이언트를 lazy 초기화하여 반환한다. Thread-safe."""
    global _db
    if _db is None:
        with _lock:
            if _db is None:
                _db = firestore.Client(
                    project=GOOGLE_CLOUD_PROJECT,
                    database=FIRESTORE_DB_NAME
                )
    return _db


def get_bucket() -> storage.Bucket:
    """GCS Bucket을 lazy 초기화하여 반환한다. Thread-safe."""
    global _bucket
    if _bucket is None:
        with _lock:
            if _bucket is None:
                client = storage.Client(project=GOOGLE_CLOUD_PROJECT)
                _bucket = client.bucket(GCS_BUCKET_NAME)
    return _bucket
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py::test_db_lazy_init_state -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_api_local.py
git commit -m "refactor(db): lazy GCP client initialization to reduce cold start"
```

---

## Task 4: main.py 최적화 (Lifespan + Healthcheck)

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 헬스체크 경량화 테스트 작성**

`backend/tests/test_api_local.py`의 `test_local_health_check` 함수를 아래로 교체한다:

```python
def test_local_health_check():
    """1. 헬스체크는 GCP 호출 없이 즉시 200을 반환해야 한다"""
    response = client.get("/")
    assert response.status_code == 200, "API 서버 내부 라우팅 동작 실패"
    data = response.json()
    assert data.get("status") == "ok", "status 필드가 'ok' 여야 합니다"
    assert "services" not in data, "경량화된 헬스체크에 services 항목이 없어야 합니다"
```

- [ ] **Step 2: 테스트 실행 — 현재 실패 예상**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py::test_local_health_check -v
```

Expected: `FAILED` — 현재 응답에 `services` 키가 포함되어 있으므로

- [ ] **Step 3: main.py 전체 교체**

`backend/main.py` 전체를 아래 내용으로 교체한다:

```python
import os
import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from database import get_db
from models import User
from utils import hash_password

from routers import auth, flipbooks, folders

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def _seed_admin():
    """startup 완료 후 백그라운드에서 admin 계정 seeding."""
    import base64
    try:
        user_ref = get_db().collection("users").document("admin")
        if not user_ref.get().exists:
            fallback_pw = base64.b64decode(b"YWRtaW4=").decode("utf-8")
            admin_password = os.getenv("ADMIN_PASSWORD", fallback_pw)
            admin_user = User(
                username="admin",
                password_hash=hash_password(admin_password)
            )
            user_ref.set(admin_user.model_dump())
            logger.info("✅ [Lifespan] Default admin user seeded successfully.")
    except Exception as e:
        logger.warning(f"⚠️ [Lifespan] Admin seeding failed (non-critical): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_seed_admin())
    yield


app = FastAPI(
    title="Flipbook MVP API (Firestore)",
    description="FastAPI Backend mapped for Cloud Firestore",
    version="0.3.0",
    lifespan=lifespan
)

frontend_url = os.getenv("FRONTEND_URL", os.getenv("NEXT_PUBLIC_FRONTEND_URL", "http://localhost:3000"))
allowed_origins = [origin.strip() for origin in frontend_url.split(",")] if frontend_url else ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(flipbooks.router)
app.include_router(folders.router)

STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage")
os.makedirs(STORAGE_DIR, exist_ok=True)
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "message": "Flipbook MVP API is running"
    }
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py::test_local_health_check -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_api_local.py
git commit -m "perf(startup): async admin seeding + lightweight healthcheck"
```

---

## Task 5: routers/auth.py 업데이트

**Files:**
- Modify: `backend/routers/auth.py`

- [ ] **Step 1: auth.py 수정**

`backend/routers/auth.py`의 import 줄과 `db` 사용처를 변경한다:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_db
from utils import verify_password

router = APIRouter(tags=["Auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
def login(req: LoginRequest):
    user_ref = get_db().collection("users").document(req.username)
    doc = user_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=401, detail="존재하지 않는 사용자입니다.")
        
    user_data = doc.to_dict()
    if not verify_password(req.password, user_data.get("password_hash")):
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
        
    return {"status": "ok", "authenticated": True, "username": req.username}
```

- [ ] **Step 2: 로그인 테스트 실행**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py::test_local_login_failure backend/tests/test_api_local.py::test_local_login_success -v
```

Expected: 두 테스트 모두 `PASSED`

- [ ] **Step 3: Commit**

```bash
git add backend/routers/auth.py
git commit -m "refactor(auth): use get_db() lazy accessor"
```

---

## Task 6: routers/folders.py 업데이트

**Files:**
- Modify: `backend/routers/folders.py`

- [ ] **Step 1: folders.py 수정**

`backend/routers/folders.py` 전체를 아래 내용으로 교체한다:

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from models import Folder
from utils import verify_api_key

router = APIRouter(tags=["Folders"])

from services.flipbook_service import delete_single_flipbook

@router.post("/folder")
def create_folder(folder: Folder, validated: bool = Depends(verify_api_key)):
    folder_id = str(uuid.uuid4())
    folder.id = folder_id
    get_db().collection("folders").document(folder_id).set(folder.model_dump())
    return {"status": "ok", "folder_id": folder_id}

@router.get("/folders")
def get_folders():
    docs = get_db().collection("folders").stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results.append(d)
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results

@router.delete("/folder/{folder_id}")
def delete_folder(folder_id: str, validated: bool = Depends(verify_api_key)):
    db = get_db()
    folder_ref = db.collection("folders").document(folder_id)
    if not folder_ref.get().exists:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    flipbooks = db.collection("flipbooks").where("folder_id", "==", folder_id).stream()
    deleted_count = 0
    for fb in flipbooks:
        delete_single_flipbook(fb.id)
        deleted_count += 1
        
    folder_ref.delete()
    return {"status": "ok", "message": f"Folder deleted with {deleted_count} flipbooks cascade deleted."}
```

- [ ] **Step 2: 전체 테스트 실행 (회귀 확인)**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py -v --ignore=backend/tests/test_api_local.py -k "not test_local_pdf_upload"
```

Expected: `PASSED` (pdf_upload는 Task 7에서 처리)

- [ ] **Step 3: Commit**

```bash
git add backend/routers/folders.py
git commit -m "refactor(folders): use get_db() lazy accessor"
```

---

## Task 7: routers/flipbooks.py 업데이트 + 테스트 mock 경로 수정

**Files:**
- Modify: `backend/routers/flipbooks.py`
- Modify: `backend/tests/test_api_local.py`

- [ ] **Step 1: 테스트의 mock 경로 업데이트**

`backend/tests/test_api_local.py`의 `test_local_pdf_upload` 함수를 아래로 교체한다:

```python
from unittest.mock import patch, MagicMock

@patch("routers.flipbooks.process_pdf_task")
@patch("database.get_db")
def test_local_pdf_upload(mock_get_db, mock_process):
    """4. 인메모리 업로드 시나리오 (Firebase 연결 없이 라우팅 통과 여부 검증)"""
    test_pdf_path = os.path.join(os.path.dirname(__file__), "test_data", "sample.pdf")
    assert os.path.exists(test_pdf_path), "Test data missing: sample.pdf"

    # Firestore mock 설정
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_db.collection.return_value.document.return_value.set.return_value = None

    with open(test_pdf_path, "rb") as f:
        files = {"file": ("E2E_TEST_local_test.pdf", f, "application/pdf")}
        headers = {"x-api-key": os.getenv("INTERNAL_API_KEY", "secret_dev_key")}
        response = client.post("/upload", files=files, headers=headers)
        assert response.status_code == 200, f"로컬 업로드 라우터 통과 실패: {response.text}"
        data = response.json()
        assert "book_id" in data
```

- [ ] **Step 2: 테스트 실행 — 현재 실패 예상 (flipbooks.py 아직 미변경)**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py::test_local_pdf_upload -v
```

Expected: `FAILED`

- [ ] **Step 3: flipbooks.py 수정**

`backend/routers/flipbooks.py` 전체를 아래 내용으로 교체한다:

```python
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

    await run_in_threadpool(process_pdf_task, pdf_path, book_dir, book.uuid_key, date_str, split_pages)

    return {
        "status": "ok",
        "message": "PDF uploaded and processed successfully.",
        "book_id": book.uuid_key
    }

@router.get("/flipbooks")
def list_flipbooks():
    docs = get_db().collection("flipbooks").stream()
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
    db = get_db()
    doc_ref = db.collection("flipbooks").document(uuid_key)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Flipbook not found")

    batch = db.batch()

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
    doc_ref = get_db().collection("flipbooks").document(uuid_key)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Flipbook not found")

    delete_single_flipbook(uuid_key)
    return {"status": "ok", "message": "Flipbook deleted successfully"}
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py::test_local_pdf_upload -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/routers/flipbooks.py backend/tests/test_api_local.py
git commit -m "refactor(flipbooks): use get_db() lazy accessor, update test mock path"
```

---

## Task 8: services/flipbook_service.py 업데이트

**Files:**
- Modify: `backend/services/flipbook_service.py`

- [ ] **Step 1: flipbook_service.py 수정**

`backend/services/flipbook_service.py` 전체를 아래 내용으로 교체한다:

```python
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from database import get_db, get_bucket, GCS_BUCKET_NAME

logger = logging.getLogger(__name__)

def delete_single_flipbook(uuid_key: str):
    db = get_db()
    doc_ref = db.collection("flipbooks").document(uuid_key)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return

    book_data = snapshot.to_dict() or {}
    date_str = book_data.get("date_folder", "")

    overlays = doc_ref.collection("overlays").stream()
    batch = db.batch()
    for d in overlays:
        batch.delete(d.reference)
    batch.commit()

    doc_ref.delete()

    try:
        prefix_path = f"flipbooks/{date_str}/{uuid_key}/" if date_str else f"flipbooks/{uuid_key}/"
        blobs = list(get_bucket().list_blobs(prefix=prefix_path))

        if blobs:
            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(lambda b: b.delete(), blobs))

    except Exception as e:
        logger.warning(f"⚠️ [Delete] GCS cleanup failed for book-{uuid_key}: {str(e)}")


def process_pdf_task(pdf_path: str, book_storage: str, uuid_key: str, date_str: str, split_pages: bool = True):
    """백그라운드에서 PDF를 이미지로 변환하고 GCS에 업로드 후 Firestore 업데이트."""
    try:
        from pdf_utils import convert_pdf_to_images
        filenames = convert_pdf_to_images(pdf_path, book_storage, split_pages=split_pages)

        bucket = get_bucket()

        def upload_worker(fname: str):
            local_path = os.path.join(book_storage, fname)
            blob = bucket.blob(f"flipbooks/{date_str}/{uuid_key}/{fname}")
            blob.upload_from_filename(local_path)
            return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/flipbooks/{date_str}/{uuid_key}/{fname}"

        with ThreadPoolExecutor(max_workers=5) as executor:
            uploaded_urls = list(executor.map(upload_worker, filenames))

        pdf_blob_name = f"flipbooks/{date_str}/{uuid_key}/original.pdf" if date_str else f"flipbooks/{uuid_key}/original.pdf"
        pdf_blob = bucket.blob(pdf_blob_name)
        pdf_blob.upload_from_filename(pdf_path)
        pdf_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{pdf_blob_name}"

        get_db().collection("flipbooks").document(uuid_key).update({
            "page_count": len(filenames),
            "image_urls": uploaded_urls,
            "pdf_url": pdf_url,
            "status": "success"
        })
        logger.info(f"✅ [Background] Flipbook-{uuid_key} Firestore Updated successfully. ({len(filenames)} pages)")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ [Background] Error processing PDF-{uuid_key}: {error_msg}", exc_info=True)
        try:
            get_db().collection("flipbooks").document(uuid_key).update({
                "status": "failed",
                "error_message": error_msg
            })
        except Exception as fe:
            logger.error(f"❌ [Background] Failed to update fail status for {uuid_key}: {str(fe)}")
    finally:
        import shutil
        if os.path.exists(book_storage):
            shutil.rmtree(book_storage)
```

주요 변경:
- `from database import db, bucket, GCS_BUCKET_NAME` → `from database import get_db, get_bucket, GCS_BUCKET_NAME`
- `process_pdf_task` 내 `from pdf_utils import convert_pdf_to_images`를 함수 내부로 이동 (lazy import)

- [ ] **Step 2: 전체 테스트 실행**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py -v
```

Expected: 모든 테스트 `PASSED`

- [ ] **Step 3: Commit**

```bash
git add backend/services/flipbook_service.py
git commit -m "refactor(service): use get_db/get_bucket lazy accessors, lazy pdf_utils import"
```

---

## Task 9: pdf_utils.py lazy import

**Files:**
- Modify: `backend/pdf_utils.py`

- [ ] **Step 1: pdf_utils.py 수정**

`backend/pdf_utils.py`의 최상단 import를 함수 내부로 이동한다.

`backend/pdf_utils.py` 전체를 아래 내용으로 교체한다:

```python
import os
import logging

logger = logging.getLogger(__name__)

# macOS M1/M2 등 애플 실리콘 환경 대비 (컨테이너 내에선 PATH 활용)
POPPLER_PATH = "/opt/homebrew/bin" if os.path.exists("/opt/homebrew/bin") else None


def convert_pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 200, split_pages: bool = False) -> list[str]:
    """
    PDF 파일을 불러와 각 페이지를 WebP 이미지로 변환하고 저장합니다.
    진행 완료 시 저장된 파일명 목록을 반환합니다.
    """
    # pdf2image는 실제 변환 시점에만 임포트 (cold start 임포트 오버헤드 제거)
    from pdf2image import convert_from_path, pdfinfo_from_path

    os.makedirs(output_dir, exist_ok=True)

    info = pdfinfo_from_path(pdf_path, poppler_path=POPPLER_PATH)
    total_pages = info["Pages"]

    saved_files = []
    page_count = 1
    chunk_size = 5

    for start in range(1, total_pages + 1, chunk_size):
        end = min(start + chunk_size - 1, total_pages)
        logger.info(f"Processing pages {start} to {end} / {total_pages}...")

        images = convert_from_path(
            pdf_path,
            first_page=start,
            last_page=end,
            dpi=dpi,
            poppler_path=POPPLER_PATH,
            fmt="webp",
            thread_count=os.cpu_count() or 2
        )

        for i, image in enumerate(images):
            width, height = image.size
            if split_pages and width > height:
                left_img = image.crop((0, 0, width // 2, height))
                left_filename = f"page_{page_count}.webp"
                left_img.save(os.path.join(output_dir, left_filename), "WEBP")
                saved_files.append(left_filename)
                page_count += 1

                right_img = image.crop((width // 2, 0, width, height))
                right_filename = f"page_{page_count}.webp"
                right_img.save(os.path.join(output_dir, right_filename), "WEBP")
                saved_files.append(right_filename)
                page_count += 1
            else:
                filename = f"page_{page_count}.webp"
                output_path = os.path.join(output_dir, filename)
                image.save(output_path, "WEBP")
                saved_files.append(filename)
                page_count += 1

        del images

    logger.info(f"Successfully converted {total_pages} sheets to {len(saved_files)} individual pages.")
    return saved_files
```

- [ ] **Step 2: 전체 테스트 재실행 (회귀 확인)**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py -v
```

Expected: 모든 테스트 `PASSED`

- [ ] **Step 3: Commit**

```bash
git add backend/pdf_utils.py
git commit -m "perf(pdf): lazy import pdf2image to skip module-load overhead on cold start"
```

---

## Task 10: deploy.sh CPU Boost 추가

**Files:**
- Modify: `deploy.sh`

- [ ] **Step 1: deploy.sh backend 배포 블록에 --cpu-boost 추가**

`deploy.sh`의 backend `gcloud run deploy` 커맨드에서 `--min-instances=0 \` 바로 위에 `--cpu-boost \`를 추가한다.

변경 전:
```bash
$GCLOUD_PATH run deploy flipbook-backend \
  --project=$PROJECT_ID \
  --image $DOCKER_REPO/flipbook-backend \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --timeout=600 \
  --min-instances=0 \
  --max-instances=3 \
  --concurrency=1 \
```

변경 후:
```bash
$GCLOUD_PATH run deploy flipbook-backend \
  --project=$PROJECT_ID \
  --image $DOCKER_REPO/flipbook-backend \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --timeout=600 \
  --cpu-boost \
  --min-instances=0 \
  --max-instances=3 \
  --concurrency=1 \
```

- [ ] **Step 2: 변경 확인**

```bash
grep "cpu-boost" deploy.sh
```

Expected: `  --cpu-boost \`

- [ ] **Step 3: Commit**

```bash
git add deploy.sh
git commit -m "perf(deploy): add --cpu-boost to backend Cloud Run for faster cold start"
```

---

## Task 11: 최종 통합 검증

- [ ] **Step 1: 전체 테스트 스위트 실행**

```bash
PYTHONPATH=./backend backend/venv/bin/python3 -m pytest backend/tests/test_api_local.py -v
```

Expected 출력:
```
PASSED backend/tests/test_api_local.py::test_local_health_check
PASSED backend/tests/test_api_local.py::test_local_login_failure
PASSED backend/tests/test_api_local.py::test_local_login_success
PASSED backend/tests/test_api_local.py::test_local_pdf_upload
PASSED backend/tests/test_api_local.py::test_db_lazy_init_state
5 passed
```

- [ ] **Step 2: 변경 파일 목록 최종 확인**

```bash
git log --oneline -8
```

Expected: Task 1~10의 커밋 8개가 순서대로 표시됨

- [ ] **Step 3: README 업데이트 (선택)**

`README.md`의 배포 섹션에 cold start 최적화 내용 반영 여부를 사용자에게 확인 후 진행

- [ ] **Step 4: 최종 Commit (필요 시)**

```bash
git add README.md
git commit -m "docs: cold start optimization 적용 내용 README 반영"
```
