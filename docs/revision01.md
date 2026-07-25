# JJFlipBook 코드 및 설정 개선 제안서 (인프라/컴포넌트 추가 없음)

새로운 인프라 컴포넌트 추가(예: JWT 라이브러리 추가 도입, Next.js Middleware 전면 개편 등 큰 아키텍처 변화) 없이, **현재 사용 중인 스택과 라이브러리를 최대한 유지하면서 당장 고칠 수 있는 코드 레벨의 치명적 결함과 로직 최적화**에 초점을 맞추어 도출한 개선점입니다.

---

## 1. 최우선 코드 버그 수정 (High-Priority Fixes)

### 🔴 데이터 모델 불일치로 인한 커버 이미지 로딩 실패 (프론트엔드)
*   **이슈:** 대시보드(`src/app/page.tsx`)는 여전히 이전 SQLite 데이터 모델(`image_paths_json: string`)을 기대하며, `book.id`를 사용하여 GCS URL을 수동으로 조합하고 있습니다. 하지만 백엔드는 Firestore로 마이그레이션되면서 전체 URL 배열인 `image_urls`을 반환합니다. 이로 인해 커버 이미지를 불러오지 못하고 JSON 파싱 에러가 발생합니다.
*   **해결책:** `page.tsx`의 `Flipbook` 인터페이스를 수정하여 `image_urls: string[]`을 기대하도록 변경하고, `coverUrl = book.image_urls?.[0]`와 같이 단순 할당하세요. 기존의 `JSON.parse` 로직은 제거해야 합니다.

### 🔴 운영 환경에서의 하드코딩된 로컬호스트 URL
*   **이슈:** `src/app/edit/[bookId]/page.tsx` 파일 내 `BACKEND_URL`이 `"http://localhost:8000"`으로 하드코딩되어 있습니다. 이는 Cloud Run 운영 환경에서 100% 충돌을 일으킵니다.
*   **해결책:** `page.tsx`에 구현된 것과 동일하게 Next.js API 프록시(`/api/backend/...`)를 일관되게 사용하도록 컴포넌트를 리팩토링하세요.

---

## 2. 백엔드 리소스 누수 및 안정성 (Backend Stability & OOM Risks)

### 🔴 PDF 인메모리 변환 방식 (확정적 OOM 위험)
*   **이슈:** `pdf_utils.py`에서 `pdf2image.convert_from_path`를 호출할 때 페이지 범위를 지정하지 않고 통째로 변환합니다. 이는 변환된 모든 페이지를 동시에 PIL Image 객체로 RAM에 올립니다. 페이지 수가 많은 PDF의 경우 Cloud Run의 2GiB 메모리를 즉시 초과하여 서버가 강제 종료(OOM Killed)됩니다.
*   **해결책:** `first_page`와 `last_page` 파라미터를 사용하여 **청크(Chunk) 단위로 루프를 돌며 변환**해야 합니다. 변환된 청크를 디스크에 저장한 후 바로 메모리에서 해제(Clear)하는 로직이 필요합니다.

### 🔴 파일 업로드 시 메모리 스파이크
*   **이슈:** `main.py`의 `POST /upload` 엔드포인트에서 `await file.read()`를 사용하고 있습니다. 이는 수백 MB에 달할 수 있는 PDF 파일 전체를 RAM에 먼저 올린 뒤 디스크에 씁니다.
*   **해결책:** `shutil.copyfileobj(file.file, f)`를 사용하여 파일을 메모리 버퍼링 없이 즉시 디스크로 스트리밍(Streaming)하여 저장해야 합니다.

### 🔴 예외 발생 시 로컬 파일 시스템(RAM) 누수
*   **이슈:** `main.py`의 `process_pdf_task` 내부를 보면 변환된 임시 파일을 삭제하는 `shutil.rmtree(book_storage)` 코드가 `try` 블록의 맨 마지막에 있습니다. GCS 업로드가 실패하거나 도중에 예외가 발생하면 삭제 로직이 실행되지 않습니다. Cloud Run의 로컬 파일 시스템은 RAM에 마운트되어 있으므로, 이 파일들이 삭제되지 않으면 메모리 누수(Memory Leak)가 발생하여 결국 서버가 다운됩니다.
*   **해결책:** 파일 삭제 로직을 **`finally` 블록으로 이동**시켜 성공/실패 여부와 관계없이 임시 파일이 무조건 삭제되도록 보장해야 합니다.

### 🔴 조용히 무시되는 GCS 업로드 실패 (Silent Failure)
*   **이슈:** `process_pdf_task`에서 스레드 풀을 이용해 `executor.submit(upload_worker, i, fname)`를 호출하지만, 반환된 Future 객체를 기다리거나(await) 결과를 확인하지 않습니다. 즉, 특정 페이지의 스토리지 업로드가 네트워크 에러로 실패해도 백엔드는 이를 모른 채 "완료" 상태로 Firestore를 업데이트해버립니다.
*   **해결책:** 반환된 Future들을 리스트에 모은 후, `.result()`를 호출하여 스레드 내부의 예외를 밖으로 던져(Bubble up) 실패 처리를 명확히 해야 합니다.

