# GCP 비용 최적화 설계 (Zero-Waste 전략)

**날짜:** 2026-04-14  
**대상 환경:** jwlee-test-project-01 / jwlee-argolis-202104 (양쪽 모두)  
**전략:** Approach 1 — deploy.sh Cloud Run 설정 + GCS Lifecycle 정책

---

## 목표

가끔씩 사용하는 소규모 패턴에서 유휴 비용을 0에 가깝게 만든다.  
콜드 스타트(~30초)는 감수한다.  
아키텍처 변경 없이 설정 수정만으로 달성한다.

---

## 변경 범위

1. `deploy.sh` — Cloud Run 배포 옵션 수정
2. `gcs-lifecycle.json` 신규 파일 추가
3. `deploy.sh` — GCS Lifecycle 적용 단계 추가

---

## Section 1: Cloud Run 설정 변경

### Backend (`flipbook-backend`)

| 옵션 | 현재 | 변경 후 | 근거 |
|---|---|---|---|
| `--min-instances` | 미지정 | `0` | 스케일 투 제로 명시 보장 |
| `--max-instances` | 미지정 (기본 100) | `3` | 동시 변환 3개 초과 차단, 폭주 요금 방지 |
| `--concurrency` | 미지정 (기본 80) | `1` | PDF 변환은 CPU/메모리 집약 작업, 인스턴스당 1요청으로 OOM 방지 |
| `--memory` | `2Gi` | `2Gi` (유지) | PDF 변환에 필요한 최소 사양 |
| `--cpu` | `2` | `2` (유지) | PDF 변환 성능 유지 |
| `--timeout` | `600` | `600` (유지) | 대용량 PDF 변환 시간 확보 |

### Frontend (`flipbook-frontend`)

| 옵션 | 현재 | 변경 후 | 근거 |
|---|---|---|---|
| `--memory` | 미지정 (기본 512Mi) | `512Mi` | 명시적 고정, Next.js에 충분 |
| `--cpu` | 미지정 (기본 1) | `1` | 정적 렌더링에 1 vCPU 충분 |
| `--min-instances` | 미지정 | `0` | 스케일 투 제로 명시 보장 |
| `--max-instances` | 미지정 (기본 100) | `5` | 소규모 트래픽 상한, 폭주 방지 |
| `--concurrency` | 미지정 (기본 80) | `80` (유지) | Next.js 다중 요청 처리 가능 |

---

## Section 2: GCS Lifecycle 정책

`gcs-lifecycle.json` 파일을 저장소 루트에 추가하고 deploy.sh에서 양쪽 버킷에 적용한다.

### 규칙 1: 미완료 멀티파트 업로드 삭제 (1일)

- **조건:** `abortIncompleteMultipartUpload`, age ≥ 1일
- **이유:** 업로드 중단 시 GCS에 남는 불완전한 임시 데이터가 요금을 유발

### 규칙 2: 고아(Orphan) 이미지 안전망 삭제 (365일)

- **조건:** prefix `flipbooks/`, age ≥ 365일
- **이유:** `delete_single_flipbook` GCS 정리 실패 시 장기 누적 방지
- **안전성:** 365일은 충분히 보수적 — 실제 활성 플립북에는 영향 없음

### 적용 시점

`deploy.sh` Phase 0 (TDD 검증) 완료 직후, Backend 빌드(Phase 1) 시작 전에 적용한다.  
양쪽 환경의 버킷(`jjflipbook-gcs-0001`, `jjflipbook-gcs-001`)에 모두 적용한다.

---

## 예상 비용 효과

| 항목 | 현재 | 최적화 후 |
|---|---|---|
| Cloud Run 유휴 비용 | 미설정으로 인스턴스 잔존 가능 | 0 (스케일 투 제로 보장) |
| PDF 변환 1회 비용 | ~$0.03 (2CPU × 10분) | 동일 (사양 유지) |
| 프론트엔드 메모리 비용 | 명시되지 않아 불명확 | 512Mi로 명시, 최소화 |
| GCS 고아 객체 비용 | 무기한 누적 | 365일 후 자동 정리 |
| 예상 월 총비용 | $3-10 (설정 미흡 시) | **$1-3** |

---

## 파일 변경 목록

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `deploy.sh` | 수정 | Backend/Frontend Cloud Run 옵션 추가, GCS Lifecycle 적용 단계 추가 |
| `gcs-lifecycle.json` | 신규 | 멀티파트 업로드 정리 + 고아 객체 삭제 규칙 |

---

## 제약 사항

- 콜드 스타트 ~20-30초 발생 (소규모 사용 패턴상 수용)
- `--max-instances=3` 설정으로 동시 업로드 3개 초과 시 대기 발생 (소규모 패턴상 문제 없음)
- GCS Lifecycle은 `gcloud storage` CLI 권한 필요 (배포 계정이 `storage.admin` 역할 보유 전제)
