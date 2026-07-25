[🇺🇸 English Version](./README_EN.md)

# 📖 JJFlipBook - PDF 플립북 뷰어 서비스

PDF 문서를 업로드하여 웹 브라우저에서 실제 책을 넘기는 듯한 **3D 플립북(Page Flip)** 형태로 감상할 수 있는 어플리케이션입니다.

---

## 🏗️ 전체 아키텍처

본 프로젝트는 **Next.js 프론트엔드**와 **FastAPI 백엔드**, 그리고 **Google Cloud 인프라**를 전격 활용하여 탄생한 서버리스 기반 멀티 티어 애플리케이션입니다.

| 계층 (Layer) | 기술 스택 / 활용 |
| :--- | :--- |
| **Frontend** | `Next.js 16+`, `Vanilla CSS`, `react-pageflip` (3D 넘김) |
| **Backend** | `FastAPI (Python 3.11)`, `poppler-utils`, `pdf2image` (PDF 분할 변환) |
| **Database** | `Google Cloud Firestore` (NoSQL - 오버레이 및 메타 영구 보존) |
| **Storage** | `Google Cloud Storage` (변환된 대형 페이지 이미지 저장소 - 날짜별 폴더 구조화) |
| **Compute** | `Google Cloud Run` (단일 통합 컨테이너, CPU Request-based, 동기식 변환 대기) |

> 💡 **참고:** 변환된 이미지가 Google Cloud Storage(GCS)에 업로드된 직후 권한이 전파되는 시간(Propagation Time)을 고려하여, 프론트엔드는 업로드 성공 응답 수신 후 약 5초의 지연(Delay)을 두고 썸네일과 데이터를 로드하도록 최적화되어 있습니다.

---

## 🏃 로컬 구동 방법

로컬 및 오프라인 환경에서 테스트 시 아래 가이드를 상호 참조하여 실행합니다.

### 1. Backend (FastAPI) 기동
```bash
# 1. 백엔드 폴더 이동 및 가상환경 설정
cd backend
python3 -m venv venv
source venv/bin/activate

# 2. 의존성 패키지 설치
pip install -r requirements.txt

# 3. 로컬 가동 (기본 8000 포트)
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
> [!NOTE]  
> 로컬에서 GCS 및 Firestore 연동을 위해서는 사용자 터미널에 `gcloud auth application-default login` 인증 토큰이 필수적입니다.

### 2. Frontend (Next.js) 기동
```bash
# 1. 프론트엔드 폴더 이동
cd frontend

# 2. 패키지 설치 (의존성 충돌 회피를 위한 필수 옵션)
npm install --legacy-peer-deps

# 3. 로컬 가동 (기본 3000 포트)
npm run dev
```

---

## 🚀 Google Cloud Run 원클릭 배포 가이드

본 지면에 포함된 쉘 도구(`deploy.sh`)를 가동하면, Artifact Registry 빌드 및 Cloud Run 자동 교차 주입 배포를 5분 내로 원클릭 가동할 수 있습니다.

```bash
# 워크스페이스 마스터 디렉토리에서 실행
./deploy.sh
```

스크립트 실행 시 타겟 프로젝트 환경 선택 후, 보안 시크릿 3종을 대화형으로 입력받습니다.

```
🔐 보안 환경변수를 입력하세요:
  ADMIN_PASSWORD (관리자 비밀번호): ****
  INTERNAL_API_KEY (내부 API 키):   ****
  SESSION_SECRET (세션 서명 키):    ****
