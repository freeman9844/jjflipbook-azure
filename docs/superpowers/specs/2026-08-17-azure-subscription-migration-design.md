# JJFlipBook Azure 구독 이전 설계

- 날짜: 2026-08-17
- 원본 구독: `8dd0dabf-d8c0-4651-a846-5b13e18e05eb`
- 대상 구독: `43ab425a-c793-4f2e-b71a-0af7a14f26d2`
- Tenant: `1716e63d-ed31-49bf-aa16-5effd27bc340`
- 지역: `koreacentral`
- 환경/RG: `jjflipbook-p2` / `rg-jjflipbook-p2`
- 방식: 병렬 재구축, 데이터 복사, 검증 후 원본 즉시 삭제

## 1. 목표와 성공 조건

현재 운영 중인 JJFlipBook 환경 전체를 동일 Tenant의 새 Azure 구독에 재구축하고,
Blob Storage와 Cosmos DB 데이터를 복사한 뒤 GitHub Actions 배포 대상을 전환한다.
Container Apps는 구독 간 직접 이동하지 않으며, 저장소의 Bicep을 사용해 새 환경을 만든다.

이전은 다음 조건을 모두 만족해야 성공으로 간주한다.

1. 대상 구독에 현재 Bicep과 동일한 논리 구성이 배포된다.
2. Blob과 Cosmos 데이터의 검증 결과가 원본과 일치한다.
3. Cosmos의 Blob URL 참조가 대상 Storage Account를 가리킨다.
4. Backend와 Frontend가 정확한 Git commit SHA 이미지의 단일 Healthy 리비전으로 수렴한다.
5. 로그인, 목록, PDF 업로드·조회·삭제 smoke test가 통과한다.
6. KEDA 규칙, Managed Identity, 데이터 평면 RBAC, 로그 상태가 정상이다.
7. GitHub Actions의 Preview와 전체 배포가 대상 구독에서 성공한다.
8. 모든 검증 후 원본 리소스 그룹을 삭제하고 원본 구독의 OIDC 역할을 회수한다.

## 2. 범위

### 포함

- Container Apps Environment, Backend/Frontend Container Apps
- Cosmos DB 계정, `jjflipbook` 데이터베이스와 4개 컨테이너
- Storage Account와 `flipbook-assets` Blob 컨테이너
- Log Analytics, Application Insights
- Backend 전용 User Assigned Managed Identity와 RBAC
- KEDA HTTP 및 `daily-warm-window` 규칙
- GitHub Actions OIDC 권한과 저장소 변수
- Blob/Cosmos 데이터 복사, 정합성 검증, 운영 전환
- 원본 `rg-jjflipbook-p2` 삭제와 원본 구독 권한 정리
- README 및 `.azure/deployment-plan.md`의 운영 대상 갱신

### 제외

- Azure Resource Mover 또는 ARM Move를 이용한 혼합 이전
- 애플리케이션 기능, 데이터 모델, KEDA 시간표 변경
- 커스텀 도메인 또는 Front Door 신규 도입
- 무중단 전환 보장
- 원본 리소스 그룹의 전환 후 보존

## 3. 대상 아키텍처

대상 구독에서 `infra/main.bicep`을 구독 범위로 실행해
`rg-jjflipbook-p2`와 모든 하위 리소스를 새로 만든다. 환경명과 리소스 그룹명은
원본과 같지만 구독이 다르므로 충돌하지 않는다. Storage, Cosmos DB, Container Apps
등 전역 고유 이름이 필요한 리소스는 대상 구독을 기반으로 생성되는 새 resource token을
사용하므로 물리 이름과 공개 URL은 달라진다.

애플리케이션 구조는 변경하지 않는다.

```text
Browser
  -> Target Frontend Container App
       -> Target Backend Container App
            -> Target Cosmos DB
            -> Target Blob Storage
```

대상 Backend는 새 User Assigned Managed Identity만 사용한다. 이 Identity에는 대상
Storage의 `Storage Blob Data Contributor`와 대상 Cosmos DB의
`Cosmos DB Built-in Data Contributor`만 부여한다. Cosmos DB의
`disableLocalAuth: true` 정책은 유지하며 키 기반 접근을 열지 않는다.

커스텀 도메인이 없으므로 전환 후 사용자는 대상 Frontend의 새 Container Apps URL을
사용한다. 원본 URL을 유지하는 것은 이번 범위에 포함하지 않는다.

## 4. 사전 준비와 권한

대상 구독에서 다음 Resource Provider를 등록하고 등록 완료를 확인한다.

- `Microsoft.App`
- `Microsoft.DocumentDB`
- `Microsoft.ManagedIdentity`
- `Microsoft.OperationalInsights`
- `Microsoft.Storage`

Korea Central에서 필요한 리소스 생성과 Container Apps 용량을 확인한 후 Bicep
Preview를 실행한다. Preview에서 예상하지 않은 삭제 또는 교체가 보이면 배포하지 않는다.

