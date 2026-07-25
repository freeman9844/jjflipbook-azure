# 📖 JJFlipBook — PDF 플립북 뷰어 서비스 (Azure Edition)

PDF 문서를 업로드하여 웹 브라우저에서 실제 책을 넘기는 듯한 **3D 플립북(Page Flip)** 형태로 감상할 수 있는 애플리케이션입니다.

> 이 저장소는 [jjflipbook_test_001](https://github.com/freeman9844/jjflipbook_test_001)(GCP 기반)을
> **Microsoft Azure**로 마이그레이션한 버전입니다.

## 아키텍처

| 계층 | 기술 스택 |
| --- | --- |
| **Frontend** | Next.js (standalone), react-pageflip — **Azure Container Apps** |
| **Backend** | FastAPI (Python 3.11), poppler-utils, pdf2image — **Azure Container Apps** |
| **Database** | **Azure Cosmos DB for NoSQL** (Serverless) — `users` / `folders` / `flipbooks` / `overlays` |
| **Storage** | **Azure Blob Storage** 프라이빗 컨테이너 `flipbook-assets` (페이지 이미지 · PDF · `bgm/` MP3) — SAS URL로 접근 |
| **Registry / 배포** | **ACR + azd (Azure Developer CLI) + Bicep** 원클릭 |
| **인증(서비스 간)** | Managed Identity (Cosmos Data Contributor, Storage Blob Data Contributor) |

- 컨테이너 양쪽 모두 `minReplicas: 0` — **스케일 투 제로**로 유휴 비용 최소화
- 백엔드는 PDF 변환 OOM 방지를 위해 동시 요청 1개로 스케일 (`concurrentRequests: 1`)
- Cosmos DB Serverless + Blob LRS — 사용량 기반 과금

## 🚀 원클릭 배포 (azd)

사전 준비: [azd 설치](https://aka.ms/azd), `az login`

```bash
azd auth login
azd init   # 기존 환경이 없다면 환경 이름/구독/리전 선택

# 보안 시크릿 3종 설정 (미설정 시 프로비저닝 실패)
azd env set ADMIN_PASSWORD '<관리자 비밀번호>'
azd env set INTERNAL_API_KEY '<내부 API 키>'
azd env set SESSION_SECRET '<세션 서명 키>'

azd up     # 인프라 프로비저닝 + 빌드 + 배포
```

`azd up` 완료 후 출력되는 `FRONTEND_URL`로 접속합니다. (최초 관리자 계정: `admin` / 설정한 `ADMIN_PASSWORD`)

### 환경 변수

| 변수 | 주입 대상 | 설명 |
| --- | --- | --- |
| `COSMOS_ENDPOINT` / `COSMOS_DB_NAME` | Backend | Cosmos DB 엔드포인트 / DB 이름(`jjflipbook`) |
| `STORAGE_ACCOUNT_NAME` / `BLOB_CONTAINER_NAME` | Backend | Blob 계정 / 컨테이너(`flipbook-assets`) |
| `NEXT_PUBLIC_BACKEND_URL` | Frontend (빌드 ARG) | 백엔드 엔드포인트 (정적 JS에 반영) |
| `INTERNAL_API_KEY` | Backend + Frontend | FE → BE 내부 API 인증 키 (양쪽 동일) |
| `ADMIN_PASSWORD` | Backend | 초기 관리자 계정 시딩 비밀번호 |
| `SESSION_SECRET` | Frontend | 로그인 세션 쿠키(`auth_token`) 서명 키 |
| `FRONTEND_URL` | Backend | CORS 허용 도메인 (Bicep이 자동 계산) |

## 로컬 개발

로컬에서 Cosmos/Blob 연동에는 `az login` 토큰이 사용됩니다 (`DefaultAzureCredential`).
배포된 리소스의 값으로 `COSMOS_ENDPOINT`, `STORAGE_ACCOUNT_NAME` 환경변수를 설정하세요.

```bash
# Backend (기본 8000 포트)
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend (기본 3000 포트)
cd frontend
npm install --legacy-peer-deps
npm run dev
```

## 테스트

```bash
# Backend 오프라인 단위 테스트 (Azure 연결 불필요 — mock 기반)
cd backend && ./venv/bin/python -m pytest tests/ -v

# Frontend 단위 테스트
cd frontend && npx jest
```

## 알려진 제약

- **긴 PDF 변환**: 업로드 요청이 변환을 동기 대기합니다. Container Apps ingress의
  요청 타임아웃(약 240초)을 초과하는 대형 PDF는 클라이언트에서 타임아웃될 수 있습니다.
  (Cosmos에는 `processing` 상태로 남으며, 변환은 서버에서 계속 진행됩니다.)
- **BGM 목록**: `flipbook-assets` 컨테이너의 `bgm/` 경로에 MP3를 업로드하면
  뮤직 플레이어 목록에 자동 노출됩니다. 백엔드 `/music/list` 엔드포인트가 user-delegation SAS URL을 생성하여 반환합니다 (컨테이너 공개 접근 불필요).
- GCP 시절 설계/플랜 문서는 `docs/` 아래에 참고용으로 보존되어 있습니다.
