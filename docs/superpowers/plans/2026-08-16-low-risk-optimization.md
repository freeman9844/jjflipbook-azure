# JJFlipBook Low-Risk Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce telemetry noise, dashboard payloads, stale SAS failures, proxy ambiguity, and CI build time without changing the PDF processing architecture or public View URLs.

**Architecture:** Keep the existing Next.js frontend, FastAPI backend, Cosmos DB, Blob Storage, and Azure Container Apps topology. Apply focused changes at existing boundaries: health/telemetry configuration, dashboard projection, per-replica SAS caching, music and proxy error semantics, and container build configuration.

**Tech Stack:** Python 3.11, FastAPI, Azure Monitor OpenTelemetry, Azure Cosmos DB, Azure Blob Storage, Next.js 16, React 19, Jest, Pytest, Bicep, GitHub Actions, GHCR, Azure Container Apps

**Spec:** `docs/superpowers/specs/2026-08-16-low-risk-optimization-design.md`

## Global Constraints

- Keep the public `/view/{uuidKey}` URL unchanged.
- Keep PDF upload and conversion synchronous in this phase.
- Add no Azure resource, CDN, Redis, queue, job, or database migration.
- Preserve managed identity and user-delegation SAS authentication.
- Keep generated SAS lifetime at two hours and cache reuse at 90 minutes.
- Keep frontend POST upload timeout at 10 minutes.
- Use a 30-second timeout for proxied GET requests.
- Use Node 22 and the committed `package-lock.json`; do not change dependency versions.
- Implement every behavior change with a failing test first.
- Use one focused commit per task and include the required Copilot co-author trailer.

---

### Task 1: Stop Telemetry Amplification and Isolate Health Probes

**Files:**
- Modify: `backend/main.py`
- Modify: `infra/resources.bicep`
- Regenerate: `infra/main.json`
- Test: `backend/tests/test_api_local.py`
- Test: `backend/tests/test_runtime_config.py`
- Test: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Produces: `configure_logging() -> None` in `backend/main.py`
- Produces: `GET /healthz -> {"status": "ok"}`
- Produces: backend startup, readiness, and liveness probes targeting `/healthz`
- Preserves: `GET /` response for existing callers

- [ ] **Step 1: Add failing backend health and logging tests**

Add to `backend/tests/test_api_local.py`:

```python
def test_dedicated_health_check():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Add to `backend/tests/test_runtime_config.py`:

```python
import logging

import main


def test_azure_sdk_logging_is_warning_or_higher():
    main.configure_logging()
    assert logging.getLogger("azure").level == logging.WARNING
```

- [ ] **Step 2: Add failing deployment configuration assertions**

Extend `test_bicep_defines_selected_scaling_policy` in
`backend/tests/test_deployment_config.py`:

```python
backend_probes = backend_container["probes"]
assert {probe["httpGet"]["path"] for probe in backend_probes} == {"/healthz"}
```

Add a new test:

```python
def test_backend_excludes_health_from_application_telemetry():
    main_source = (ROOT / "backend" / "main.py").read_text()
    assert 'FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")' in main_source
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
cd backend
python3 -m pytest -q \
  tests/test_api_local.py::test_dedicated_health_check \
  tests/test_runtime_config.py::test_azure_sdk_logging_is_warning_or_higher \
  tests/test_deployment_config.py::test_bicep_defines_selected_scaling_policy \
  tests/test_deployment_config.py::test_backend_excludes_health_from_application_telemetry
```

Expected: failures for missing `/healthz`, `configure_logging`, excluded URL,
and probe path.

- [ ] **Step 4: Implement logging and health isolation**

In `backend/main.py`, replace the module-level logging setup with:

```python
def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("azure").setLevel(logging.WARNING)


configure_logging()
logger = logging.getLogger(__name__)
```

Change FastAPI instrumentation to:

```python
FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")
```

Add the dedicated endpoint while preserving `GET /`:

```python
@app.get("/healthz")
def health_check():
    return {"status": "ok"}
