# JJFlipBook Low-Risk Optimization Design

**Date:** 2026-08-16
**Status:** Approved for implementation planning

## Goal

Reduce avoidable telemetry cost, dashboard payload size, stale SAS failures,
deployment time, and proxy failure ambiguity without changing the PDF
processing architecture or the public View URL contract.

## Current Evidence

- Log Analytics ingested about 179 MB in 24 hours:
  - `ContainerAppConsoleLogs_CL`: 124 MB
  - `AppTraces`: 46 MB
- The active backend revision emitted more than 217,000 console entries.
  Most high-volume messages were Azure SDK request headers, exporter
  transmission confirmations, and live diagnostics traffic.
- Backend health probes use `/`, so platform probes are recorded as application
  requests and dependencies.
- `GET /flipbooks` selects complete documents and signs every page URL for up to
  50 books, while the dashboard only reads the first image as the cover.
- SAS URLs are regenerated on each response. A stale Next.js music cache entry
  returned 403 after deployment while a fresh backend response returned 206.
- The frontend proxy has a 10-minute POST timeout but no GET timeout.
- Docker builds do not use GitHub Actions layer caching. The frontend image
  uses `npm install`, Node 20, and legacy Docker `ENV` syntax.

## Scope

### Included

1. Suppress Azure SDK and Azure Monitor exporter INFO-level log amplification.
2. Add a dedicated health endpoint and exclude it from application telemetry.
3. Return only one signed cover URL per book from the dashboard list endpoint.
4. Cache generated SAS URLs in each backend process until shortly before
   expiration.
5. Stop caching SAS-bearing music responses in the Next.js data cache and
   propagate backend failures.
6. Add a bounded timeout and explicit gateway timeout response to frontend GET
   proxy requests.
7. Enable service-specific GitHub Actions Docker layer caches.
8. Use Node 22, reproducible `npm ci`, and current Docker `ENV` syntax.

### Excluded

- Queue-based or Azure Container Apps Job PDF processing
- Database partition-key changes
- New CDN, Front Door, Redis, or Key Vault resources
- Blob migration or bulk metadata updates
- Changes to administrator authentication
- Changes to the public `/view/{uuidKey}` URL

## Design

### 1. Telemetry and Health Probes

The backend will expose:

```http
GET /healthz
200 {"status":"ok"}
```

All backend startup, readiness, and liveness probes will target `/healthz`.
FastAPI OpenTelemetry instrumentation will exclude this path so platform
probes do not create application request and dependency telemetry.

Before Azure Monitor is configured, the `azure` logger hierarchy will be set to
`WARNING`. Application loggers remain at `INFO`, preserving PDF processing,
authentication, and explicit application diagnostics while removing Azure SDK
HTTP headers and exporter self-reporting.

### 2. Dashboard List Contract

`GET /flipbooks` keeps the existing response shape used by the frontend. Each
book still contains `image_urls`, but the array contains at most one signed
cover URL.

The Cosmos query will project only dashboard fields:

- `id`
- `uuid_key`
- `title`
- `folder_id`
- `user_id`
- `page_count`
- `created_at`
- `status`
- first image URL

`GET /flipbook/{uuidKey}` remains unchanged and returns the complete page list
for the viewer and editor.

This preserves frontend compatibility while preventing dashboard requests from
serializing and signing every page of every book.

### 3. SAS URL Cache

The backend will cache signed Blob URLs per blob name in process memory.

- Generated SAS lifetime remains two hours.
- Cache entries are reused for up to 90 minutes.
- Entries refresh before the underlying SAS approaches expiration.
- Cache access uses a dedicated lock so it cannot deadlock with the existing
  user-delegation-key lock.
- The cache is per replica; no distributed cache is introduced.
- A revision restart safely starts with an empty cache.

Only validated URLs for the configured storage account and container are
cached. The existing managed-identity and user-delegation flow remains
unchanged.

### 4. Music Response Freshness

