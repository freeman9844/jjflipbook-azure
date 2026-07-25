# GCP 비용 최적화 (Zero-Waste) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cloud Run 스케일 투 제로 보장 및 GCS Lifecycle 정책 적용으로 유휴 비용을 0에 가깝게 만든다.

**Architecture:** `gcs-lifecycle.json` 신규 파일 추가 후 `deploy.sh`에 Lifecycle 적용 단계 삽입. Backend/Frontend Cloud Run 옵션에 min-instances, max-instances, concurrency, memory, cpu를 명시적으로 설정한다. 아키텍처 변경 없이 설정 수정만으로 완료.

**Tech Stack:** `Bash`, `gcloud CLI`, `Google Cloud Run`, `Google Cloud Storage`

---

## 변경 파일 목록

| 파일 | 유형 | 변경 내용 |
|---|---|---|
| `gcs-lifecycle.json` | 신규 | 미완료 업로드 삭제(1일) + 고아 객체 삭제(365일) |
| `deploy.sh` | 수정 | GCS Lifecycle 적용 단계 추가, Backend/Frontend Cloud Run 옵션 추가 |

---

### Task 1: gcs-lifecycle.json 생성

**Files:**
- Create: `gcs-lifecycle.json`

- [ ] **Step 1: 파일 생성**

저장소 루트에 `gcs-lifecycle.json`을 아래 내용으로 생성한다.

```json
{
  "rule": [
    {
      "action": { "type": "AbortIncompleteMultipartUpload" },
      "condition": { "age": 1 }
    },
    {
      "action": { "type": "Delete" },
      "condition": { "age": 365 }
    }
  ]
}
```

- `AbortIncompleteMultipartUpload`: 업로드 도중 끊긴 임시 데이터를 1일 후 삭제
- `Delete age: 365`: 365일 이상 된 객체 삭제 (삭제 실패로 남은 고아 이미지 정리)

- [ ] **Step 2: JSON 문법 검증**

```bash
python3 -m json.tool gcs-lifecycle.json
```

기대 결과: JSON 내용이 정상 출력됨 (오류 없음)

- [ ] **Step 3: 커밋**

```bash
git add gcs-lifecycle.json
git commit -m "chore(gcs): add lifecycle policy - abort incomplete uploads (1d) and delete orphans (365d)"
```

---

### Task 2: deploy.sh — GCS Lifecycle 적용 단계 추가

**Files:**
- Modify: `deploy.sh:144-160`

- [ ] **Step 1: VPC 옵션 블록 바로 앞에 Lifecycle 적용 단계 삽입**

`deploy.sh`의 144번째 줄 (`echo "✅ 사전 역량 검증 완벽 통과!..."`) 다음 줄에 아래 블록을 삽입한다.

기존:
```bash
echo "✅ 사전 역량 검증 완벽 통과! 진짜 클라우드 배포 파이프라인(Phase 1~4)을 시작합니다..."

# ========================================
# [VPC 및 네트워크 보안 옵션 처리]
```

변경 후:
```bash
echo "✅ 사전 역량 검증 완벽 통과! 진짜 클라우드 배포 파이프라인(Phase 1~4)을 시작합니다..."

echo "----------------------------------------"
echo "🗄️ [Phase 0.5] GCS Lifecycle 정책 적용 중... (버킷: $GCS_BUCKET_NAME)"
echo "----------------------------------------"
$GCLOUD_PATH storage buckets update gs://$GCS_BUCKET_NAME \
  --project=$PROJECT_ID \
  --lifecycle-file=gcs-lifecycle.json
if [ $? -ne 0 ]; then
  echo "⚠️ GCS Lifecycle 설정 실패 (비치명적, 배포는 계속 진행됩니다)"
else
  echo "✅ GCS Lifecycle 정책 적용 완료"
fi

# ========================================
# [VPC 및 네트워크 보안 옵션 처리]
```

- [ ] **Step 2: bash 문법 검증**

```bash
bash -n deploy.sh
```

기대 결과: 아무 출력 없음 (문법 오류 없음)

- [ ] **Step 3: 커밋**

```bash
git add deploy.sh
git commit -m "chore(deploy): add gcs lifecycle policy application phase (Phase 0.5)"
```

---

### Task 3: deploy.sh — Backend Cloud Run 옵션 추가

**Files:**
- Modify: `deploy.sh:172-184`

- [ ] **Step 1: Backend 배포 블록에 옵션 3개 추가**