```

In all three backend probes in `infra/resources.bicep`, change:

```bicep
httpGet: { path: '/healthz', port: 8080 }
```

- [ ] **Step 5: Regenerate Bicep JSON and verify GREEN**

Run:

```bash
az bicep build --file infra/main.bicep
cd backend
python3 -m pytest -q \
  tests/test_api_local.py::test_dedicated_health_check \
  tests/test_runtime_config.py::test_azure_sdk_logging_is_warning_or_higher \
  tests/test_deployment_config.py::test_bicep_defines_selected_scaling_policy \
  tests/test_deployment_config.py::test_backend_excludes_health_from_application_telemetry
```

Expected: all focused tests pass; Bicep emits only the existing BCP334 warning.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/main.py infra/resources.bicep infra/main.json \
  backend/tests/test_api_local.py backend/tests/test_runtime_config.py \
  backend/tests/test_deployment_config.py
git commit -m "perf: suppress telemetry probe noise" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Return Dashboard Summaries Instead of Full Page Manifests

**Files:**
- Modify: `backend/routers/flipbooks.py`
- Test: `backend/tests/test_api_local.py`

**Interfaces:**
- Produces: `_sign_summary_doc(doc: dict) -> dict`
- Preserves: `GET /flipbooks` response fields and `image_urls: list[str]`
- Changes: `image_urls` from all pages to at most one cover URL for list responses
- Preserves: `GET /flipbook/{uuid_key}` complete signed page list

- [ ] **Step 1: Add failing summary and detail tests**

Extend `backend/tests/test_api_local.py`:

```python
@patch("routers.flipbooks.sign_url", side_effect=lambda value: f"{value}?signed")
@patch("routers.flipbooks.get_container")
def test_list_flipbooks_returns_only_signed_cover(mock_get_container, _sign_url):
    container = MagicMock()
    container.query_items.return_value = [
        {
            "id": "book-1",
            "uuid_key": "book-1",
            "title": "Book",
            "image_urls": ["page-1.webp", "page-2.webp", "page-3.webp"],
        }
    ]
    mock_get_container.return_value = container

    response = client.get("/flipbooks")

    assert response.status_code == 200
    assert response.json()[0]["image_urls"] == ["page-1.webp?signed"]
    query = container.query_items.call_args.kwargs["query"]
    assert "ARRAY_SLICE(c.image_urls, 0, 1)" in query
    assert "SELECT *" not in query


@patch("routers.flipbooks.sign_url", side_effect=lambda value: f"{value}?signed")
@patch("routers.flipbooks.get_container")
def test_get_flipbook_keeps_complete_page_manifest(mock_get_container, _sign_url):
    container = MagicMock()
    container.read_item.return_value = {
        "id": "book-2",
        "image_urls": ["page-1.webp", "page-2.webp"],
    }
    mock_get_container.return_value = container

    response = client.get("/flipbook/book-2")

    assert response.status_code == 200
    assert response.json()["image_urls"] == [
        "page-1.webp?signed",
        "page-2.webp?signed",
    ]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd backend
python3 -m pytest -q \
  tests/test_api_local.py::test_list_flipbooks_returns_only_signed_cover \
  tests/test_api_local.py::test_get_flipbook_keeps_complete_page_manifest
```

Expected: list test receives all three page URLs and query still contains
`SELECT *`.

- [ ] **Step 3: Implement the summary projection**

Add to `backend/routers/flipbooks.py`:

```python
def _sign_summary_doc(doc: dict) -> dict:
    summary = dict(doc)
    summary.pop("error_message", None)
    cover_urls = summary.get("image_urls") or []
    summary["image_urls"] = [sign_url(cover_urls[0])] if cover_urls else []
    return summary
```

Replace the list query and response:

```python
docs = get_container("flipbooks").query_items(
    query="""
    SELECT
        c.id,
        c.uuid_key,
        c.title,
        c.folder_id,
        c.user_id,
        c.page_count,
        c.created_at,
        c.status,
        ARRAY_SLICE(c.image_urls, 0, 1) AS image_urls
    FROM c
    ORDER BY c.created_at DESC
    OFFSET 0 LIMIT 50
    """,
    enable_cross_partition_query=True,
)
return [_sign_summary_doc(doc) for doc in docs]
```

Do not change `_sign_doc` or `get_flipbook`.

- [ ] **Step 4: Verify GREEN and regression behavior**

Run:

```bash
cd backend
python3 -m pytest -q tests/test_api_local.py
```

Expected: all API tests pass, including error-message redaction.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/routers/flipbooks.py backend/tests/test_api_local.py
git commit -m "perf: return lightweight flipbook summaries" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Cache SAS URLs and Surface Music Storage Failures

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/routers/music.py`
- Test: `backend/tests/test_blob_sas.py`
- Test: `backend/tests/test_api_local.py`

