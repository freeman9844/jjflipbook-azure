FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
ENV NPM_CONFIG_UPDATE_NOTIFIER=false
ENV NPM_CONFIG_AUDIT=false
ENV NPM_CONFIG_FUND=false
RUN npm ci --legacy-peer-deps --loglevel=error
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
LABEL org.opencontainers.image.source="https://github.com/freeman9844/jjflipbook-azure"
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
