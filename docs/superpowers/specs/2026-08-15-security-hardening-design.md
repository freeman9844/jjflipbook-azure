# JJFlipBook Azure Security Hardening Design

**Date:** 2026-08-15  
**Status:** Approved  
**Scope:** The six P0/P1 findings from the repository analysis

## 1. Goals

Harden the existing Azure MVP without replacing its FastAPI, Next.js, Cosmos DB,
Blob Storage, Container Apps, azd, or Bicep architecture.

The implementation must:

1. Prevent public viewers from enumerating or reading unrelated Blob assets.
2. Reduce the frontend Container App's Azure data-plane privileges.
3. Replace the shared static authentication cookie with an expiring signed session.
4. Return an error when synchronous PDF processing fails.
5. Correct overlay selection on pages after the first page.
6. Preserve retryability and metadata when Blob deletion fails.

Public `/view/{uuid}` links and existing successful API response shapes must remain
compatible.

## 2. Chosen Approach

Use minimal-invasive hardening within the current application boundaries.

Rejected alternatives:

- Adding Key Vault and Container Apps authentication would broaden this change
  beyond the six approved findings.
- Introducing queues and worker Container Apps would improve long-running PDF
  processing, but it would change the user-facing upload contract and deployment
  topology.

## 3. Security Architecture

### 3.1 Managed identities

Create two user-assigned managed identities:

- **Backend identity:** `AcrPull`, Cosmos DB Built-in Data Contributor, and Storage
  Blob Data Contributor.
- **Frontend identity:** `AcrPull` only.

Attach the backend identity only to the backend Container App and the frontend
identity only to the frontend Container App. The frontend must not be able to
request Cosmos DB or Blob Storage data-plane tokens.

### 3.2 Blob access

Replace the cached container-level SAS with blob-scoped user-delegation SAS
tokens:

- Permission: read only.
- Resource scope: one exact blob.
- Lifetime: two hours, preserving the current viewer behavior.
- No container list permission.

`sign_url` will parse and validate URLs against the configured account and
container, extract the exact blob name, and generate a blob SAS. URLs outside the
configured Blob base URL remain unchanged.

The user-delegation key may remain cached until shortly before expiry, but each
returned SAS must be generated for one blob with `generate_blob_sas`.

Image, original PDF, and BGM responses keep their current URL fields, so public
viewer links and frontend components do not need a protocol change.

### 3.3 Administrator session

After successful backend credential verification, the Next.js proxy issues an
HttpOnly cookie containing:

- username,
- issued-at timestamp,
- absolute expiry timestamp,
- cryptographically random nonce,
- HMAC-SHA256 signature generated with `SESSION_SECRET`.

The serialized format is
`base64url(JSON payload).base64url(HMAC signature)`. The cookie receives both
`Max-Age=28800` and the matching absolute `Expires` value.

The session expires eight hours after issuance regardless of browser lifetime.
Cookie attributes remain `HttpOnly`, `Secure` in production, `SameSite=Lax`, and
`Path=/`. The proxy validates token shape, signature using a timing-safe
comparison, and expiry before allowing protected requests.

The application must fail closed:

- Production frontend startup or protected request handling must reject a missing
  or placeholder `SESSION_SECRET` or `INTERNAL_API_KEY`.
- Production backend startup must reject missing or placeholder
  `ADMIN_PASSWORD` or `INTERNAL_API_KEY`.
- Bicep sets backend `APP_ENV=production`. Development defaults may only be used
  when `APP_ENV` is `development` or `test`; frontend defaults may only be used
  outside `NODE_ENV=production`.

`localStorage.isAuthenticated` is removed as an authorization source. The client
may keep transient React state for rendering, but a protected server endpoint
must determine whether the cookie is valid. A `401` response immediately returns
the UI to the login state without requiring a page reload.

The proxy handles `GET /api/backend/session` locally and returns the validated
session username without forwarding to FastAPI. `AuthGuard` calls this endpoint
when protecting non-public routes. Logout clears the cookie and the in-memory
authentication state.

## 4. Processing and Deletion Semantics

### 4.1 PDF upload

