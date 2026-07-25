#!/bin/bash
set -e

# =========================================================
# 🛠 [설정 구역] 본인의 GCP 환경에 맞게 수정하세요.
# =========================================================
PROJECT_ID="your-new-project-id"           # 배포할 GCP 프로젝트 ID
REGION="asia-northeast3"                   # 리전 (서울)
BUCKET_NAME="jjflipbook-storage-$PROJECT_ID" # GCS 버킷 이름 (글로벌 고유)
DB_NAME="jjflipbook"                       # Firestore DB 이름
API_KEY="my-secret-internal-key-1234!"     # 프론트<->백엔드 통신용 API 키
ADMIN_PW=$(openssl rand -base64 12)        # 초기 관리자 비밀번호 (자동 무작위 생성)
# =========================================================

echo "🚀 [$PROJECT_ID] 프로젝트에 배포를 시작합니다..."
gcloud config set project $PROJECT_ID

echo "📦 필수 API를 활성화하는 중..."
gcloud services enable \
    run.googleapis.com \
    storage.googleapis.com \
    firestore.googleapis.com \
    cloudbuild.googleapis.com

echo "🗄️ Firestore 데이터베이스 ($DB_NAME) 확인/생성..."
gcloud firestore databases create \
    --database=$DB_NAME \
    --location=$REGION \
    --type=firestore-native || echo "✅ DB가 이미 존재합니다."

echo "🪣 Cloud Storage 버킷 ($BUCKET_NAME) 생성..."
gcloud storage buckets create gs://$BUCKET_NAME --location=$REGION || echo "✅ 버킷이 이미 존재합니다."

# ---------------------------------------------------------
# [Step 1] 백엔드 (FastAPI) 빌드 및 배포
# ---------------------------------------------------------
echo "⚙️ [1/2] 백엔드(FastAPI) 빌드 및 Cloud Run 배포 시작..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/flipbook-backend ./backend

gcloud run deploy jjflipbook-backend \
    --image gcr.io/$PROJECT_ID/flipbook-backend \
    --region $REGION \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --no-cpu-throttling \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GCS_BUCKET_NAME=$BUCKET_NAME,INTERNAL_API_KEY=$API_KEY,ADMIN_PASSWORD=$ADMIN_PW"

# 배포된 백엔드 URL 추출 (프론트엔드 빌드 시점에 필요함)
BACKEND_URL=$(gcloud run services describe jjflipbook-backend --region $REGION --format 'value(status.url)')
echo "✅ 백엔드 배포 완료! URL: $BACKEND_URL"

# ---------------------------------------------------------
# [Step 2] 프론트엔드 (Next.js) 빌드 및 배포
# ---------------------------------------------------------
echo "🎨 [2/2] 프론트엔드(Next.js) 빌드 및 Cloud Run 배포 시작..."
cd frontend

# 핵심 조치: cloudbuild.yaml을 이용해 도커 빌드 시점에 BACKEND_URL을 주입하여 정적 파일에 굽습니다.
gcloud builds submit --config cloudbuild.yaml \
    --substitutions=_NEXT_PUBLIC_BACKEND_URL=$BACKEND_URL .

gcloud run deploy jjflipbook-frontend \
    --image gcr.io/$PROJECT_ID/flipbook-frontend \
    --region $REGION \
    --allow-unauthenticated \
    --memory 1Gi \
    --set-env-vars="NEXT_PUBLIC_BACKEND_URL=$BACKEND_URL,INTERNAL_API_KEY=$API_KEY"

cd ..
FRONTEND_URL=$(gcloud run services describe jjflipbook-frontend --region $REGION --format 'value(status.url)')

echo "======================================================"
echo "🎉 모든 배포가 성공적으로 완료되었습니다!"
echo "👉 접속 주소 (프론트엔드): $FRONTEND_URL"
echo "🔑 관리자 계정 ID : admin"
echo "🔑 관리자 비밀번호: $ADMIN_PW"
echo "======================================================"