**Interfaces:**
- Produces: `_utc_now() -> datetime`
- Produces: `_signed_url_cache: dict[str, tuple[str, datetime]]`
- Preserves: `sign_url(url: str) -> str`
- Changes: `/music/list` returns 503 on Blob access/signing failure

- [ ] **Step 1: Add failing SAS cache tests**

Add to `backend/tests/test_blob_sas.py`:

```python
from datetime import timedelta


def test_sign_url_reuses_cached_sas_until_refresh_window():
    database._signed_url_cache.clear()
    now = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    url = f"{database.BLOB_BASE_URL}/flipbooks/book/page_1.webp"

    with (
        patch.object(database, "_utc_now", return_value=now),
        patch.object(database, "_get_user_delegation_key", return_value=object()),
        patch.object(
            database,
            "generate_blob_sas",
            return_value="sp=r&sig=first",
        ) as generate,
    ):
        first = database.sign_url(url)
        second = database.sign_url(url)

    assert first == second
    assert generate.call_count == 1


def test_sign_url_refreshes_after_cache_ttl():
    database._signed_url_cache.clear()
    start = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    url = f"{database.BLOB_BASE_URL}/flipbooks/book/page_1.webp"

    with (
        patch.object(
            database,
            "_utc_now",
            side_effect=[start, start + timedelta(minutes=91)],
        ),
        patch.object(database, "_get_user_delegation_key", return_value=object()),
        patch.object(
            database,
            "generate_blob_sas",
            side_effect=["sp=r&sig=first", "sp=r&sig=second"],
        ) as generate,
    ):
        first = database.sign_url(url)
        second = database.sign_url(url)

    assert first != second
    assert generate.call_count == 2


def test_sign_url_does_not_cache_external_urls():
    database._signed_url_cache.clear()
    external = "https://other.blob.core.windows.net/container/file.mp3"

    assert database.sign_url(external) == external
    assert database._signed_url_cache == {}
```

- [ ] **Step 2: Add failing music failure tests**

Add to `backend/tests/test_api_local.py`:

```python
@patch("routers.music.get_blob_container")
def test_music_list_returns_empty_success_for_empty_container(mock_container):
    mock_container.return_value.list_blobs.return_value = []
    response = client.get("/music/list")
    assert response.status_code == 200
    assert response.json() == {"files": []}


@patch("routers.music.get_blob_container")
def test_music_list_returns_service_unavailable_on_blob_failure(mock_container):
    mock_container.return_value.list_blobs.side_effect = RuntimeError("storage down")
    response = client.get("/music/list")
    assert response.status_code == 503
    assert response.json() == {"detail": "Music storage unavailable"}
```

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
cd backend
python3 -m pytest -q \
  tests/test_blob_sas.py::test_sign_url_reuses_cached_sas_until_refresh_window \
  tests/test_blob_sas.py::test_sign_url_refreshes_after_cache_ttl \
  tests/test_blob_sas.py::test_sign_url_does_not_cache_external_urls \
  tests/test_api_local.py::test_music_list_returns_empty_success_for_empty_container \
  tests/test_api_local.py::test_music_list_returns_service_unavailable_on_blob_failure
```

Expected: missing cache globals/helper and music failure returns 200.

- [ ] **Step 4: Implement the dedicated SAS cache**

In `backend/database.py`, add:

```python
_sas_cache_lock = threading.Lock()
_signed_url_cache: dict[str, tuple[str, datetime]] = {}
_SIGNED_URL_CACHE_TTL = timedelta(minutes=90)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
```

In `sign_url`, after validating and deriving `blob_name`, use:

```python
now = _utc_now()
with _sas_cache_lock:
    cached = _signed_url_cache.get(blob_name)
    if cached and cached[1] > now:
        return cached[0]