`process_pdf_task` remains synchronous from the API caller's perspective, but it
must no longer swallow its terminal error.

On success:

- Blob uploads complete.
- Cosmos status becomes `success`.
- The upload route returns the existing success response.

On failure:

- Cosmos status becomes `failed` with a safe error message.
- Temporary files are removed.
- The processing function raises a typed processing exception.
- The upload route returns an appropriate non-2xx response and must not claim the
  document was processed successfully.

If updating the failure status also fails, preserve both errors in server logs
while returning the original processing failure to the caller.

### 4.2 Single flipbook deletion

Deletion order becomes:

1. Enumerate and delete all Blob objects under the exact flipbook prefix.
2. Delete overlays for the flipbook partition.
3. Delete the flipbook metadata item.

Blob deletion is idempotent. Missing blobs do not fail a retry. Any Blob listing
or deletion failure stops the operation before metadata deletion and produces a
non-2xx API response.

Once Blob cleanup succeeds, Cosmos cleanup proceeds. A retry tolerates missing
overlay or flipbook records.

### 4.3 Folder cascade deletion

Delete each child flipbook through the hardened single-flipbook operation. Delete
the folder item only after all child deletions succeed.

If one child fails:

- stop the cascade,
- preserve the folder,
- return an error identifying the failed child,
- retain remaining child metadata for retry.

Children deleted before the failure remain deleted; the operation is resumable
because child deletion is idempotent.

## 5. Overlay Editor

Client-side overlays receive a stable `clientId` when loaded or created. The
editor stores the selected overlay by `clientId`, never by the index of a
page-filtered array.

Editing and deletion locate the matching item in the full overlay collection.
The `clientId` is a frontend-only field and is omitted from the payload sent to
the backend. The backend continues assigning persistent overlay IDs when saving,
preserving the existing Cosmos schema.

## 6. Error Handling and Observability

- Define narrow exceptions for PDF processing and asset deletion.
- Convert them to explicit FastAPI error responses at router boundaries.
- Do not return success-shaped responses after partial failure.
- Log identifiers such as flipbook UUID and folder ID, but do not log session
  tokens, API keys, SAS tokens, passwords, or complete signed Blob URLs.
- Keep Application Insights instrumentation behavior unchanged.

## 7. Compatibility

The following remain unchanged:

- `/view/{uuid}` is publicly accessible.
- Flipbook, overlay, folder, music, and upload endpoint paths.
- Successful upload, deletion, and list response fields.
- Cosmos DB container names and partition keys.
- Blob path layout.
- `azd up` deployment workflow and two-Container-App topology.

Existing sessions become invalid after deployment because the cookie format
changes. Administrators must log in again.

## 8. Test Strategy

### Backend

- Blob SAS grants read access to one blob and contains no list permission.
- A URL outside the configured account/container is not signed.
- PDF processing failure records `failed` and propagates an exception.
- Upload returns non-2xx when processing fails.
- Blob deletion failure leaves overlays and flipbook metadata intact.
- Retrying cleanup after some blobs are already missing succeeds while metadata
  still exists.
- Folder deletion preserves the folder when a child cleanup fails.

### Frontend

- A valid signed session is accepted.
- Expired, malformed, and signature-tampered sessions are rejected.
- Login creates an eight-hour HttpOnly cookie.
- A protected `401` transitions the UI to the login state.
- Editing or deleting an overlay on page two or later changes only the selected
  overlay.

### Infrastructure

- Bicep assigns Cosmos and Blob roles only to the backend identity.
- Both identities receive only `AcrPull` at ACR scope.
- Each Container App references its intended identity.
- Bicep compiles without introducing new diagnostics.

### Regression

- Backend unit tests.
- Frontend Jest tests, type-check, lint, and production build.
- Existing public viewer and administrator dashboard flows.

## 9. Out of Scope

- Queue/worker-based asynchronous PDF processing.
- Key Vault integration.
- Container Apps built-in authentication.
- Cosmos DB or Storage private endpoints.
- Upload size and PDF content validation.
- Login rate limiting.
- Pagination changes.
- CI/CD redesign.
