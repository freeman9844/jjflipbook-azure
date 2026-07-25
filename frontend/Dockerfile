# frontend/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
# React 19 의존성 충돌 무시 및 deprecated 경고 로그 차단
ENV NPM_CONFIG_UPDATE_NOTIFIER=false
ENV NPM_CONFIG_AUDIT=false
ENV NPM_CONFIG_FUND=false
RUN npm install --legacy-peer-deps --loglevel=error
COPY . .

# 빌드 시점에 백엔드 Cloud Run URL을 주입 (정적 JS 파일에 구워짐)
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL

RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Next.js standalone 포트 3000 노출
EXPOSE 3000
CMD ["node", "server.js"]