```

Generate the SAS exactly as before, using `now`, then cache only the completed
URL:

```python
signed_url = f"{unsigned_url}?{token}"
with _sas_cache_lock:
    _signed_url_cache[blob_name] = (
        signed_url,
        now + _SIGNED_URL_CACHE_TTL,
    )
return signed_url
```

Do not hold `_sas_cache_lock` while calling `_get_user_delegation_key`.

- [ ] **Step 5: Implement explicit music failure semantics**

In `backend/routers/music.py`, import `HTTPException` and replace the fallback:

```python
except Exception as exc:
    logger.warning(
        "Music storage listing failed (%s)",
        exc.__class__.__name__,
    )
    raise HTTPException(
        status_code=503,
        detail="Music storage unavailable",
    ) from exc
```

- [ ] **Step 6: Verify GREEN**

Run:

```bash
cd backend
python3 -m pytest -q tests/test_blob_sas.py tests/test_api_local.py
```

Expected: all SAS and API tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/database.py backend/routers/music.py \
  backend/tests/test_blob_sas.py backend/tests/test_api_local.py
git commit -m "perf: cache blob sas urls" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Add Frontend Proxy Timeouts and Fresh Music Fetches

**Files:**
- Modify: `frontend/src/app/api/backend/[...path]/route.ts`
- Modify: `frontend/src/app/api/music/route.ts`
- Test: `frontend/src/app/api/backend/[...path]/route.test.ts`
- Test: `frontend/src/app/api/music/route.test.ts`

**Interfaces:**
- Produces: proxied GET timeout response `504 {"error":"Backend request timed out"}`
- Produces: proxied GET connection response `502 {"error":"Backend connection failed"}`
- Produces: music network failure `502`
- Preserves: backend 4xx/5xx status and JSON for completed requests

- [ ] **Step 1: Add failing GET proxy timeout tests**

Add to `frontend/src/app/api/backend/[...path]/route.test.ts`:

```typescript
it('returns 504 when a backend GET exceeds thirty seconds', async () => {
  jest.useFakeTimers();
  global.fetch = jest.fn((_url, init) => new Promise((_resolve, reject) => {
    const signal = (init as RequestInit).signal;
    signal?.addEventListener('abort', () => {
      reject(new DOMException('Aborted', 'AbortError'));
    });
  })) as jest.Mock;

  const responsePromise = GET(
    new NextRequest('https://frontend/api/backend/flipbook/book-1'),
    { params: Promise.resolve({ path: ['flipbook', 'book-1'] }) },
  );
  await jest.advanceTimersByTimeAsync(30000);
  const response = await responsePromise;

  expect(response.status).toBe(504);
  expect(await response.json()).toEqual({
    error: 'Backend request timed out',
  });
  jest.useRealTimers();
});


it('returns 502 when a backend GET connection fails', async () => {
  global.fetch = jest.fn().mockRejectedValue(new TypeError('fetch failed'));

  const response = await GET(
    new NextRequest('https://frontend/api/backend/flipbook/book-1'),
    { params: Promise.resolve({ path: ['flipbook', 'book-1'] }) },
  );

  expect(response.status).toBe(502);
  expect(await response.json()).toEqual({
    error: 'Backend connection failed',
  });
});
```

Ensure `jest.useRealTimers()` also runs from `afterEach` so a failed assertion
cannot leak fake timers into another test.

- [ ] **Step 2: Replace music route fallback tests with explicit status tests**

Update `frontend/src/app/api/music/route.test.ts`:

```typescript
expect(global.fetch).toHaveBeenCalledWith(
  `${BACKEND_URL}/music/list`,
  { cache: 'no-store' },
);
```

Replace the missing configuration, network failure, and non-OK tests with:

```typescript
it('returns 503 when backend configuration is missing', async () => {
  delete process.env.NEXT_PUBLIC_BACKEND_URL;
  const response = await GET();
  expect(response.status).toBe(503);
});

it('returns 502 when backend fetch fails', async () => {
  global.fetch = jest.fn().mockRejectedValue(new Error('network error'));
  const response = await GET();
  expect(response.status).toBe(502);
});

