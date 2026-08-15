# JJFlipBook Azure Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the six approved P0/P1 security and correctness findings while preserving public viewer links and the existing two-Container-App architecture.

**Architecture:** Keep Next.js as the public gateway and FastAPI as the internal data service. Restrict Azure data-plane access to a backend-only managed identity, issue one-blob read-only SAS URLs, replace the static cookie with an eight-hour HMAC session, and make processing/deletion failures explicit and retryable.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, Node.js `crypto`, FastAPI, Python 3.11, Azure Cosmos DB SDK, Azure Storage Blob SDK, Azure Container Apps, Bicep, Jest, Testing Library, pytest.

## Global Constraints

- Preserve unauthenticated `/view/{uuid}` access.
- Preserve successful API endpoint paths and response fields.
- Preserve Cosmos container names, partition keys, and Blob path layout.
- Use blob-scoped user-delegation SAS with read permission only and a two-hour lifetime.
- Administrator sessions expire exactly eight hours after issuance.
- Frontend managed identity receives `AcrPull` only.
- Backend managed identity receives `AcrPull`, Cosmos DB Built-in Data Contributor, and Storage Blob Data Contributor.
- Do not add Key Vault, Container Apps built-in authentication, queues, workers, private endpoints, pagination, rate limiting, or CI redesign.
- Do not log passwords, API keys, session tokens, SAS tokens, or complete signed Blob URLs.
- Follow test-driven development: add a failing focused test before each behavior change.

## File Responsibility Map

| File | Responsibility |
| --- | --- |
| `backend/database.py` | Azure client lifetime and exact-blob SAS signing |
| `backend/utils.py` | Backend secret validation, password helpers, API-key verification |
| `backend/main.py` | Production configuration validation and admin seeding |
| `backend/services/errors.py` | Typed processing and deletion exceptions |
| `backend/services/flipbook_service.py` | PDF processing result propagation and retryable cleanup order |
| `backend/routers/flipbooks.py` | Translate processing/deletion exceptions to HTTP failures |
| `backend/routers/folders.py` | Preserve folders when a child deletion fails |
| `backend/tests/test_blob_sas.py` | Blob-level SAS behavior |
| `backend/tests/test_processing_and_deletion.py` | Processing and cleanup failure semantics |
| `backend/tests/test_api_local.py` | API-level processing/deletion response behavior |
| `frontend/src/lib/session.ts` | Signed session creation, verification, and configuration |
| `frontend/src/lib/session.test.ts` | Session validity, expiry, tamper, and configuration tests |
| `frontend/src/app/api/backend/[...path]/route.ts` | Session endpoint, cookie issuance, and protected proxy authorization |
| `frontend/src/app/api/backend/[...path]/route.test.ts` | Proxy cookie and session endpoint tests |
| `frontend/src/components/AuthGuard.tsx` | Server-validated login state and expiry timer |
| `frontend/src/components/AuthGuard.test.tsx` | Auth guard public/protected/login/logout behavior |
| `frontend/src/lib/overlays.ts` | Stable overlay client IDs and immutable update helpers |
| `frontend/src/lib/overlays.test.ts` | Cross-page overlay selection regression tests |
| `frontend/src/app/edit/[bookId]/page.tsx` | Use stable IDs in the editor |
| `frontend/src/app/page.tsx` | Remove localStorage authentication and react to server authorization |
| `infra/resources.bicep` | Split frontend/backend identities and RBAC |
| `README.md` | Document signed sessions, exact-blob SAS, and split identities |

---

### Task 1: Replace Container SAS With Exact-Blob SAS

**Files:**
- Modify: `backend/database.py:1-93`
- Create: `backend/tests/test_blob_sas.py`

**Interfaces:**
- Produces: `sign_url(url: str) -> str`
- Produces: `_get_user_delegation_key() -> object`
- Preserves: `get_container(name: str)` and `get_blob_container()`
- Consumed by: `backend/routers/flipbooks.py`, `backend/routers/music.py`

- [ ] **Step 1: Write tests proving SAS is scoped to one blob**

Create `backend/tests/test_blob_sas.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import database


def test_sign_url_generates_read_only_blob_sas():
    url = f"{database.BLOB_BASE_URL}/flipbooks/20260815/book/page_1.webp"

    with (
        patch.object(database, "_get_user_delegation_key", return_value=object()),
        patch.object(database, "generate_blob_sas", return_value="sp=r&sr=b&sig=test") as generate,
    ):
        signed = database.sign_url(url)

    assert signed == f"{url}?sp=r&sr=b&sig=test"
    kwargs = generate.call_args.kwargs
    assert kwargs["blob_name"] == "flipbooks/20260815/book/page_1.webp"
    assert kwargs["permission"].read is True
    assert getattr(kwargs["permission"], "list", False) is False


def test_sign_url_does_not_sign_other_storage_urls():
    external = "https://other.blob.core.windows.net/flipbook-assets/private.pdf"
    assert database.sign_url(external) == external


def test_sign_url_does_not_sign_sibling_container():
    sibling = (
        f"https://{database.STORAGE_ACCOUNT_NAME}.blob.core.windows.net/"
        "other-container/private.pdf"
    )
    assert database.sign_url(sibling) == sibling


def test_delegation_key_is_reused_until_refresh_window():
    database._delegation_key = None
    database._delegation_key_expiry = None
    service = MagicMock()
    service.get_user_delegation_key.return_value = object()

    with patch.object(database, "BlobServiceClient", return_value=service):
        first = database._get_user_delegation_key()
        second = database._get_user_delegation_key()

    assert first is second
    assert service.get_user_delegation_key.call_count == 1
```