```

> [!WARNING]
> 입력을 생략하면 기본값(`admin`, `secret_dev_key`, `simple-mvp-session-secret-123`)이 사용됩니다. **프로덕션 배포 시에는 반드시 강한 값을 입력하세요.**

### 💡 주요 환경 변수 개요 (`deploy.sh` 가 자동 주입)

| 변수 | 주입 대상 | 설명 |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_BACKEND_URL` | Frontend | 정적 빌드 시 백엔드 엔드포인트를 JS에 구워 넣는 주소 |
| `GCS_BUCKET_NAME` | Backend + Frontend | 이미지 저장 버킷명 (음악 플레이리스트 API도 이 값을 사용) |
| `GOOGLE_CLOUD_PROJECT` | Backend | Cloud Storage 및 Firestore SDK 호출 시 프로젝트 ID |
| `FIRESTORE_DB_NAME` | Backend | Firestore 데이터베이스 인스턴스명 |
| `INTERNAL_API_KEY` | Backend + Frontend | 프론트엔드 → 백엔드 내부 API 호출 인증 키 (양쪽이 동일해야 함) |
| `ADMIN_PASSWORD` | Backend | 초기 관리자 계정 시딩에 사용되는 비밀번호 |
| `SESSION_SECRET` | Frontend | 로그인 세션 쿠키(`auth_token`) 서명 키 |
| `FRONTEND_URL` | Backend | CORS 허용 도메인 (배포 후 Phase 4.5에서 자동 갱신) |

> [!IMPORTANT]
> **Cloud Run 리소스 권장 사항**: PDF 페이지 수가 많거나 해상도가 높을 경우 RAM 소모가 크며 변환(동기 대기) 시간이 길어집니다. 백엔드 안정성을 위해 `--memory=2Gi`, `--timeout=600`, `--concurrency=1`(PDF 변환 OOM 방지)이 설정되어 있습니다. 프론트엔드는 `--memory=1Gi`입니다. 양쪽 모두 `--min-instances=0`으로 **스케일 투 제로**가 보장되어 유휴 비용이 0에 가깝습니다. (Request-based CPU 할당 적용)

---

## 📂 디렉토리 구조도

```text
├── backend/
│   ├── main.py                    # FastAPI 애플리케이션 진입점 및 컨텍스트 초기화
│   ├── database.py                # Firestore/GCS 클라이언트 lazy singleton (get_db/get_bucket)
│   ├── models.py                  # Pydantic NoSQL 데이터 모델
│   ├── utils.py                   # 인증(비밀번호, API 키) 등 공통 유틸리티
│   ├── pdf_utils.py               # poppler 기반 PDF 페이지 렌더링 (5장 청크 처리)
│   ├── routers/                   # 도메인별 API 엔드포인트 (auth, flipbooks, folders)
│   ├── services/
│   │   └── flipbook_service.py    # PDF 처리 및 연쇄 삭제 핵심 비즈니스 로직
│   ├── scripts/
│   │   └── cleanup_test_data.py   # 배포 후 테스트 더미 데이터 자동 정화 스크립트
│   ├── tests/
│   │   └── test_api_local.py      # Pre-flight 오프라인 단위 테스트
│   ├── Dockerfile                 # 백엔드 컨테이너 빌드 가이드
│   └── requirements.txt           # 라이브러리 명세
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx           # 대시보드 (폴더/플립북 목록 관리)
│   │   │   ├── view/[uuidKey]/    # 플립북 뷰어 (3D 페이지 플립)
│   │   │   ├── edit/[bookId]/     # 오버레이 에디터 (링크/영상 영역 지정)
│   │   │   └── api/
│   │   │       ├── backend/       # 백엔드 통합 프록시 (인증 포함)
│   │   │       └── music/         # GCS 기반 BGM 목록 제공 API
│   │   └── components/
│   │       ├── AuthGuard.tsx      # 전역 인증 가드 (레이아웃 래퍼)
│   │       ├── FolderCard.tsx     # 폴더 카드 UI 컴포넌트
│   │       ├── FlipbookCard.tsx   # 플립북 카드 UI (처리중/실패 오버레이 포함)
│   │       ├── ConfirmModal.tsx   # 재사용 삭제 확인 모달 (폴더/문서 공용)
│   │       ├── CreateFolderModal.tsx  # 폴더 생성 모달
│   │       └── MusicPlayer.tsx    # 독립 배경음악 플레이어 컴포넌트
│   ├── Dockerfile                 # standalone Next.js 최적화 빌드
│   └── cloudbuild.yaml            # 빌드 시점 ARG 환경변수 주입 스펙
│
├── deploy.sh                      # Cloud Run 원클릭 배포 자동화 마스터 스크립트
└── gcs-lifecycle.json             # GCS 버킷 Lifecycle 정책 (미완료 업로드 1일 삭제, 고아 객체 365일 삭제)
```

