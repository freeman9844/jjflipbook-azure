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

# 런타임 시점에 백엔드 URL이 Container App에 주입됨
RUN npm run build

FROM node:20-alpine AS runner
LABEL org.opencontainers.image.source="https://github.com/freeman9844/jjflipbook-azure"
WORKDIR /app
ENV NODE_ENV production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Next.js standalone 포트 3000 노출
EXPOSE 3000
CMD ["node", "server.js"]