- [ ] **Step 2: Run the new tests and confirm the old container-SAS implementation fails**

Run:

```bash
cd backend
python -m pytest tests/test_blob_sas.py -q
```

Expected: collection or assertion failures because `generate_blob_sas`,
`_get_user_delegation_key`, and blob-scoped permissions do not exist.

- [ ] **Step 3: Implement delegated-key caching and blob SAS generation**

In `backend/database.py`:

1. Replace `generate_container_sas` and `ContainerSasPermissions` imports with:

```python
from urllib.parse import unquote, urlsplit
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContainerClient,
    generate_blob_sas,
)
```

2. Replace `_sas_token` and `_sas_expiry` with:

```python
_delegation_key = None
_delegation_key_expiry: datetime | None = None
```

3. Add:

```python
def _get_user_delegation_key():
    global _delegation_key, _delegation_key_expiry
    now = datetime.now(timezone.utc)
    with _lock:
        if (
            _delegation_key is None
            or _delegation_key_expiry is None
            or (_delegation_key_expiry - now) < timedelta(hours=2, minutes=10)
        ):
            start = now - timedelta(minutes=5)
            expiry = now + timedelta(hours=8)
            service = BlobServiceClient(
                account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net",
                credential=_get_credential(),
            )
            _delegation_key = service.get_user_delegation_key(
                key_start_time=start,
                key_expiry_time=expiry,
            )
            _delegation_key_expiry = expiry
    return _delegation_key
```

4. Replace `get_container_sas` and `sign_url` with:

```python
def sign_url(url: str) -> str:
    if not url:
        return url

    parsed = urlsplit(url)
    expected_host = f"{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    container_prefix = f"/{BLOB_CONTAINER_NAME}/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected_host
        or not parsed.path.startswith(container_prefix)
    ):
        return url

    blob_name = unquote(parsed.path[len(container_prefix):])
    if not blob_name:
        return url

    now = datetime.now(timezone.utc)
    token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=BLOB_CONTAINER_NAME,
        blob_name=blob_name,
        user_delegation_key=_get_user_delegation_key(),
        permission=BlobSasPermissions(read=True),
        start=now - timedelta(minutes=5),
        expiry=now + timedelta(hours=2),
    )
    unsigned_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return f"{unsigned_url}?{token}"
```

- [ ] **Step 4: Run the focused and backend regression tests**

Run:

```bash
cd backend
python -m pytest tests/test_blob_sas.py tests/test_api_local.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the Blob SAS hardening**

```bash
git add backend/database.py backend/tests/test_blob_sas.py
git commit -m "fix: scope asset SAS tokens to individual blobs"
```

---

### Task 2: Add Eight-Hour Signed Administrator Sessions

**Files:**
- Create: `frontend/src/lib/session.ts`
- Create: `frontend/src/lib/session.test.ts`
- Modify: `frontend/src/app/api/backend/[...path]/route.ts:1-140`
- Create: `frontend/src/app/api/backend/[...path]/route.test.ts`
- Modify: `frontend/src/components/AuthGuard.tsx:1-75`
- Modify: `frontend/src/components/AuthGuard.test.tsx:1-39`
- Modify: `frontend/src/app/page.tsx:1-220`

**Interfaces:**
- Produces: `createSessionToken(username: string, nowSeconds?: number, nonce?: string) -> string`
- Produces: `verifySessionToken(token: string | undefined, nowSeconds?: number) -> SessionPayload | null`
- Produces: `SESSION_TTL_SECONDS = 28800`
- Proxy endpoint: `GET /api/backend/session -> { authenticated: true, username, expiresAt }`
- Consumed by: backend proxy route and `AuthGuard`

- [ ] **Step 1: Write session unit tests**

Create `frontend/src/lib/session.test.ts`:

```typescript
import {
  SESSION_TTL_SECONDS,
  createSessionToken,
  verifySessionToken,
} from './session';

describe('signed administrator sessions', () => {
  beforeEach(() => {
    process.env.SESSION_SECRET = 'test-session-secret-at-least-32-bytes';
  });

  afterEach(() => {
    delete process.env.SESSION_SECRET;
  });

  it('accepts a valid token and fixes expiry at eight hours', () => {
    const token = createSessionToken('admin', 1_000, 'fixed-nonce');
    const payload = verifySessionToken(token, 1_001);

    expect(payload).toEqual({
      username: 'admin',
      iat: 1_000,
      exp: 1_000 + SESSION_TTL_SECONDS,
      nonce: 'fixed-nonce',
    });
  });

  it('rejects an expired token', () => {
    const token = createSessionToken('admin', 1_000, 'fixed-nonce');
    expect(verifySessionToken(token, 1_000 + SESSION_TTL_SECONDS)).toBeNull();
  });

  it('rejects a tampered payload', () => {
    const token = createSessionToken('admin', 1_000, 'fixed-nonce');
    const [payload, signature] = token.split('.');
    const tampered = `${payload.slice(0, -1)}A.${signature}`;
    expect(verifySessionToken(tampered, 1_001)).toBeNull();
  });

  it('rejects malformed tokens', () => {
    expect(verifySessionToken('not-a-session', 1_000)).toBeNull();
  });

  it('fails closed without a production session secret', () => {
    delete process.env.SESSION_SECRET;
    const originalNodeEnv = process.env.NODE_ENV;
    Object.defineProperty(process.env, 'NODE_ENV', {
      value: 'production',
      configurable: true,
    });

    expect(() => createSessionToken('admin', 1_000, 'nonce')).toThrow(
      'SESSION_SECRET must be configured',
    );

    Object.defineProperty(process.env, 'NODE_ENV', {
      value: originalNodeEnv,
      configurable: true,
    });
  });
});
```

- [ ] **Step 2: Run the session tests and confirm they fail**

Run:

```bash
cd frontend
npm test -- --runInBand src/lib/session.test.ts
```

Expected: fail because `src/lib/session.ts` does not exist.

- [ ] **Step 3: Implement the signed-session module**

Create `frontend/src/lib/session.ts`:

```typescript
import {
  createHmac,
  randomBytes,
  timingSafeEqual,
} from 'node:crypto';