## 🚀 대용량 배포 속도 최적화 (Deployment Optimization)

Cloud Build 환경에서의 빌드/배포 시간을 획기적으로 단축하기 위해 다음과 같은 최적화가 적용되어 있습니다.

### 1. `.gcloudignore` 기반의 업로드 병목 제거
*   **불필요한 로컬 의존성 제외**: 로컬 환경에서 생성된 무거운 폴더들(`frontend/node_modules/` 약 480MB, `frontend/.next/` 약 290MB, `backend/venv/` 약 210MB)이 클라우드로 전송되는 것을 방지합니다.
*   **초고속 업로드**: 약 1GB에 달하던 소스코드 업로드 트래픽을 제거하여, `gcloud builds submit` 명령의 컨텍스트 업로드 시간이 수 분에서 **단 몇 초**로 단축되었습니다.

### 2. 도커 빌드 캐싱 (Docker Layer Caching) 활성화
*   **Kaniko 레이어 캐싱**: `cloudbuild.yaml` 및 `deploy.sh` 내에 `--cache-from` 옵션을 주입하여, `package.json`이나 `requirements.txt`에 변경이 없을 경우 의존성 설치 단계(npm install / pip install)를 완전히 건너뛰도록 캐싱(Layer Caching) 파이프라인을 구축했습니다. **추가적인 1분 이상의 빌드 속도 개선** 효과가 있습니다.

---

## 🚀 대용량 PDF 처리 및 성능/안정성 최적화 (OOM 방지)

대용량 문서 업로드 및 변환 시 서버 과부하 및 메모리 고갈(OOM)을 방지하도록 백엔드와 프론트엔드의 파일 처리 파이프라인을 스트리밍 및 분할 구조로 최신화했습니다.

### 1. 청크 단위 PDF 변환 (Chunked PDF Processing)
*   **메모리 스파이크 차단**: 대형 PDF 전체를 메모리에 로드하지 않고, **5페이지 단위 청크(Chunk)**로 순차 디코딩하여 RAM 점유율을 극도로 낮추었습니다. (`pdf_utils.py`)
*   **렌더링 멀티 프로세스**: `pdf2image` 디코딩 연산자에 `thread_count=os.cpu_count()` 동적 스레드 수를 부여하여 Cloud Run의 실제 vCPU 수에 맞게 자동 최적화됩니다.

### 2. 엔드-투-엔드 스트리밍 업로드 (Streaming Pipeline)
*   **Frontend-Proxy Relay**: Next.js API Routes 에서 페이로드를 전체 버퍼링하지 않고 `Request.body`를 그대로 파이프하는 **Streaming Body Proxy (`duplex: 'half'`)**를 가동하여 대형 파일 중계 부하를 제거했습니다.
*   **스레딩 GCS 동시 업로드**: I/O 바운드 구간을 `ThreadPoolExecutor` 풀 구조로 우회하여 5개의 연동 페이로드가 **동시 다발적 릴레이 전송**을 수행합니다.