### 🔴 Poppler 스레딩 수와 vCPU의 불일치
*   **이슈:** `pdf_utils.py`에는 `thread_count=4`가 하드코딩되어 있습니다. 하지만 `deploy.sh`를 보면 Cloud Run의 CPU 할당량이 명시되어 있지 않아 기본값인 **1 vCPU**로 동작합니다. 1개의 vCPU에서 CPU 집약적인 4개의 프로세스를 돌리면 컨텍스트 스위칭 오버헤드만 발생합니다.
*   **해결책:** `deploy.sh`에 `--cpu=4` 옵션을 추가하여 하드웨어 스펙을 맞추거나, 코드 내에서 `os.cpu_count()`를 사용하여 동적으로 스레드 수를 결정하도록 수정해야 합니다.

### 🔴 백그라운드 작업을 위한 견고한 상태 관리
*   **이슈:** `process_pdf_task`에서 PDF 변환이 실패(예: 손상된 파일)하면 예외는 처리되지만 Firestore는 업데이트되지 않습니다. `page_count`가 계속 `0`으로 남아있기 때문에 프론트엔드는 무한히 폴링(Polling)을 시도하게 됩니다.
*   **해결책:** `except` 블록에 Firestore 문서 상태를 `status: "failed"`로 업데이트하는 로직을 추가하고, 프론트엔드에서 이 상태를 인지하여 폴링을 중지하도록 UI 상태 처리를 추가하세요.

### 🔴 하드코딩된 GCP 변수 분리
*   **이슈:** GCS 버킷 이름과 프로젝트 ID가 `main.py`에 하드코딩되어 있습니다.
*   **해결책:** 배포 스크립트를 통해 주입받을 수 있도록 이를 `os.getenv("GCS_BUCKET_NAME")` 및 `os.getenv("GOOGLE_CLOUD_PROJECT")`로 추출하세요.

### 🔴 데드 코드 제거
*   **이슈:** Firestore 마이그레이션 이전에 사용되었던 `db.py` 파일 내에 사용하지 않는 SQLite 로직이 그대로 남아있습니다.
*   **해결책:** `db.py` 파일을 삭제하세요.

---

## 3. Next.js 프록시 및 프론트엔드 안티 패턴 (Frontend & Proxy Flaws)

### 🔴 프록시 API에서의 이중 메모리 로드 (`route.ts`)
*   **이슈:** `src/app/api/backend/[...path]/route.ts` 파일에서 클라이언트가 보낸 대용량 파일을 백엔드로 전달하기 위해 `await request.formData()`를 사용하여 페이로드 전체를 파싱하고 있습니다. 이는 Next.js 서버(프록시)의 메모리를 극도로 고갈시킵니다.
*   **해결책:** 프록시 서버에서 페이로드를 파싱하지 말고, `fetch(url, { method: 'POST', body: request.body, duplex: 'half', ... })`를 사용하여 클라이언트의 스트림을 그대로 백엔드로 파이핑(Piping) 해야 합니다.

### 🔴 하이드레이션(Hydration) 불일치로 인한 화면 깜빡임 (Flicker)
*   **이슈:** `page.tsx` 등에서 초기 상태를 `isAuthenticated: false`로 두고, `useEffect` 안에서 `localStorage`를 읽어 로그인 상태를 변경합니다. 서버 사이드 렌더링(SSR) 시점에는 무조건 로그인 화면이 그려지고, 클라이언트 마운트 직후 대시보드로 화면이 휙 바뀌는 하이드레이션 에러와 시각적 깜빡임이 발생합니다.
*   **해결책:** 클라이언트 마운트 여부를 추적하는 `isMounted` 상태를 추가하여 마운트 이전에는 렌더링을 지연(`return null`)시키세요.

### 🔴 깨지기 쉬운 프록시 에러 핸들링
*   **이슈:** `route.ts`에서 백엔드의 응답을 무조건 `await res.json()`으로 파싱합니다. 만약 백엔드에서 500 에러가 발생하여 FastAPI의 기본 에러 페이지(HTML)가 반환되면, JSON 파싱 에러가 발생하여 실제 에러가 마스킹(Masking)됩니다.
*   **해결책:** 응답의 `Content-Type`을 확인하여 `application/json`일 때만 파싱하고, 그렇지 않으면 텍스트로 처리하도록 방어 로직을 추가해야 합니다.

### 🔴 Firestore 읽기 비용 절감 (단순 폴링 최적화)
*   **이슈:** 문서 처리 중일 때 `page.tsx`는 3초마다 `/api/backend/flipbooks` 엔드포인트를 폴링합니다. 이는 **전체** 책 목록을 계속해서 불러오기 때문에 불필요한 API 호출을 유발합니다.
*   **해결책:** (웹소켓이나 SSE 도입 없이) 기존의 `setInterval` 로직을 활용하되, 전체 목록 대신 현재 처리 중인 **특정 문서**만 조회(`/api/backend/flipbook/{uuid}`)하도록 API 호출 대상을 변경하세요.