기존 (172-184번째 줄):
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
  $VPC_OPTIONS \
  $INGRESS_OPTIONS \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,FIRESTORE_DB_NAME=$FIRESTORE_DB_NAME,GCS_BUCKET_NAME=$GCS_BUCKET_NAME,INTERNAL_API_KEY=$INTERNAL_API_KEY,ADMIN_PASSWORD=$ADMIN_PASSWORD"
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
  --min-instances=0 \
  --max-instances=3 \
  --concurrency=1 \
  $VPC_OPTIONS \
  $INGRESS_OPTIONS \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,FIRESTORE_DB_NAME=$FIRESTORE_DB_NAME,GCS_BUCKET_NAME=$GCS_BUCKET_NAME,INTERNAL_API_KEY=$INTERNAL_API_KEY,ADMIN_PASSWORD=$ADMIN_PASSWORD"
```

옵션 설명:
- `--min-instances=0`: 트래픽 없을 때 인스턴스 0개로 스케일 투 제로 (유휴 비용 0)
- `--max-instances=3`: 동시 PDF 변환 최대 3개로 제한, 폭주 요금 방지
- `--concurrency=1`: 인스턴스당 PDF 변환 요청 1개만 처리 (2GB 메모리 동시 점유 방지)

- [ ] **Step 2: bash 문법 검증**

```bash
bash -n deploy.sh
```

기대 결과: 아무 출력 없음 (문법 오류 없음)

- [ ] **Step 3: diff 확인**

```bash
git diff deploy.sh
```

기대 결과: `--min-instances=0`, `--max-instances=3`, `--concurrency=1` 3줄이 추가된 것만 보임

- [ ] **Step 4: 커밋**

```bash
git add deploy.sh
git commit -m "chore(deploy): add backend cloud run cost optimization options (min=0, max=3, concurrency=1)"
```

---

### Task 4: deploy.sh — Frontend Cloud Run 옵션 추가

**Files:**
- Modify: `deploy.sh:203-211`

- [ ] **Step 1: Frontend 배포 블록에 옵션 4개 추가**

기존 (203-211번째 줄):
```bash
$GCLOUD_PATH run deploy flipbook-frontend \
  --project=$PROJECT_ID \
  --image $DOCKER_REPO/flipbook-frontend \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  $VPC_OPTIONS \
  --set-env-vars "NEXT_PUBLIC_BACKEND_URL=$BACKEND_URL,GCS_BUCKET_NAME=$GCS_BUCKET_NAME,INTERNAL_API_KEY=$INTERNAL_API_KEY,SESSION_SECRET=$SESSION_SECRET"
```

변경 후:
```bash
$GCLOUD_PATH run deploy flipbook-frontend \
  --project=$PROJECT_ID \
  --image $DOCKER_REPO/flipbook-frontend \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  $VPC_OPTIONS \
  --set-env-vars "NEXT_PUBLIC_BACKEND_URL=$BACKEND_URL,GCS_BUCKET_NAME=$GCS_BUCKET_NAME,INTERNAL_API_KEY=$INTERNAL_API_KEY,SESSION_SECRET=$SESSION_SECRET"
```

옵션 설명:
- `--memory=512Mi`: Next.js SSR에 충분한 메모리를 명시적으로 지정 (기본값과 동일하지만 명시화)
- `--cpu=1`: 프론트엔드 렌더링에 1 vCPU 충분, 명시화
- `--min-instances=0`: 스케일 투 제로 명시 보장
- `--max-instances=5`: 소규모 트래픽 상한 설정, 폭주 방지

- [ ] **Step 2: bash 문법 검증**

```bash
bash -n deploy.sh
```

기대 결과: 아무 출력 없음 (문법 오류 없음)

- [ ] **Step 3: diff 확인**

```bash
git diff deploy.sh
```

기대 결과: `--memory=512Mi`, `--cpu=1`, `--min-instances=0`, `--max-instances=5` 4줄 추가만 보임

- [ ] **Step 4: 커밋**

```bash
git add deploy.sh
git commit -m "chore(deploy): add frontend cloud run cost optimization options (memory=512Mi, min=0, max=5)"
```

---

## 최종 검증

모든 Task 완료 후:

```bash
# 전체 파일 문법 재확인
bash -n deploy.sh && echo "✅ deploy.sh 문법 OK"
python3 -m json.tool gcs-lifecycle.json && echo "✅ gcs-lifecycle.json 형식 OK"

# 커밋 로그 확인
git log --oneline -5
```

기대 결과:
```
✅ deploy.sh 문법 OK
✅ gcs-lifecycle.json 형식 OK
<hash> chore(deploy): add frontend cloud run cost optimization options
<hash> chore(deploy): add backend cloud run cost optimization options
<hash> chore(deploy): add gcs lifecycle policy application phase
<hash> chore(gcs): add lifecycle policy
```
