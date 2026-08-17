FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS builder
WORKDIR /app
COPY package*.json ./
ENV NPM_CONFIG_UPDATE_NOTIFIER=false
ENV NPM_CONFIG_AUDIT=false
ENV NPM_CONFIG_FUND=false
RUN npm ci --legacy-peer-deps --loglevel=error
COPY . .
RUN npm run build
RUN rm -rf \
    .next/standalone/node_modules/@img \
    .next/standalone/node_modules/sharp \
    && test ! -e .next/standalone/node_modules/@img \
    && test ! -e .next/standalone/node_modules/sharp

FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS runner
LABEL org.opencontainers.image.source="https://github.com/freeman9844/jjflipbook-azure"
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