export const SESSION_TTL_SECONDS = 8 * 60 * 60;

export interface SessionPayload {
  username: string;
  iat: number;
  exp: number;
  nonce: string;
}

const LEGACY_DEFAULT = 'simple-mvp-session-secret-123';

function sessionSecret(): string {
  const value = process.env.SESSION_SECRET;
  if (
    process.env.NODE_ENV === 'production'
    && (!value || value === LEGACY_DEFAULT || value.length < 32)
  ) {
    throw new Error('SESSION_SECRET must be configured with at least 32 characters');
  }
  return value || LEGACY_DEFAULT;
}

function encode(value: string | Buffer): string {
  return Buffer.from(value).toString('base64url');
}

function signature(encodedPayload: string): Buffer {
  return createHmac('sha256', sessionSecret()).update(encodedPayload).digest();
}

export function createSessionToken(
  username: string,
  nowSeconds = Math.floor(Date.now() / 1000),
  nonce = randomBytes(16).toString('base64url'),
): string {
  const payload: SessionPayload = {
    username,
    iat: nowSeconds,
    exp: nowSeconds + SESSION_TTL_SECONDS,
    nonce,
  };
  const encodedPayload = encode(JSON.stringify(payload));
  return `${encodedPayload}.${encode(signature(encodedPayload))}`;
}

