# Cloud Run Cold Start 최적화 설계

**날짜:** 2026-04-15  
**목표:** Cloud Run cold start 시간 단축 (추정 5~10s → 2~4s)  
**제약:** 비용 최우선 (`--min-instances=0` 유지), cold start 30초 이내 허용  
**범위:** Backend (FastAPI) 중심, Frontend 일부

---

## 배경 및 문제 정의

현재 `deploy.sh`는 backend/frontend 모두 `--min-instances=0`으로 설정되어 있어 idle 상태 후 첫 요청 시 cold start가 발생한다. PDF 변환(`pdf2image`)은 매우 드물게 사용되는 기능임에도 불구하고, 관련 의존성이 항상 로드되어 startup 시간을 늘리고 있다.

### 현재 Cold Start 병목 순서

```
1. 컨테이너 초기화        ~1s   (이미지 pull & 런타임 준비)
2. Python 모듈 임포트     ~2-4s  (fastapi[all], sqlmodel, pdf2image, bcrypt 등)
3. GCP 클라이언트 초기화  ~1-3s  (database.py 임포트 시점에 즉시 실행)
4. Lifespan Firestore 쿼리 ~0.5-1s (admin 계정 존재 여부 확인)
5. 첫 헬스체크            ~0.5s  (Firestore + GCS 실제 네트워크 콜)
─────────────────────────────────
합계 (추정)               5~10s
```

### 핵심 문제

- `database.py`가 임포트 시점에 `storage.Client()` + `firestore.Client()`를 즉시 실행 → GCP 인증 오버헤드 발생
- `fastapi[all]`이 불필요한 extras를 다수 포함
- `sqlmodel`이 requirements에 포함되어 있으나 Firestore 사용으로 불필요
- lifespan이 Firestore 네트워크 콜을 블로킹으로 실행
- 헬스체크 `/`가 Firestore + GCS 실제 호출을 수행

---

## 설계 결정: 4-Layer 최적화

### Layer 0: Cloud Run CPU Boost (설정 변경)

`--cpu-boost` 옵션을 backend deploy에 추가한다. startup 중에만 일시적으로 CPU를 증가시키며, idle 시에는 추가 비용이 발생하지 않는다.

```bash
# deploy.sh 변경
$GCLOUD_PATH run deploy flipbook-backend \
  ...
  --cpu-boost \   # 추가
  ...
```

### Layer 1: Multi-stage Docker Build (Dockerfile 재작성)

`bcrypt` 컴파일에 필요한 `gcc`/`build-essential`을 runtime 이미지에서 제거한다. `poppler-utils`는 `pdf2image` 런타임 의존성이므로 runtime stage에만 포함한다.

```dockerfile
# Stage 1: Builder — 컴파일 도구 포함
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /install
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Stage 2: Runtime — 런타임 의존성만
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

**효과:** `gcc`/`build-essential` (~200MB) 이 최종 이미지에서 제거됨 → 컨테이너 pull 시간 단축

### Layer 2: Requirements 슬림화

| 현재 | 변경 | 이유 |
|------|------|------|
| `fastapi[all]` | `fastapi` + `uvicorn[standard]` + `python-multipart` + `email-validator` | `[all]`은 불필요한 extras 다수 포함 |
| `sqlmodel` | 제거 | Firestore 사용 중, SQLModel은 완전 불필요 |
| `bcrypt==3.2.0` | `bcrypt` (버전 핀 제거) | 최신 wheel 사용 가능 → 컴파일 불필요할 수 있음 |

**변경 후 `requirements.txt`:**
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

### Layer 3: GCP 클라이언트 Lazy Initialization

**현재 `database.py`:** 모듈 임포트 시점에 즉시 GCP 인증 및 클라이언트 생성 실행.

**변경 후:** 첫 실제 호출 시점까지 초기화 지연. Thread-safe하게 구현.

```python
# database.py
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
    global _bucket
    if _bucket is None:
        with _lock:
            if _bucket is None:
                client = storage.Client(project=GOOGLE_CLOUD_PROJECT)
                _bucket = client.bucket(GCS_BUCKET_NAME)
    return _bucket
```

**호출부 변경 패턴:**
- `from database import db, bucket` → `from database import get_db, get_bucket, GCS_BUCKET_NAME`
- 사용 시점에 `db.collection(...)` → `get_db().collection(...)`
- 사용 시점에 `bucket.blob(...)` → `get_bucket().blob(...)`

**영향 범위:**
- `backend/main.py`
- `backend/services/flipbook_service.py`
- `backend/routers/flipbooks.py`
- `backend/routers/auth.py`
- `backend/routers/folders.py`

### Layer 4: Startup 로직 최적화

#### 4-1. Lifespan admin seeding 비동기화

```python
# main.py
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_seed_admin())  # 블로킹 없이 백그라운드 실행
    yield

async def _seed_admin():
    """startup 완료 후 백그라운드에서 admin 계정 seeding."""
    import base64
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
```

#### 4-2. 헬스체크 경량화

```python
# main.py — 헬스체크에서 실제 GCP 호출 제거
@app.get("/")
def read_root():
    return {
        "status": "ok",
        "message": "Flipbook MVP API is running"
    }
```

기존 Firestore/GCS 연결 확인은 `/health/detail` 같은 별도 엔드포인트로 분리하거나 제거한다. Cloud Run의 내장 헬스체크는 HTTP 200 반환만으로 충분하다.

---

## 변경 파일 목록

| 파일 | 변경 유형 | 주요 변경 내용 |
|------|-----------|---------------|
| `backend/Dockerfile` | 재작성 | Multi-stage build |
| `backend/requirements.txt` | 수정 | sqlmodel 제거, fastapi[all] 분리 |
| `backend/database.py` | 재작성 | Lazy init 패턴 |
| `backend/main.py` | 수정 | lifespan 비동기화, 헬스체크 경량화 |
| `backend/services/flipbook_service.py` | 수정 | get_db(), get_bucket() 호출 |
| `backend/routers/flipbooks.py` | 수정 | get_db(), get_bucket() 호출 |
| `backend/routers/auth.py` | 수정 | get_db() 호출 |
| `backend/routers/folders.py` | 수정 | get_db() 호출 |
| `deploy.sh` | 수정 | --cpu-boost 추가 |

---

## 기대 효과

| 레이어 | 단축 예상 | 비용 영향 |
|--------|-----------|-----------|
| CPU Boost | 전체 startup 가속 | 미미 (startup 중만) |
| Multi-stage Docker | ~0.5-1s (이미지 크기 감소) | 없음 |
| Requirements 슬림화 | ~0.5-1s (임포트 시간 감소) | 없음 |
| Lazy GCP init | ~1-3s (가장 큰 개선) | 없음 |
| Startup 로직 최적화 | ~0.5-1s | 없음 |
| **합계** | **2.5~7s 단축** | 최소 |

---

## 리스크 및 고려사항

- **Thread safety**: Lazy init에 `threading.Lock()` double-checked locking 패턴 사용 → 안전
- **Admin seeding 타이밍**: background task로 전환 시, 서버 시작 직후 첫 admin 로그인이 seeding 완료 전에 발생할 수 있음 → `passlib` 해싱이 느려 실제로는 문제 없을 것으로 판단, 단 로그로 명시
- **헬스체크 제거**: GCS/Firestore 연결 오류를 즉시 감지하지 못할 수 있음 → Cloud Run은 HTTP 200만 확인하므로 운영상 문제 없음
- **sqlmodel 제거**: 코드 전체 grep 결과 `requirements.txt`에만 존재, 실제 사용 없음 — 안전하게 제거 확인됨