### 3. 📂 1-Level 폴더 시스템 및 연쇄 관리 (Cascade Delete)
*   **논리적 트리 결합**: Firestore 메타데이터(`folder_id`) 기반의 1단계 폴더 파티션을 지원하여 업로드된 문서를 관리할 수 있습니다.
*   **물리 분리 아키텍처 보존**: GCS에 저장되는 실제 객체(이미지 Blob)들은 폴더 트리 종속성 없이 개별 UID 생명주기로 관리되어, **빠른 데이터 이동 및 확장성**을 철저히 보장합니다.
*   **연쇄 파기(Cascade Cleanup)**: 대상 폴더 삭제 시 내부에 맵핑된 메인 데이터(Firestore), 오버레이 종속 데이터, GCS 실물 파편 스토리지까지 고아(Orphan) 잔재 없이 완벽히 클린업합니다.
*   **원자적 오버레이 업데이트**: 오버레이 저장 시 기존 데이터 삭제와 신규 데이터 추가를 단일 `batch.commit()`으로 처리하여 중간 실패로 인한 데이터 유실을 방지합니다.

### 4. 확실한 자원 회수 (Resource Cleanup Guarantee)
*   **에러 내성 강화**: 파일 처리 성공 여부와 무관하게 `finally` 블록에서 디렉토리 소거(`shutil.rmtree`)를 강제 마킹하여 임시 스토리지 누수가 원천 차단됩니다.

### 5. 스마트 미디어 & 원본 에셋 보존 (Original PDF & Audio)
*   **원본 PDF 영구 보존**: PDF 업로드 시 이미지로 쪼개질 뿐만 아니라, 뷰어 사용자가 언제든 원본을 다운로드할 수 있도록 원본 `.pdf` 파일 역시 GCS 버킷에 동시 업로드되어 영구 보존됩니다.
*   **직관적인 다운로드 UI**: 플립북 뷰어 하단 컨트롤 바에 'PDF 다운로드 아이콘'이 독립적으로 렌더링되며, 클릭 시 GCS 원본 링크를 통해 원본 파일이 다이렉트로 다운로드됩니다.
*   **배경음악 우회 락해제 (Autoplay Bypass)**: 모바일(iOS Safari 등)의 엄격한 '자동 재생 차단 정책(Autoplay Policy)'을 완벽히 우회하기 위해, 뷰어 화면 어디든 첫 터치(`pointerdown`)가 발생하는 즉시 백그라운드 `.mp3` 오디오의 재생 락을 해제(Unlock)하는 이벤트 리스너를 연동했습니다. (`touchstart`와의 이중 등록 제거 — iOS 첫 탭 이중 소비 방지)

### 6. 다이나믹 Lo-Fi BGM 플레이리스트 자동화 (Dynamic Audio Pipeline)
*   **GCS 기반 분산 오디오 저장소**: Repository 용량 최적화 및 빌드 속도 개선을 위해 150MB가 넘는 수십 개의 배경음악 `.mp3` 파일들을 로컬 폴더(`frontend/public`)가 아닌 **Google Cloud Storage 버킷**으로 전면 분리 이관했습니다.
*   **Next.js 동적 JSON API (`/api/music`)**: 서버사이드 라우팅(Route Handlers)이 GCS의 **REST API를 직접 Fetch 호출**하여 버킷 내의 음악 목록을 실시간으로 스캐닝하고, 퍼블릭 재생 URL 리스트를 동적으로 프론트엔드에 공급합니다. 버킷명은 `GCS_BUCKET_NAME` 환경변수로 주입되어 프로젝트별로 유연하게 대응됩니다. 프론트엔드를 재배포할 필요 없이 GCS에 파일을 추가/삭제하는 것만으로 즉각 플레이리스트가 업데이트됩니다.
*   **독립 컴포넌트**: `MusicPlayer.tsx`가 뷰어 페이지에서 완전히 분리된 독립 컴포넌트로 관리됩니다.

---

## 📊 대시보드 사용성 및 정렬 고도화

사용자 경험과 직관적인 문맥 전달력을 위한 데이터 렌더링 리비전입니다.