export function verifySessionToken(
  token: string | undefined,
  nowSeconds = Math.floor(Date.now() / 1000),
): SessionPayload | null {
  if (!token) return null;

  const parts = token.split('.');
  if (parts.length !== 2) return null;
  const [encodedPayload, encodedSignature] = parts;

  try {
    const expected = signature(encodedPayload);
    const actual = Buffer.from(encodedSignature, 'base64url');
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      return null;
    }

    const payload = JSON.parse(
      Buffer.from(encodedPayload, 'base64url').toString('utf8'),
    ) as SessionPayload;
    if (
      payload.username.length === 0
      || !Number.isInteger(payload.iat)
      || !Number.isInteger(payload.exp)
      || payload.exp <= nowSeconds
      || payload.exp - payload.iat !== SESSION_TTL_SECONDS
      || payload.nonce.length === 0
    ) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Change the proxy to use signed sessions**

In `frontend/src/app/api/backend/[...path]/route.ts`:

1. Import `createSessionToken`, `verifySessionToken`, and
   `SESSION_TTL_SECONDS`.
2. Delete the static `SESSION_TOKEN`.
3. Replace `isAuthenticated` with:

```typescript
function sessionFor(request: NextRequest) {
  return verifySessionToken(request.cookies.get('auth_token')?.value);
}
```

4. Handle `GET session` before constructing the backend URL:

```typescript
if (pathStr === 'session') {
  const session = sessionFor(request);
  if (!session) {
    return NextResponse.json({ authenticated: false }, { status: 401 });
  }
  return NextResponse.json({
    authenticated: true,
    username: session.username,
    expiresAt: session.exp,
  });
}
```

5. Use `sessionFor(request)` for all protected GET, POST, and DELETE checks.
6. On successful login:

```typescript
const token = createSessionToken(data.username);
const session = verifySessionToken(token);
if (!session) throw new Error('Failed to create session');
resObj.cookies.set('auth_token', token, {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'lax',
  path: '/',
  maxAge: SESSION_TTL_SECONDS,
  expires: new Date(session.exp * 1000),
});
```

7. Remove all production fallbacks for `INTERNAL_API_KEY`. Add:

```typescript
function internalApiKey(): string {
  const value = process.env.INTERNAL_API_KEY;
  if (process.env.NODE_ENV === 'production' && (!value || value === 'secret_dev_key')) {
    throw new Error('INTERNAL_API_KEY must be configured');
  }
  return value || 'secret_dev_key';
}
```

- [ ] **Step 5: Test proxy cookie issuance and the local session endpoint**

Create `frontend/src/app/api/backend/[...path]/route.test.ts`:

```typescript
/** @jest-environment node */
import { NextRequest } from 'next/server';
import { GET, POST } from './route';

describe('/api/backend proxy sessions', () => {
  beforeEach(() => {
    process.env.SESSION_SECRET = 'test-session-secret-at-least-32-bytes';
    process.env.INTERNAL_API_KEY = 'test-internal-api-key';
    process.env.NEXT_PUBLIC_BACKEND_URL = 'https://backend.internal';
    jest.clearAllMocks();
  });

  afterEach(() => {
    delete process.env.SESSION_SECRET;
    delete process.env.INTERNAL_API_KEY;
    delete process.env.NEXT_PUBLIC_BACKEND_URL;
  });

  it('issues an eight-hour HttpOnly cookie after login', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({
        authenticated: true,
        username: 'admin',
        status: 'ok',
      }),
    }) as jest.Mock;

    const request = new NextRequest('https://frontend/api/backend/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'password' }),
    });
    const response = await POST(request, {
      params: Promise.resolve({ path: ['login'] }),
    });

    expect(response.status).toBe(200);
    const cookie = response.headers.get('set-cookie') || '';
    expect(cookie).toContain('auth_token=');
    expect(cookie.toLowerCase()).toContain('httponly');
    expect(cookie).toContain('Max-Age=28800');
    expect(cookie).toContain('Expires=');
  });

  it('returns the validated session without forwarding to FastAPI', async () => {
    const loginRequest = new NextRequest('https://frontend/api/backend/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'password' }),
    });
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ authenticated: true, username: 'admin' }),
    }) as jest.Mock;
    const loginResponse = await POST(loginRequest, {
      params: Promise.resolve({ path: ['login'] }),
    });
    const cookie = (loginResponse.headers.get('set-cookie') || '').split(';')[0];
    (global.fetch as jest.Mock).mockClear();

    const response = await GET(
      new NextRequest('https://frontend/api/backend/session', {
        headers: { cookie },
      }),
      { params: Promise.resolve({ path: ['session'] }) },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(expect.objectContaining({
      authenticated: true,
      username: 'admin',
    }));
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
```

Run:

```bash
cd frontend
npm test -- --runInBand 'src/app/api/backend/[...path]/route.test.ts'
```

Expected: tests fail until the signed proxy changes are complete, then pass.

- [ ] **Step 6: Rewrite AuthGuard tests around the server session**

Replace localStorage-based expectations in
`frontend/src/components/AuthGuard.test.tsx` with:

```typescript
import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import AuthGuard from './AuthGuard';

jest.mock('next/navigation', () => ({
  usePathname: () => '/',
}));

describe('AuthGuard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders protected content after server session validation', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        username: 'admin',
        expiresAt: Math.floor(Date.now() / 1000) + 3600,
      }),
    }) as jest.Mock;

    render(<AuthGuard><div>Protected Content</div></AuthGuard>);
    expect(await screen.findByText('Protected Content')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith('/api/backend/session', {
      cache: 'no-store',
    });
  });

  it('shows login when session validation returns 401', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 }) as jest.Mock;
    render(<AuthGuard><div>Protected Content</div></AuthGuard>);
    expect(await screen.findByText('JJFlipBook 로그인')).toBeInTheDocument();
  });

  it('sets authenticated state after successful login', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({ ok: true });

    render(<AuthGuard><div>Protected Content</div></AuthGuard>);
    await screen.findByText('JJFlipBook 로그인');
    fireEvent.change(screen.getByPlaceholderText('아이디'), {
      target: { value: 'admin' },
    });
    fireEvent.change(screen.getByPlaceholderText('비밀번호'), {
      target: { value: 'password' },
    });
    fireEvent.click(screen.getByText('로그인'));

    expect(await screen.findByText('Protected Content')).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Implement server-validated AuthGuard state**

In `frontend/src/components/AuthGuard.tsx`:

- Treat `/view/` as public before starting session validation.
- Fetch `/api/backend/session` with `cache: 'no-store'`.
- Store only React state; remove every `localStorage` call.
- Schedule `setIsLoggedIn(false)` for `expiresAt * 1000 - Date.now()`.
- Set `isLoggedIn` to `true` after a successful login.
- Export `useAuth()` from this module. Its context value is:

```typescript
interface AuthContextValue {
  logout: () => void;
}
```

The provider wraps `children` and implements `logout` as
`setIsLoggedIn(false)`.

Use this state shape:

```typescript
interface SessionResponse {
  authenticated: boolean;
  username: string;
  expiresAt: number;
}
```

- [ ] **Step 8: Remove dashboard localStorage usage**

In `frontend/src/app/page.tsx`:

- Remove `localStorage.removeItem("isAuthenticated")` from failed list fetches.
- Remove it from `handleLogout`.
- Import `useAuth` and call `logout()` after `POST /api/backend/logout`
  succeeds instead of calling `router.refresh()`.
- Preserve the current dashboard UI and request paths.

- [ ] **Step 9: Run frontend session, proxy, guard, type, and lint checks**

Run:

```bash
cd frontend
npm test -- --runInBand src/lib/session.test.ts src/components/AuthGuard.test.tsx
npm test -- --runInBand 'src/app/api/backend/[...path]/route.test.ts'
npm run type-check
npm run lint
```

Expected: all commands pass.

- [ ] **Step 10: Commit signed sessions**

```bash
git add \
  frontend/src/lib/session.ts \
  frontend/src/lib/session.test.ts \
  frontend/src/app/api/backend/[...path]/route.ts \
  frontend/src/app/api/backend/[...path]/route.test.ts \
  frontend/src/components/AuthGuard.tsx \
  frontend/src/components/AuthGuard.test.tsx \
  frontend/src/app/page.tsx
git commit -m "fix: replace static auth cookie with signed sessions"
```

---

### Task 3: Fail Closed on Backend Secrets and Split Azure Identities

**Files:**
- Modify: `backend/utils.py:1-15`
- Modify: `backend/main.py:1-100`
- Modify: `backend/tests/conftest.py:1-48`
- Create: `backend/tests/test_runtime_config.py`
- Modify: `infra/resources.bicep:1-344`

**Interfaces:**
- Produces: `validate_runtime_config() -> None`
- Produces: `required_setting(name: str, development_default: str | None = None) -> str`
- Bicep produces: separate `backendIdentity` and `frontendIdentity`
- Consumed by: backend startup and API-key verification

- [ ] **Step 1: Write backend configuration tests**

Create `backend/tests/test_runtime_config.py`:

```python
from unittest.mock import patch

import pytest

from utils import required_setting, validate_runtime_config


def test_production_rejects_missing_required_settings():
    with patch.dict(
        "os.environ",
        {"APP_ENV": "production"},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            validate_runtime_config()


def test_production_rejects_legacy_defaults():
    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "ADMIN_PASSWORD": "admin",
            "INTERNAL_API_KEY": "secret_dev_key",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            validate_runtime_config()


def test_test_environment_allows_explicit_development_defaults():
    with patch.dict("os.environ", {"APP_ENV": "test"}, clear=True):
        assert required_setting("INTERNAL_API_KEY", "secret_dev_key") == "secret_dev_key"
```

- [ ] **Step 2: Run the tests and confirm configuration helpers are missing**

Run:

```bash
cd backend
python -m pytest tests/test_runtime_config.py -q
```

Expected: import failure for `required_setting` and `validate_runtime_config`.

- [ ] **Step 3: Implement backend configuration validation**

In `backend/utils.py`, add:

```python
_INSECURE_DEFAULTS = {
    "ADMIN_PASSWORD": {"admin"},
    "INTERNAL_API_KEY": {"secret_dev_key"},
}


def required_setting(name: str, development_default: str | None = None) -> str:
    app_env = os.getenv("APP_ENV", "development")
    value = os.getenv(name)
    if app_env in {"development", "test"}:
        if value:
            return value
        if development_default is not None:
            return development_default
    if not value or value in _INSECURE_DEFAULTS.get(name, set()):
        raise RuntimeError(f"{name} must be configured securely")
    return value


def validate_runtime_config() -> None:
    required_setting("ADMIN_PASSWORD", "admin")
    required_setting("INTERNAL_API_KEY", "secret_dev_key")
```

Change `verify_api_key` to:

```python
import hmac

def verify_api_key(x_api_key: str = Header(None)):
    expected = required_setting("INTERNAL_API_KEY", "secret_dev_key")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Internal API Key")
    return True
```

In `backend/main.py`:

- Import `required_setting` and `validate_runtime_config`.
- Call `validate_runtime_config()` at the start of `lifespan`.
- Replace the base64 fallback with:

```python
admin_password = required_setting("ADMIN_PASSWORD", "admin")
```

Remove the `base64` import and encoded fallback.

In `backend/tests/conftest.py`, before importing application modules, add:

```python
os.environ.setdefault("APP_ENV", "test")
```

- [ ] **Step 4: Run backend configuration and API tests**

Run:

```bash
cd backend
python -m pytest tests/test_runtime_config.py tests/test_api_local.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Split Bicep identities and RBAC**

In `infra/resources.bicep`:

1. Replace `identity` with:

```bicep
resource backendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-backend-${resourceToken}'
  location: location
  tags: tags
}

resource frontendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-frontend-${resourceToken}'
  location: location
  tags: tags
}
```

2. Create one `AcrPull` assignment per identity:

```bicep
resource backendAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, backendIdentity.id, 'acrpull')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: backendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource frontendAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, frontendIdentity.id, 'acrpull')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: frontendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
```

3. Point Storage and Cosmos role assignments only at `backendIdentity`.
4. Attach each Container App to its matching identity.
5. Configure each registry reference with its matching identity.
6. Keep `AZURE_CLIENT_ID` only on the backend and set:

```bicep
{ name: 'APP_ENV', value: 'production' }
```

7. Update `dependsOn` so backend depends on `backendAcrPull`,
   `blobContributor`, and `cosmosDataContributor`; frontend depends on
   `frontendAcrPull`.

- [ ] **Step 6: Compile and statically inspect Bicep**

Run:

```bash
az bicep build --file infra/main.bicep --stdout >/dev/null
rg -n "backendIdentity|frontendIdentity|principalId|userAssignedIdentities" infra/resources.bicep
```

Expected:

- Bicep build succeeds.
- Blob and Cosmos assignments reference only `backendIdentity`.
- Frontend Container App references only `frontendIdentity`.
- No new Bicep diagnostic is introduced.

- [ ] **Step 7: Commit secret validation and identity separation**

```bash
git add \
  backend/utils.py \
  backend/main.py \
  backend/tests/conftest.py \
  backend/tests/test_runtime_config.py \
  infra/resources.bicep
git commit -m "fix: isolate Azure identities and validate secrets"
```

---

### Task 4: Propagate PDF Processing Failure to the Upload API

**Files:**
- Create: `backend/services/errors.py`
- Modify: `backend/services/flipbook_service.py:45-113`
- Modify: `backend/routers/flipbooks.py:31-69`
- Modify: `backend/tests/test_api_local.py:1-85`
- Create: `backend/tests/test_processing_and_deletion.py`

**Interfaces:**
- Produces: `class PdfProcessingError(RuntimeError)`
- Produces: `process_pdf_task(...) -> None`, raising `PdfProcessingError` on failure
- Router maps: `PdfProcessingError -> HTTP 500 {"detail": "PDF processing failed"}`

- [ ] **Step 1: Write service and API failure tests**

Create the initial processing section of
`backend/tests/test_processing_and_deletion.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.errors import PdfProcessingError
from services.flipbook_service import process_pdf_task


@patch("pdf_utils.convert_pdf_to_images", side_effect=RuntimeError("poppler failed"))
@patch("services.flipbook_service.get_container")
def test_processing_failure_records_failed_and_raises(mock_get_container, _convert, tmp_path):
    flipbooks = MagicMock()
    mock_get_container.return_value = flipbooks
    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    work_dir = tmp_path / "book"
    work_dir.mkdir()

    with pytest.raises(PdfProcessingError, match="PDF processing failed"):
        process_pdf_task(
            str(pdf_path),
            str(work_dir),
            "book-id",
            "20260815",
            True,
        )

    operations = flipbooks.patch_item.call_args.kwargs["patch_operations"]
    assert {"op": "set", "path": "/status", "value": "failed"} in operations
    assert not work_dir.exists()
```

Add to `backend/tests/test_api_local.py`:

```python
@patch(
    "routers.flipbooks.process_pdf_task",
    side_effect=PdfProcessingError("PDF processing failed"),
)
@patch("routers.flipbooks.get_container")
def test_upload_returns_error_when_processing_fails(mock_get_container, _process):
    mock_get_container.return_value = MagicMock()
    test_pdf_path = os.path.join(os.path.dirname(__file__), "test_data", "sample.pdf")
    with open(test_pdf_path, "rb") as file:
        response = client.post(
            "/upload",
            files={"file": ("failed.pdf", file, "application/pdf")},
            headers={"x-api-key": "secret_dev_key"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "PDF processing failed"}
```

Import `PdfProcessingError` in the test module.

- [ ] **Step 2: Run the processing tests and confirm failure**

Run:

```bash
cd backend
python -m pytest \
  tests/test_processing_and_deletion.py::test_processing_failure_records_failed_and_raises \
  tests/test_api_local.py::test_upload_returns_error_when_processing_fails \
  -q
```

Expected: import failure because `services.errors` does not exist.

- [ ] **Step 3: Add typed service exceptions**

Create `backend/services/errors.py`:

```python
class PdfProcessingError(RuntimeError):
    pass


class AssetDeletionError(RuntimeError):
    def __init__(self, uuid_key: str):
        super().__init__(f"Asset deletion failed for flipbook {uuid_key}")
        self.uuid_key = uuid_key
```

- [ ] **Step 4: Raise processing errors after recording failure**

In `backend/services/flipbook_service.py`:

- Import `PdfProcessingError`.
- Keep the current failed-status patch.
- Never include the raw exception in an HTTP response.
- After the failure-status patch attempt, add:

```python
raise PdfProcessingError("PDF processing failed") from e
```

- Keep temporary directory deletion in `finally`.

In `backend/routers/flipbooks.py`, wrap the threadpool call:

```python
try:
    await run_in_threadpool(
        process_pdf_task,
        pdf_path,
        book_dir,
        book.uuid_key,
        date_str,
        split_pages,
    )
except PdfProcessingError as exc:
    raise HTTPException(status_code=500, detail="PDF processing failed") from exc
```

- [ ] **Step 5: Run processing and API tests**

Run:

```bash
cd backend
python -m pytest \
  tests/test_processing_and_deletion.py::test_processing_failure_records_failed_and_raises \
  tests/test_api_local.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit explicit processing failures**

```bash
git add \
  backend/services/errors.py \
  backend/services/flipbook_service.py \
  backend/routers/flipbooks.py \
  backend/tests/test_processing_and_deletion.py \
  backend/tests/test_api_local.py
git commit -m "fix: return upload errors when PDF processing fails"
```

---

### Task 5: Make Flipbook and Folder Deletion Retryable

**Files:**
- Modify: `backend/services/flipbook_service.py:18-43`
- Modify: `backend/routers/flipbooks.py:115-123`
- Modify: `backend/routers/folders.py:27-50`
- Modify: `backend/tests/test_processing_and_deletion.py`
- Modify: `backend/tests/test_api_local.py`

**Interfaces:**
- Consumes: `AssetDeletionError(uuid_key: str)` from Task 4
- Produces: `delete_single_flipbook(uuid_key: str, date_str: str = "") -> None`
- Router maps: `AssetDeletionError -> HTTP 502`

- [ ] **Step 1: Add tests for deletion ordering and failure preservation**

Append to `backend/tests/test_processing_and_deletion.py`:

```python
from services.errors import AssetDeletionError
from services.flipbook_service import delete_single_flipbook


@patch("services.flipbook_service.get_blob_container")
@patch("services.flipbook_service.get_container")
def test_blob_delete_failure_preserves_cosmos_metadata(mock_get_container, mock_blob):
    overlays = MagicMock()
    flipbooks = MagicMock()
    mock_get_container.side_effect = lambda name: {
        "overlays": overlays,
        "flipbooks": flipbooks,
    }[name]
    blob = MagicMock()
    blob.list_blobs.return_value = [MagicMock(name="flipbooks/20260815/id/page.webp")]
    blob.delete_blob.side_effect = RuntimeError("storage unavailable")
    mock_blob.return_value = blob

    with pytest.raises(AssetDeletionError):
        delete_single_flipbook("id", "20260815")

    overlays.query_items.assert_not_called()
    overlays.delete_item.assert_not_called()
    flipbooks.delete_item.assert_not_called()


@patch("services.flipbook_service.get_blob_container")
@patch("services.flipbook_service.get_container")
def test_retry_after_partial_blob_cleanup_deletes_metadata(mock_get_container, mock_blob):
    overlays = MagicMock()
    overlays.query_items.return_value = [{"id": "overlay-1"}]
    flipbooks = MagicMock()
    mock_get_container.side_effect = lambda name: {
        "overlays": overlays,
        "flipbooks": flipbooks,
    }[name]
    blob = MagicMock()
    blob.list_blobs.return_value = []
    mock_blob.return_value = blob

    delete_single_flipbook("id", "20260815")

    overlays.delete_item.assert_called_once_with(
        item="overlay-1",
        partition_key="id",
    )
    flipbooks.delete_item.assert_called_once_with(item="id", partition_key="id")
```

Add this router-level folder test to `backend/tests/test_api_local.py`:

```python
@patch("routers.folders.delete_single_flipbook", side_effect=AssetDeletionError("book-1"))
@patch("routers.folders.get_container")
def test_folder_delete_failure_preserves_folder(mock_get_container, _delete):
    folders = MagicMock()
    folders.read_item.return_value = {"id": "folder-1"}
    flipbooks = MagicMock()
    flipbooks.query_items.return_value = [
        {"id": "book-1", "date_folder": "20260815"},
    ]
    mock_get_container.side_effect = lambda name: {
        "folders": folders,
        "flipbooks": flipbooks,
    }[name]

    response = client.delete(
        "/folder/folder-1",
        headers={"x-api-key": "secret_dev_key"},
    )

    assert response.status_code == 502
    folders.delete_item.assert_not_called()
```

- [ ] **Step 2: Run deletion tests and confirm the old implementation fails**

Run:

```bash
cd backend
python -m pytest tests/test_processing_and_deletion.py tests/test_api_local.py -q
```

Expected: failure because metadata is deleted before Blob cleanup and Blob errors
are swallowed.

- [ ] **Step 3: Reorder deletion and propagate Blob failures**

Refactor `delete_single_flipbook` in
`backend/services/flipbook_service.py`:

```python
def delete_single_flipbook(uuid_key: str, date_str: str = ""):
    prefix = (
        f"flipbooks/{date_str}/{uuid_key}/"
        if date_str
        else f"flipbooks/{uuid_key}/"
    )

    try:
        blob_container = get_blob_container()
        blob_names = [
            blob.name
            for blob in blob_container.list_blobs(name_starts_with=prefix)
        ]
        if blob_names:
            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(blob_container.delete_blob, blob_names))
    except Exception as exc:
        logger.error("Blob cleanup failed for flipbook %s", uuid_key, exc_info=True)
        raise AssetDeletionError(uuid_key) from exc

    overlays = get_container("overlays")
    overlay_ids = [
        item["id"]
        for item in overlays.query_items(
            query="SELECT c.id FROM c",
            partition_key=uuid_key,
        )
    ]
    for overlay_id in overlay_ids:
        overlays.delete_item(item=overlay_id, partition_key=uuid_key)

    try:
        get_container("flipbooks").delete_item(
            item=uuid_key,
            partition_key=uuid_key,
        )
    except CosmosResourceNotFoundError:
        pass
```

Import `AssetDeletionError`.

- [ ] **Step 4: Map deletion failures at router boundaries**

In `backend/routers/flipbooks.py`:

```python
try:
    delete_single_flipbook(uuid_key, date_str)
except AssetDeletionError as exc:
    raise HTTPException(
        status_code=502,
        detail="Flipbook assets could not be deleted",
    ) from exc
```

In `backend/routers/folders.py`, wrap each child:

```python
try:
    delete_single_flipbook(fb["id"], fb.get("date_folder", ""))
except AssetDeletionError as exc:
    raise HTTPException(
        status_code=502,
        detail=f"Failed to delete child flipbook {fb['id']}",
    ) from exc
```

Keep `folders.delete_item` after the entire loop.

- [ ] **Step 5: Run all backend tests**

Run:

```bash
cd backend
python -m pytest tests/ -q
```

Expected: all backend tests pass.

- [ ] **Step 6: Commit retryable deletion semantics**

```bash
git add \
  backend/services/flipbook_service.py \
  backend/routers/flipbooks.py \
  backend/routers/folders.py \
  backend/tests/test_processing_and_deletion.py \
  backend/tests/test_api_local.py
git commit -m "fix: preserve metadata when asset deletion fails"
```

---

### Task 6: Fix Cross-Page Overlay Editing With Stable Client IDs

**Files:**
- Create: `frontend/src/lib/overlays.ts`
- Create: `frontend/src/lib/overlays.test.ts`
- Modify: `frontend/src/app/edit/[bookId]/page.tsx:1-291`

**Interfaces:**
- Produces: `EditableOverlay` with `clientId: string`
- Produces: `hydrateOverlays(overlays: OverlayInput[]) -> EditableOverlay[]`
- Produces: `updateOverlay(overlays, clientId, patch) -> EditableOverlay[]`
- Produces: `removeOverlay(overlays, clientId) -> EditableOverlay[]`
- Produces: `serializeOverlays(overlays) -> OverlayInput[]`
- Consumed by: overlay editor only

- [ ] **Step 1: Write the cross-page regression tests**

Create `frontend/src/lib/overlays.test.ts`:

```typescript
import {
  hydrateOverlays,
  removeOverlay,
  serializeOverlays,
  updateOverlay,
} from './overlays';

const source = [
  {
    id: 'page-1-overlay',
    page: 1,
    type: 'link',
    x: 1,
    y: 2,
    width: 10,
    height: 20,
    data_url: 'https://one.example',
  },
  {
    id: 'page-2-overlay',
    page: 2,
    type: 'link',
    x: 3,
    y: 4,
    width: 10,
    height: 20,
    data_url: 'https://two.example',
  },
];

describe('overlay editor helpers', () => {
  it('updates the selected page-two overlay without changing page one', () => {
    const overlays = hydrateOverlays(source, () => 'generated');
    const updated = updateOverlay(overlays, 'page-2-overlay', {
      data_url: 'https://updated.example',
    });

    expect(updated[0].data_url).toBe('https://one.example');
    expect(updated[1].data_url).toBe('https://updated.example');
  });

  it('removes only the selected overlay', () => {
    const overlays = hydrateOverlays(source, () => 'generated');
    const remaining = removeOverlay(overlays, 'page-2-overlay');
    expect(remaining.map((item) => item.id)).toEqual(['page-1-overlay']);
  });

  it('does not send clientId to the backend', () => {
    const overlays = hydrateOverlays(source, () => 'generated');
    expect(serializeOverlays(overlays)[0]).not.toHaveProperty('clientId');
  });
});
```

- [ ] **Step 2: Run the test and confirm the helper is missing**

Run:

```bash
cd frontend
npm test -- --runInBand src/lib/overlays.test.ts
```

Expected: fail because `src/lib/overlays.ts` does not exist.

- [ ] **Step 3: Implement stable overlay helpers**

Create `frontend/src/lib/overlays.ts`:

```typescript
export interface OverlayInput {
  id?: string;
  page: number;
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  data_url: string;
}

export interface EditableOverlay extends OverlayInput {
  clientId: string;
}

function newClientId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random()}`;
}

export function hydrateOverlays(
  overlays: OverlayInput[],
  createId: () => string = newClientId,
): EditableOverlay[] {
  return overlays.map((overlay) => ({
    ...overlay,
    clientId: overlay.id || createId(),
  }));
}

export function updateOverlay(
  overlays: EditableOverlay[],
  clientId: string,
  patch: Partial<OverlayInput>,
): EditableOverlay[] {
  return overlays.map((overlay) => (
    overlay.clientId === clientId ? { ...overlay, ...patch } : overlay
  ));
}

export function removeOverlay(
  overlays: EditableOverlay[],
  clientId: string,
): EditableOverlay[] {
  return overlays.filter((overlay) => overlay.clientId !== clientId);
}

export function serializeOverlays(overlays: EditableOverlay[]): OverlayInput[] {
  return overlays.map(({ clientId: _clientId, ...overlay }) => overlay);
}
```