it('preserves backend failure status', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status: 503,
  }) as jest.Mock;
  const response = await GET();
  expect(response.status).toBe(503);
});
```

- [ ] **Step 3: Run focused frontend tests and verify RED**

Run:

```bash
cd frontend
npm test -- --runInBand --runTestsByPath \
  './src/app/api/backend/[...path]/route.test.ts' \
  './src/app/api/music/route.test.ts'
```

Expected: GET proxy still returns 500, timeout never aborts, and music route
returns successful empty lists.

- [ ] **Step 4: Implement GET timeout and gateway status mapping**

In the proxy `GET`, wrap the backend fetch:

```typescript
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 30000);

try {
  const res = await fetch(url, {
    cache: 'no-store',
    signal: controller.signal,
  });
  const responseContentType = res.headers.get('content-type') || '';
  const data = responseContentType.includes('application/json')
    ? await res.json()
    : { message: await res.text() };
  return NextResponse.json(data, { status: res.status });
} catch (error) {
  if (error instanceof Error && error.name === 'AbortError') {
    return NextResponse.json(
      { error: 'Backend request timed out' },
      { status: 504 },
    );
  }
  return NextResponse.json(
    { error: 'Backend connection failed' },
    { status: 502 },
  );
} finally {
  clearTimeout(timeoutId);
}
```

Keep the frontend-only `session` path outside this fetch block.

- [ ] **Step 5: Implement uncached music fetch and status propagation**

In `frontend/src/app/api/music/route.ts`:

```typescript
if (!backendUrl) {
  return NextResponse.json(
    { error: 'Music backend is not configured' },
    { status: 503 },
  );
}

try {
  const res = await fetch(`${backendUrl}/music/list`, {
    cache: 'no-store',
  });
  if (!res.ok) {
    return NextResponse.json(
      { error: 'Music service unavailable' },
      { status: res.status },
    );
  }
  return NextResponse.json(await res.json());
} catch {
  return NextResponse.json(
    { error: 'Music backend connection failed' },
    { status: 502 },
  );
}
```

- [ ] **Step 6: Verify GREEN and frontend regressions**

Run:

```bash
cd frontend
npm test -- --runInBand
npm run type-check
npm run lint
```

Expected: all frontend tests, type-check, and lint pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add 'frontend/src/app/api/backend/[...path]/route.ts' \
  'frontend/src/app/api/backend/[...path]/route.test.ts' \
  frontend/src/app/api/music/route.ts \
  frontend/src/app/api/music/route.test.ts
git commit -m "fix: bound frontend backend requests" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Make Container Builds Reproducible and Cacheable

**Files:**
- Modify: `frontend/Dockerfile`
- Modify: `.github/workflows/azure-dev.yml`
- Test: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Produces: frontend runtime based on `node:22-alpine`
- Produces: deterministic install from `package-lock.json`
- Produces: independent GitHub Actions caches named `backend` and `frontend`

- [ ] **Step 1: Add failing Docker and workflow contract tests**

Add to `backend/tests/test_deployment_config.py`:

```python
def test_frontend_container_uses_reproducible_node_22_build():
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text()
    assert dockerfile.count("FROM node:22-alpine") == 2
    assert "RUN npm ci --legacy-peer-deps --loglevel=error" in dockerfile
    assert "RUN npm install" not in dockerfile
    assert "ENV NODE_ENV=production" in dockerfile


def test_workflow_uses_separate_buildkit_cache_scopes():
    workflow = _load_workflow()
    backend_step = _workflow_step(workflow, "Build and push backend image")
    frontend_step = _workflow_step(workflow, "Build and push frontend image")

    assert "cache-from: type=gha,scope=backend" in backend_step
    assert "cache-to: type=gha,mode=max,scope=backend" in backend_step
    assert "cache-from: type=gha,scope=frontend" in frontend_step
    assert "cache-to: type=gha,mode=max,scope=frontend" in frontend_step
```

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```bash
cd backend
python3 -m pytest -q \
  tests/test_deployment_config.py::test_frontend_container_uses_reproducible_node_22_build \
  tests/test_deployment_config.py::test_workflow_uses_separate_buildkit_cache_scopes