*   **최신순 자동 정렬**: 생성일(`created_at`) 타임스탬프를 기준으로 내림차순 렌더 큐를 고정하여 신규 투입된 문서가 상단에 직관 배치됩니다.
*   **업데이트 날짜 시각화**: 카드 피처 뷰 왼쪽 하단에 통일된 연월일 데이트 레이블을 자동 투사하여 문서 히스토리를 강화했습니다.
*   **반응형 모바일 대시보드 레이아웃**: 모바일 접속 시 '새 폴더', 'PDF 업로드', '로그아웃' 등 헤더 및 액션 버튼들이 모바일 폭에 맞추어 유연하게 수직(Column) 정렬/배치되도록 최적화했습니다.
*   **모바일 뷰어(Viewer) 동적 스케일링 및 뷰포트 최적화**: `100dvh` 동적 뷰포트 고정과 상단 기준점(`center top`) 다이나믹 스케일 다운 알고리즘을 적용하여 좁은 스마트폰 화면에서도 책과 하단 UI가 안정적으로 동시 노출됩니다.
*   **Android 페이지 넘김 깜빡임(Flickering) 수정**: `react-pageflip` 라이브러리가 `.stf__parent`에 자동 주입하는 `transform: translateZ(0)` GPU 레이어와, 외부 스케일 Wrapper의 `transform: scale()` GPU 레이어가 Android Chrome에서 이중 합성(Double Compositing) 충돌을 일으키는 것을 확인했습니다. `globals.css`에서 `.is-android` 클래스에만 translateZ 무력화(`none !important`)·perspective 제거·`transform-style: flat` 적용을 스코프하여 Android 전용 GPU 레이어를 통합했습니다. `layout.tsx` 최상단 인라인 스크립트가 `navigator.userAgent`로 Android를 감지해 `<html>`에 `is-android` 클래스를 즉시 부착합니다.
*   **iPhone(iOS Safari) 터치/클릭 불가 수정**: 4가지 원인을 동시에 해결했습니다. ① `mobileScrollSupport={false}` → `true` 변경 — 라이브러리가 `touchstart`에 `preventDefault()` 호출 시 iOS에서 click 이벤트가 전부 소멸되는 문제 해소. ② `globals.css`의 Android GPU 픽스를 `.is-android`로 격리 — `transform-style: flat`이 iOS 제스처 인식을 파괴하던 부작용 제거. ③ 플립북 크기를 `transform: scale()` Wrapper 대신 `bookWidth`/`bookHeight`를 직접 계산해 props로 전달 — CSS 스케일 변환에 의한 iOS 터치 좌표 불일치 방지. ④ `button, a { touch-action: manipulation }` 전역 적용 — iOS 300ms 탭 딜레이 제거.
*   **컴포넌트 분리**: `FolderCard`, `FlipbookCard`, `ConfirmModal`, `CreateFolderModal` 등 UI 요소가 독립 컴포넌트로 분리되어 유지보수성이 향상되었습니다.

---

## 🔒 Direct VPC 내부망 설계 및 망분리 (Security)

### 1. Direct VPC Egress & Next.js API Routes Proxy
인프라 보호를 위해 외부의 직접적인 연결을 차단하는 폐쇄 통신망으로 설계되었습니다.
*   **Proxy Relay**: 브라우저 클라이언트가 백엔드 API를 직접 호출하지 않고, Next.js 프론트엔드 서버가 연산을 Proxy로 대리 수행합니다. (`/api/backend/*`)
*   **Internal Ingress**: 백엔드(FastAPI)는 `--ingress=internal` 정책으로 구동되어 외부 공용 인터넷의 진입점을 완전히 차단합니다.
*   **Direct VPC Egress**: 프론트엔드와 백엔드 모두 동일한 사설망(`jwlee-vpc-001`) 내에 배포되어 트래픽이 VPC 외부로 유출되지 않고 안전하게 내재됩니다.

### 2. Private DNS를 통한 완전한 네이티브 라우팅
*   VPC 내부에 구글 서비스(`run.app`)에 대한 **Private DNS Zone**이 구성되어 있습니다.
*   두 Cloud Run 서비스 간의 모든 통신은 외부 NAT IP를 경유하지 않으며, 오로지 구글의 내부 사설망인 Private Google Access VIP(`199.36.153.8`)만을 거쳐 빠르고 안전하게 동작합니다.