기존 GitHub OIDC App Registration `jjflipbook-azure-github-p2`를 재사용한다.
대상 구독 범위에 현재 배포에 필요한 `Contributor`와
`Role Based Access Control Administrator`를 부여한다. 새 client secret은 만들지 않는다.

데이터 복사 실행 주체에는 원본과 대상 리소스 범위에서만 임시 데이터 평면 역할을 부여한다.

- 양쪽 Storage Account: `Storage Blob Data Contributor`
- 양쪽 Cosmos DB 계정: `Cosmos DB Built-in Data Contributor`

복사와 검증이 끝나면 이 임시 역할은 회수한다.

## 5. 배포와 데이터 이전 흐름

### 5.1 대상 환경 생성

1. `AZURE_SUBSCRIPTION_ID`를 대상 구독으로 설정한 격리된 AZD 실행 컨텍스트에서
   `azd provision --preview`를 실행한다.
2. Preview 승인 후 대상 인프라와 현재 commit SHA 이미지를 배포한다.
3. Backend와 Frontend의 리비전, 이미지, Managed Identity, RBAC, KEDA 설정을
   Azure CLI로 확인한다.
4. 데이터 복사 중 외부 쓰기를 막기 위해 대상 Frontend와 Backend ingress를
   비활성화한다.

이 단계에서는 원본 환경과 원본 GitHub 배포 설정을 유지한다.

### 5.2 Blob 1차 복사

Microsoft Entra 인증을 사용하는 AzCopy로 원본 Blob 컨테이너를 대상 컨테이너에
동기화한다. Shared Key 또는 장기 SAS를 만들지 않는다. 원본은 계속 서비스하므로 이
단계의 결과는 예비 복사본이며 최종 정합성 판정에 사용하지 않는다.

복사 전후에 다음 inventory를 저장한다.

- Blob 개수
- 총 content length
- Blob 이름과 크기
- 저장된 Content-MD5가 있는 Blob의 MD5

### 5.3 Cosmos 1차 복사

Azure Identity로 양쪽 Cosmos DB에 접속하는 마이그레이션 스크립트를 사용한다.
다음 컨테이너의 모든 문서를 읽어 같은 `id`와 파티션 키로 대상에 upsert한다.

| 컨테이너 | 파티션 키 |
|---|---|
| `users` | `/id` |
| `folders` | `/id` |
| `flipbooks` | `/id` |
| `overlays` | `/bookId` |

`_rid`, `_self`, `_etag`, `_attachments`, `_ts` 같은 Cosmos 시스템 필드는 복사하지
않는다. 비밀번호 해시를 포함한 애플리케이션 필드는 보존하되, `flipbooks` 문서의
`image_urls`, `cover_urls`, `pdf_url`에 저장된 원본 Blob URL은 대상 Storage Account의
동일 컨테이너·Blob 경로로 변환한다. 원본 Storage hostname과 컨테이너가 정확히 일치하는
URL만 변환하고, overlay의 외부 `data_url` 같은 사용자 링크는 변경하지 않는다.

### 5.4 쓰기 동결과 최종 동기화

1. 원본 Frontend와 Backend ingress를 비활성화한다.
2. 활성 원본 리비전을 비활성화해 KEDA cron이나 HTTP scaler가 애플리케이션 쓰기를
   다시 시작하지 못하게 한다.
3. 원본 요청과 데이터 변경이 멈췄음을 확인한다.
4. AzCopy 최종 증분 동기화를 실행한다.
5. Cosmos 4개 컨테이너를 다시 upsert하고 대상에만 남은 비시스템 문서가 없도록
   원본 기준으로 동기화한다.

원본 쓰기 동결 시점부터 대상 공개 전환까지는 짧은 점검 중단 시간이 발생한다.

## 6. 데이터 정합성 검증

### Blob

원본과 대상에서 Blob 이름별 크기를 비교하고 전체 개수와 총 바이트를 확인한다.
Content-MD5가 있는 Blob은 MD5도 비교한다. 차이가 하나라도 있으면 전환하지 않는다.

### Cosmos DB

원본 문서에는 대상 Blob URL 변환을 적용하고, 대상 문서와 함께 Cosmos 시스템 필드를
제거한 뒤 키 순서를 정규화한 JSON을 생성한다. 컨테이너별로 다음 값을 비교한다.

- 문서 수
- `id`와 파티션 키 집합
- 문서별 SHA-256
- 컨테이너 전체의 정렬된 SHA-256 목록

`users`, `folders`, `flipbooks`, `overlays` 중 하나라도 불일치하면 원본 서비스를
복구하고 대상 데이터를 다시 동기화한다. 대상 `flipbooks` 문서에 원본 Storage hostname이
하나라도 남아 있으면 검증 실패로 처리한다.

검증 결과에는 데이터 내용이나 비밀번호 해시를 남기지 않고 개수, 크기, digest,
실행 시각만 기록한다.