```

Expected: Node 20, `npm install`, legacy `ENV`, and missing cache fields fail.

- [ ] **Step 3: Update the frontend Dockerfile**

Use:

```dockerfile
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
```

- [ ] **Step 4: Add service-specific BuildKit caches**

Under the backend build step:

```yaml
cache-from: type=gha,scope=backend
cache-to: type=gha,mode=max,scope=backend
```

Under the frontend build step:

```yaml
cache-from: type=gha,scope=frontend
cache-to: type=gha,mode=max,scope=frontend
```

- [ ] **Step 5: Verify GREEN and production frontend build**

Run:

```bash
cd backend
python3 -m pytest -q \
  tests/test_deployment_config.py::test_frontend_container_uses_reproducible_node_22_build \
  tests/test_deployment_config.py::test_workflow_uses_separate_buildkit_cache_scopes
cd ../frontend
npm ci --legacy-peer-deps --loglevel=error
npm run build
```

Expected: contract tests and Next.js production build pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add frontend/Dockerfile .github/workflows/azure-dev.yml \
  backend/tests/test_deployment_config.py
git commit -m "ci: cache reproducible container builds" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Validate, Deploy, and Verify the Optimization Batch

**Files:**
- Update local-only: `.azure/deployment-plan.md`
- Verify: all changed files from Tasks 1-5

**Interfaces:**
- Consumes: all Task 1-5 commits
- Produces: synchronized `main`, successful GitHub Actions run, healthy Azure revisions
- Produces: production evidence that telemetry amplification stopped

- [ ] **Step 1: Run the complete local validation suite**

Run:

```bash
cd backend
python3 -m pytest -q tests
cd ../frontend
npm test -- --runInBand
npm run type-check
npm run lint
npm run build
cd ..
az bicep build --file infra/main.bicep
git diff --check
git status --short --branch
```

Expected:

- Backend suite has zero failures.
- Frontend suite, type-check, lint, and build pass.
- Bicep has no error and only the existing BCP334 warning.
- The worktree contains only intended commits and no uncommitted source files.

- [ ] **Step 2: Review requirements against the spec**

Read:

```bash
git --no-pager diff origin/main...HEAD
```

Confirm:

- Every backend probe uses `/healthz`.
- `GET /` remains present.
- Health telemetry is excluded.
- Azure SDK logs are WARNING.
- List responses cap `image_urls` at one.
- Detail responses retain all pages.
- SAS cache uses a separate lock and 90-minute TTL.
- Music failures are non-200 and not Next-cached.
- GET timeout is 30 seconds; POST timeout remains 10 minutes.
- Docker caches have distinct scopes.
- No PDF workflow or Azure resource was added.

- [ ] **Step 3: Run Azure preparation and validation workflows**

Invoke the `azure-prepare` skill to update `.azure/deployment-plan.md` for this
existing production modification. Set the approved context to:

```text
Subscription: e9c89382-b9fd-4856-8ae4-647988d62a44
Location: koreacentral
Resource group: rg-jjflipbook
AZD environment: jjflipbook
```

Then invoke `azure-validate`. The validation must include:

```bash
azd version
azd auth login --check-status
az bicep build --file infra/main.bicep

PARAMS=$(mktemp)
trap 'rm -f "$PARAMS"' EXIT

export AZURE_ENV_NAME=$(azd env get-value AZURE_ENV_NAME)
export AZURE_LOCATION=$(azd env get-value AZURE_LOCATION)
export ADMIN_PASSWORD=$(azd env get-value ADMIN_PASSWORD)
export INTERNAL_API_KEY=$(azd env get-value INTERNAL_API_KEY)
export SESSION_SECRET=$(azd env get-value SESSION_SECRET)
export BACKEND_IMAGE=$(az containerapp show \
  -g rg-jjflipbook -n ca-backend-3nbgqlm6mwuwo \
  --query 'properties.template.containers[0].image' -o tsv)
export FRONTEND_IMAGE=$(az containerapp show \
  -g rg-jjflipbook -n ca-frontend-3nbgqlm6mwuwo \
  --query 'properties.template.containers[0].image' -o tsv)