### 3. 보안 강화 및 CORS (Cross-Origin Resource Sharing) 제한
*   **프론트엔드 도메인 화이트리스트 검증**: 모든 출처(`*`)를 허용하던 기존 방식에서 탈피하여 환경 변수로 주입된 지정된 `FRONTEND_URL` 도메인만 API와 통신할 수 있도록 CORS 미들웨어 구성을 엄격하게 수정했습니다.

---

## 🔑 관리자 인증 시스템 (Authentication)

보안과 전용 세션 관리를 위해 설계된 고도화 로그인 아키텍처입니다.

*   **전역 AuthGuard 통합**: `layout.tsx`에서 `AuthGuard` 컴포넌트가 모든 페이지를 래핑하여 인증을 일원화합니다. `/view/*` 경로만 공개 접근을 허용하며, 나머지(`/`, `/edit/*` 등)는 로그인이 필요합니다.
*   **HttpOnly 쿠키 세션**: 로그인 성공 시 `SESSION_SECRET`으로 서명된 값을 `HttpOnly` 쿠키에 저장하여 XSS 기반 세션 탈취를 차단합니다.
*   **내부 API 키 인증**: 업로드, 삭제 등 쓰기 작업은 `INTERNAL_API_KEY`로 백엔드에서 재검증됩니다. 프론트엔드와 백엔드의 키가 반드시 일치해야 하며, `deploy.sh`가 동일한 값을 양쪽 서비스에 자동 주입합니다.
*   **패스워드 암호화**: Python 네이티브 `bcrypt` 해싱 엔진으로 관리자 비밀번호를 보호합니다.
*   **시크릿 프롬프트 입력**: `deploy.sh` 실행 시 `ADMIN_PASSWORD`, `INTERNAL_API_KEY`, `SESSION_SECRET` 세 값을 대화형으로 입력받아 Cloud Run 환경변수에 주입합니다. 스크립트 코드에 시크릿이 하드코딩되지 않습니다.

---

## 🛠️ 클라이언트 렌더링 (React/Next.js) 안정성 강화

*   **SSR Hydration 오류 완벽 제어**: DOM을 직접 수정하는 전역 CSS Injection 코드나 윈도우 사이즈 측정(Resize) 로직 등을 `useEffect` 내부 영역으로 철저히 격리하여, Next.js 구동 시 즉발하던 런타임 크래시를 방어했습니다.
*   **타입 안전성 강화**: 모든 컴포넌트에서 `any` 타입을 제거하고 `FlipbookData`, `Overlay`, `Folder` 등 명시적 인터페이스를 정의했습니다.
*   **병렬 폴링 처리**: 변환 중인 플립북이 여러 개일 때 순차 요청 대신 `Promise.all`로 동시 조회하여 폴링 응답 시간을 단축했습니다.
*   **지수 백오프 자동 폴링**: `status: "failed"` 방어 로직과 함께 스마트 폴링 엔진을 도입하여 데이터베이스 호출 비용(Quota)을 획기적으로 낮췄습니다.
*   **불변성 패턴 적용**: 상태 업데이트 시 `prev => prev.map(...)` 등 불변성 패턴을 일관되게 적용하여 예측 불가능한 사이드이펙트를 차단합니다.
*   **Next.js API Route 정적 캐싱 무력화**: `export const dynamic = 'force-dynamic'` 및 `cache: 'no-store'` 정책을 API 프록시에 고정 주입하여 실시간 데이터베이스 Fetching을 확정했습니다.

---

## ☁️ Google Cloud 배포 구조도 (Architecture)