## 7. GitHub Actions 전환

데이터 최종 동기화가 끝나면 GitHub 저장소 변수를 다음 대상으로 변경한다.

- `AZURE_SUBSCRIPTION_ID=43ab425a-c793-4f2e-b71a-0af7a14f26d2`
- `AZURE_TENANT_ID=1716e63d-ed31-49bf-aa16-5effd27bc340`
- `AZURE_ENV_NAME=jjflipbook-p2`
- `AZURE_LOCATION=koreacentral`
- `AZURE_CLIENT_ID`는 기존 OIDC App Registration을 유지

먼저 `validate_only=true` 수동 workflow를 실행해 대상 구독 Preview를 확인한다.
그 다음 전체 workflow를 한 번만 실행한다. 자동 push 실행과 수동 전체 실행을 동시에
시작하지 않으며, 이전 작업 중에는 `main` 배포 변경을 동결한다.

전체 workflow는 이미지 빌드, OIDC 로그인, 인프라 프로비저닝, 정확한 SHA 리비전
수렴, smoke test, 레거시 리소스 정리를 순서대로 완료해야 한다.

## 8. 운영 검증과 전환

대상 ingress를 활성화한 후 다음 게이트를 순서대로 확인한다.

1. Backend/Frontend가 정확한 commit SHA 이미지의 단일 Healthy 리비전이다.
2. root와 `/api/backend/healthz`가 HTTP 200을 반환한다.
3. 관리자 로그인이 성공한다.
4. 기존 폴더와 플립북 목록이 정상적으로 조회된다.
5. 테스트 PDF 업로드, 변환, 조회, 삭제가 성공한다.
6. smoke test가 만든 Blob과 Cosmos 문서가 모두 정리된다.
7. 기존 플립북의 이미지, 표지, PDF URL이 대상 Storage SAS URL로 반환된다.
8. smoke test 후 Blob/Cosmos 정합성 검증이 다시 통과한다.
9. 양쪽 Container App에 `daily-warm-window`와 HTTP scale rule이 존재한다.
10. Backend Identity의 Storage/Cosmos 역할이 정확하다.
11. 최종 리비전 이후 Application/System 오류 로그가 없다.
12. GitHub Actions 전체 실행이 대상 구독을 가리키며 성공했다.

모든 게이트를 통과하면 대상 Frontend URL을 최종 운영 URL로 기록하고 README와
배포 문서를 갱신한다.

## 9. 실패 처리와 Rollback

원본 리소스 그룹을 삭제하기 전에는 다음 순서로 rollback할 수 있다.

1. 대상 Frontend/Backend ingress를 비활성화한다.
2. 원본의 마지막 Healthy 리비전을 다시 활성화한다.
3. 원본 Frontend/Backend ingress를 활성화한다.
4. GitHub `AZURE_SUBSCRIPTION_ID`를 원본 구독으로 되돌린다.
5. 원본 health와 로그인 경로를 확인한다.

검증 중에는 대상 URL을 일반 사용자에게 배포하지 않으므로 대상에서 새로운 운영 데이터가
생기지 않는 것을 전제로 한다. 예상하지 않은 사용자 쓰기가 발생했다면 대상 데이터를
원본으로 역동기화하기 전에는 rollback하지 않는다.

원본 리소스 그룹 삭제 후에는 원본 환경으로 rollback할 수 없다. 이후 복구는 대상
Cosmos DB의 백업 정책과 대상 Storage에 남아 있는 데이터만 사용한다. 이 제한은
원본 즉시 삭제 정책의 명시적인 결과다.

## 10. 원본 삭제와 권한 정리

8절의 모든 검증 증거가 확보된 직후 다음을 수행한다.

1. 원본 구독의 `rg-jjflipbook-p2`를 삭제한다.
2. 리소스 그룹 삭제 완료와 원본 리소스 부재를 확인한다.
3. GitHub OIDC Service Principal에 부여된 원본 구독 범위의
   `Contributor`와 `Role Based Access Control Administrator`를 회수한다.
4. 데이터 복사 실행 주체의 양쪽 임시 데이터 평면 역할을 회수한다.
5. GitHub 저장소 변수와 운영 문서가 대상 구독과 새 Frontend URL만 가리키는지 확인한다.

대상 구독의 OIDC 역할, Backend Managed Identity 역할, GitHub Actions 배포 변수는
운영을 위해 유지한다.

## 11. 구현 산출물

- 대상 구독용 갱신된 `.azure/deployment-plan.md`
- Provider, quota, Preview, 배포, 데이터 복사, 검증, 삭제 절차를 담은 실행 계획
- Blob inventory 및 Cosmos digest를 생성·비교하는 재실행 가능한 마이그레이션 도구
- destructive 단계에 검증 증거를 요구하는 원본 정리 절차
- 대상 구독과 새 운영 URL을 반영한 README
- 대상 구독에서 성공한 GitHub Actions 실행과 Azure CLI 검증 기록