jq '(.parameters.environmentName.value = env.AZURE_ENV_NAME)
  | (.parameters.location.value = env.AZURE_LOCATION)
  | (.parameters.adminPassword.value = env.ADMIN_PASSWORD)
  | (.parameters.internalApiKey.value = env.INTERNAL_API_KEY)
  | (.parameters.sessionSecret.value = env.SESSION_SECRET)
  | (.parameters.backendImage.value = env.BACKEND_IMAGE)
  | (.parameters.frontendImage.value = env.FRONTEND_IMAGE)' \
  infra/main.parameters.json > "$PARAMS"

az deployment sub validate \
  --location koreacentral \
  --template-file infra/main.bicep \
  --parameters @"$PARAMS" \
  --only-show-errors -o none

az deployment sub what-if \
  --location koreacentral \
  --template-file infra/main.bicep \
  --parameters @"$PARAMS" \
  --no-pretty-print \
  --only-show-errors
```

Use resolved secure parameters from the existing AZD environment without
printing secret values. Record proof in `.azure/deployment-plan.md` and set its
status to `Validated` only after all checks pass.

- [ ] **Step 4: Deploy through the existing CI/CD recipe**

Invoke `azure-deploy`, complete its pre-deployment checklist, then push:

```bash
git push origin main
```

Capture the workflow:

```bash
SHA=$(git rev-parse HEAD)
RUN_ID=$(gh run list --commit "$SHA" --workflow azure-dev.yml \
  --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
```

Expected: image builds, public-image checks, Azure preview/provisioning, smoke
test, cleanup, and GHCR retention all pass.

- [ ] **Step 5: Verify production endpoints and deployment state**

Run:

```bash
FRONTEND='https://ca-frontend-3nbgqlm6mwuwo.thankfulpebble-55e7007e.koreacentral.azurecontainerapps.io'
test "$(curl -sS -o /dev/null -w '%{http_code}' "$FRONTEND/")" = 200
test "$(curl -sS -o /dev/null -w '%{http_code}' "$FRONTEND/api/backend/healthz")" = 200
test "$(curl -sS -o /dev/null -w '%{http_code}' "$FRONTEND/view/verification-probe")" = 200
```

Verify both active images end with the deployed commit SHA and both active
revisions report `Healthy`.

- [ ] **Step 6: Verify fresh BGM URLs**

Fetch `/api/music`, then validate three URLs without printing SAS tokens:

```python
import json
import requests

data = requests.get(f"{frontend}/api/music", timeout=30).json()
assert len(data["files"]) == 29
for url in data["files"][:3]:
    response = requests.get(
        url,
        headers={"Range": "bytes=0-0"},
        timeout=30,
    )
    assert response.status_code in {200, 206}
    assert response.headers["Content-Type"] == "audio/mpeg"
```

- [ ] **Step 7: Verify telemetry amplification stopped**

Wait at least 10 minutes after the new backend revision becomes healthy, then
query the workspace:

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(10m)
| where ContainerAppName_s == "ca-backend-3nbgqlm6mwuwo"
| where Log_s contains "Transmission succeeded"
    or Log_s contains "azsdk-python-monitor-opentelemetry-exporter"
| summarize Matches=count()
```

Expected: `Matches == 0`.

Verify health probes are absent from application telemetry:

```kusto
AppRequests
| where TimeGenerated > ago(10m)
| where Name contains "healthz"
| summarize Matches=count()
```

Expected: `Matches == 0`.

Record the post-deployment 10-minute ingestion rate. The 90% daily reduction
criterion is evaluated after a full comparable operating window, but the
immediate repeated-message checks must pass before completion.

- [ ] **Step 8: Verify live RBAC and repository synchronization**

Confirm the backend managed identity still has:

- Storage Blob Data Contributor on `st3nbgqlm6mwuwo`
- Cosmos DB Built-in Data Contributor on `cosmos-3nbgqlm6mwuwo`

Then verify:

```bash
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
test -z "$(git status --short)"
```

Update `.azure/deployment-plan.md` to `Deployed` with the commit SHA, workflow
URL, endpoint results, telemetry queries, and live RBAC proof.