The frontend `/api/music` route will fetch the backend with `cache: 'no-store'`.
It will not store full SAS URLs in the Next.js data cache.

If the backend cannot list or sign music:

- Backend `/music/list` returns HTTP 503 instead of a successful empty list.
- Frontend `/api/music` preserves the failure status.
- `MusicPlayer` continues to degrade without blocking the flipbook viewer.

An empty but successful Blob listing remains HTTP 200 with `files: []`.

### 5. Frontend GET Proxy Timeout

All proxied GET requests to the backend will use an `AbortController` with a
30-second timeout.

- Backend response status and JSON body continue to pass through unchanged.
- Timeout returns HTTP 504 with a stable error message.
- Other connection failures return HTTP 502.
- Authentication checks handled entirely by the frontend remain unchanged.
- The existing 10-minute upload POST timeout remains unchanged.

### 6. CI and Runtime Image

Both `docker/build-push-action` steps will use GitHub Actions cache backends
with separate scopes for frontend and backend.

The frontend Dockerfile will:

- use `node:22-alpine`
- use `npm ci --legacy-peer-deps`
- keep the existing lockfile as the dependency source of truth
- set `ENV NODE_ENV=production`

No application dependency versions change in this phase.

## Error Handling

- Telemetry setup remains non-fatal, but setup failures continue to emit one
  application warning.
- A Cosmos projection or response-shape failure is surfaced as an API error;
  the list endpoint does not silently return incomplete books.
- SAS cache generation failures propagate to the caller rather than storing an
  invalid value.
- Music storage failures return 503 and are not cached as successful empty
  responses.
- GET proxy timeouts are distinguishable from backend 4xx/5xx responses.

## Testing

### Backend

- Health endpoint returns 200 and deployment probes target `/healthz`.
- Telemetry instrumentation excludes `/healthz`.
- Azure logger hierarchy is configured at `WARNING`.
- List endpoint returns no more than one signed cover URL per book.
- Detail endpoint still returns all page URLs.
- SAS cache reuses a URL, refreshes near expiry, and never caches invalid URLs.
- Music listing returns 503 on Blob errors and 200 for a valid empty listing.

### Frontend

- GET proxy preserves backend responses.
- GET proxy returns 504 on timeout and 502 on connection failure.
- Music route uses `no-store` and preserves backend failure status.
- Existing viewer, authentication, and music component tests continue to pass.

### Deployment Configuration

- Backend probes use `/healthz`.
- GitHub Actions uses separate backend and frontend BuildKit cache scopes.
- Frontend Dockerfile uses Node 22 and `npm ci`.

## Rollout

1. Implement with test-driven development.
2. Run backend and frontend suites, type-check, lint, build, Bicep compile, and
   deployment configuration tests.
3. Validate the Azure deployment preview.
4. Push one immutable commit to `main`.
5. Let the existing GitHub Actions workflow build, provision, smoke test, and
   clean retained GHCR versions.
6. Verify healthy revisions, endpoint behavior, BGM URLs, and live RBAC.
7. Compare Log Analytics ingestion after a full operating window.

## Success Criteria

- Public frontend and View endpoints remain available.
- Backend probe status is healthy on `/healthz`.
- Health probes no longer appear as application requests.
- Azure SDK/exporter INFO messages no longer dominate console or trace logs.
- Daily console and trace ingestion drops by at least 90% from the observed
  179 MB baseline under comparable traffic.
- Dashboard list responses contain at most one image URL per book.
- Detail responses retain all page URLs.
- Fresh music URLs return partial-content or successful audio responses.
- GET proxy timeout tests and the production smoke test pass.
- Deployment workflow duration does not regress; subsequent builds can reuse
  Docker layers.

## Rollback

The change adds no Azure resource and performs no data migration. Rollback is a
Git revert followed by the existing deployment workflow. Existing Cosmos
documents and Blob objects remain compatible with both versions.