```mermaid
graph TD
    User([사용자 / 웹 브라우저]) -->|1. HTTPS 접속| FE_Run["Frontend (Next.js) <br> Cloud Run"];
    
    subgraph VPC ["VPC 사설망 (Direct VPC Egress)"]
        FE_Run -->|2. Proxy API 중계| BE_Run["Backend (FastAPI) <br> Cloud Run <br> (Ingress: Internal)"];
    end
    
    subgraph Google Cloud Platform
        BE_Run -->|3. PDF 이미지 분할| Poppler["Poppler-utils <br> (컨테이너 내장)"];
        BE_Run -->|4. 원본 / 변환 저장| GCS[("Cloud Storage <br> 이미지 버킷")];
        BE_Run -->|5. 메타데이터 저장| Firestore[("Cloud Firestore <br> NoSQL DB")];
        
        GCS -.->|6. 이미지 다이렉트 로딩| User;
    end

    style FE_Run fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px
    style BE_Run fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px
    style GCS fill:#e6f4ea,stroke:#1e8e3e,stroke-width:2px
    style Firestore fill:#e6f4ea,stroke:#1e8e3e,stroke-width:2px
```

---

## 🧪 Shift-Left TDD 및 자동화 배포 파이프라인 (CI/CD)

클라우드 자원 낭비를 막고 안전한 서버 코드를 릴리즈하기 위해, `deploy.sh`에 **Shift-Left TDD** 원칙을 반영한 양방향 다단계 파이프라인이 탑재되었습니다.

### 1. 배포 전 오프라인 방어 (Phase 0: Pre-Flight Checks)
*   **백엔드 단위 테스트 차단막 (Mocking)**: 로컬 Python 환경(`pytest`)에서 FastAPI 라우팅을 검사하되, Cloud Storage 업로드나 Firestore 트랜잭션을 **Mocking 객체로 우회 차단**하여 로컬 환경에서의 쓰레기 데이터 생성을 근본적으로 막았습니다.
*   **프론트엔드 다층 방어막 (Frontend TDD)**: 배포 직전 4중 검증 체계를 강제합니다.
    *   **[2-1] TypeScript 정적 타입 검사 (`tsc`)**: 런타임에 뻗을 수 있는 타입 충돌을 Build 전 단계에서 솎아냅니다.
    *   **[2-2] 코드 스멜 및 품질 제한 (`eslint`)**: 코드 품질을 자동 심사합니다.
    *   **[2-3] 로컬 UI 컴포넌트 유닛 테스트 (`Jest`)**: `AuthGuard.test.tsx` 등 컴포넌트 렌더링 테스트를 통과해야만 다음 단계로 진행합니다.
    *   **[2-4] Next.js SSR 정적 빌드 검증 (`npm run build`)**: 빌드 오류가 있는 코드가 Cloud Build에 올라가는 것을 사전 차단합니다.
*   **gcloud 자동 탐색**: `PATH`에서 `gcloud`를 먼저 탐색하고, 없을 때만 절대경로 fallback을 시도합니다. 실행 불가 시 명확한 오류 메시지를 출력하고 중단합니다.

### 2. 배포 후 자동 정화 (Phase 5: G.C Teardown)
*   **찌꺼기 일괄 소각 (Cleanup)**: 과거 수동 테스트 혹은 단위 테스트로 인해 생성되었을 수 있는 찌꺼기 PDF 객체들을 막기 위해, 배포의 가장 마지막 단계(Phase 5)에서 **`backend/scripts/cleanup_test_data.py`** 가 자동 실행됩니다. 명시된 테스트 더미들을 Cloud Storage 블롭 단위부터 Firestore 메타데이터까지 일괄 색인하여 제거하고 파이프라인을 온전하게 종료시킵니다.

---

## 💰 GCP 비용 최적화 (Zero-Waste)

가끔씩 사용하는 소규모 패턴에서 유휴 비용을 0에 가깝게 만들기 위해 아키텍처 변경 없이 설정 수정만으로 최적화합니다.

### Cloud Run 스케일 투 제로 설정