- [ ] **Step 4: Integrate stable IDs into the editor**

In `frontend/src/app/edit/[bookId]/page.tsx`:

- Import all helper functions and types.
- Change `overlays` state to `EditableOverlay[]`.
- Change `selectedOverlayIndex` to `selectedOverlayId: string | null`.
- Hydrate API results with `hydrateOverlays`.
- Give newly drawn overlays a generated client ID by hydrating the one new item.
- Render with `key={overlay.clientId}`.
- Select `overlay.clientId`, never the filtered array index.
- Update using `updateOverlay`.
- Delete using `removeOverlay`.
- Send `JSON.stringify(serializeOverlays(overlays))`.

The page filter remains:

```typescript
overlays
  .filter((overlay) => overlay.page === activePage)
  .map((overlay) => (
    <div key={overlay.clientId} ... />
  ))
```

- [ ] **Step 5: Run overlay tests and frontend checks**

Run:

```bash
cd frontend
npm test -- --runInBand src/lib/overlays.test.ts
npm run type-check
npm run lint
```

Expected: all commands pass.

- [ ] **Step 6: Commit the editor fix**

```bash
git add \
  frontend/src/lib/overlays.ts \
  frontend/src/lib/overlays.test.ts \
  frontend/src/app/edit/[bookId]/page.tsx
git commit -m "fix: edit overlays by stable client identifier"
```