| 서비스 | 옵션 | 값 | 근거 |
| :--- | :--- | :--- | :--- |
| **Backend** | `--min-instances` | `0` | 트래픽 없을 때 인스턴스 0개로 스케일 투 제로 |
| **Backend** | `--max-instances` | `3` | 동시 PDF 변환 최대 3개 제한, 폭주 요금 방지 |
| **Backend** | `--concurrency` | `1` | 인스턴스당 PDF 변환 요청 1개만 처리 (OOM 방지) |
| **Backend** | `--memory` | `2Gi` | PDF 변환에 필요한 최소 사양 유지 |
| **Backend** | `--cpu-boost` | (설정) | 컨테이너 기동 중 CPU 임시 증가 → cold start 가속 |
| **Frontend** | `--min-instances` | `0` | 스케일 투 제로 명시 보장 |
| **Frontend** | `--max-instances` | `5` | 소규모 트래픽 상한 설정, 폭주 방지 |
| **Frontend** | `--memory` | `1Gi` | Next.js 16 standalone + sharp 모듈 OOM 방지 |

> cold start 최적화 적용 후 **약 5~10초 → 2~4초** 수준으로 단축됩니다. (아래 섹션 참고)

### Cloud Run Cold Start 최적화 (4-Layer)

`--min-instances=0` 유지(비용 제로) 하에 cold start를 단축하는 4가지 레이어가 적용되어 있습니다.

| 레이어 | 적용 내용 | 단축 효과 |
| :--- | :--- | :--- |
| **CPU Boost** | `--cpu-boost` — 기동 중 CPU 임시 증가, idle 비용 없음 | startup 전반 가속 |
| **Multi-stage Docker** | builder(gcc 포함) / runtime(poppler만) 이미지 분리 → 이미지 크기 감소 | ~0.5~1s |
| **Lazy GCP 클라이언트** | `database.py`: `get_db()` / `get_bucket()` lazy singleton — 모듈 임포트 시 GCP 인증 없음 | ~1~3s (최대 효과) |
| **Startup 로직 경량화** | admin seeding → `asyncio.create_task` 백그라운드 실행 / 헬스체크(`/`) GCP 호출 제거 | ~0.5~1s |

> `pdf2image` 임포트도 PDF 변환 호출 시점으로 지연되어(lazy import) cold start 시 불필요한 모듈 로드가 없습니다.

### 백엔드 API 응답 최적화 (4항목)

| 항목 | 변경 내용 | 효과 |
| :--- | :--- | :--- |
| **GZip 압축** | `GZipMiddleware` 추가 (1KB 이상 응답 자동 압축) | JSON 응답 크기 ~60% 감소 |
| **Firestore 쿼리 제한** | `list_flipbooks`: 전체 스캔 → `order_by("created_at").limit(50)` | 무제한 스캔 방지, 비용 절감, 최신순 정렬 |
| **Firestore 이중 읽기 제거** | 삭제 엔드포인트: 존재 확인 + 데이터 조회 2회 → 1회로 통합, `date_str` 서비스로 전달 | Firestore 읽기 1회 절감 |
| **PDF 변환 파라미터화** | DPI `200→150` (환경변수 `PDF_DPI`), WebP quality `75` (환경변수 `WEBP_QUALITY`) | 이미지 파일 크기 ~40% 감소, 변환 속도 향상 |

> 💡 필요시 `deploy.sh`의 `--set-env-vars`에 `PDF_DPI=200,WEBP_QUALITY=85` 등을 추가하여 품질을 조정할 수 있습니다.

### GCS Lifecycle 정책 (`gcs-lifecycle.json`)

배포(`deploy.sh` Phase 0.5)마다 GCS 버킷에 자동 적용됩니다.

| 규칙 | 조건 | 목적 |
| :--- | :--- | :--- |
| `AbortIncompleteMultipartUpload` | age ≥ 1일 | 업로드 중단 시 남은 임시 데이터 자동 삭제 |
| `Delete` | age ≥ 365일 | GCS 정리 실패로 누적된 고아(Orphan) 이미지 안전망 제거 |