---

### Task 7: Update Documentation and Run Full Validation

**Files:**
- Modify: `README.md:1-240`
- Validate: `backend/`
- Validate: `frontend/`
- Validate: `infra/main.bicep`

**Interfaces:**
- Documents all interfaces introduced in Tasks 1-6.
- Adds no new runtime behavior.

- [ ] **Step 1: Update security and deployment documentation**

In `README.md`:

- Replace “container SAS” wording with “exact-blob read-only user-delegation
  SAS”.
- State that public viewers cannot list the Blob container.
- Document separate frontend and backend managed identities and their roles.
- Replace the static-session description with HMAC-SHA256 signed, eight-hour
  HttpOnly sessions.
- State that existing sessions are invalidated after this deployment.
- Document that production secrets have no fallback and startup fails if they
  are missing or use legacy defaults.
- Update deletion behavior: Blob cleanup completes before Cosmos metadata is
  removed, and failures remain retryable.
- Keep the existing `azd env set` commands unchanged.

- [ ] **Step 2: Run the full backend test suite**

Run:

```bash
cd backend
python -m pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 3: Run all frontend checks**

Run:

```bash
cd frontend
npm test -- --runInBand
npm run type-check
npm run lint
npm run build
```

Expected: all commands pass and Next.js produces routes for `/`,
`/api/backend/[...path]`, `/api/music`, `/edit/[bookId]`, and `/view/[uuidKey]`.

- [ ] **Step 4: Compile Bicep and inspect the generated template**

Run:

```bash
az bicep build --file infra/main.bicep --outfile /tmp/jjflipbook-main.json
python - <<'PY'
import json

with open("/tmp/jjflipbook-main.json", encoding="utf-8") as file:
    template = json.load(file)

text = json.dumps(template)
assert "id-backend-" in text
assert "id-frontend-" in text
assert "APP_ENV" in text
print("Bicep identity and environment checks passed")
PY
rm /tmp/jjflipbook-main.json
```

Expected: Bicep compiles and the static assertions pass.

- [ ] **Step 5: Review the final diff for secret or SAS leakage**

Run:

```bash
git --no-pager diff --check
git --no-pager diff --stat HEAD~7..HEAD
rg -n \
  "simple-mvp-session-secret-123|secret_dev_key|YWRtaW4=|ContainerSasPermissions|generate_container_sas" \
  backend frontend infra README.md
```

Expected:

- No whitespace errors.
- Legacy defaults appear only in explicit development/test validation logic and
  tests.
- No `ContainerSasPermissions` or `generate_container_sas` use remains.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md
git commit -m "docs: describe security hardening behavior"
```

- [ ] **Step 7: Review commit history**

Run:

```bash
git --no-pager log --oneline -8
git status --short
```

Expected: the design commit plus six implementation commits and one documentation
commit are visible, and the worktree is clean.
