# JJFlipBook Azure 구독 이전 배포 계획

Status: Deployed
Mode: Parallel rebuild, verified cutover, source removed
Source: 8dd0dabf-d8c0-4651-a846-5b13e18e05eb
Target: 43ab425a-c793-4f2e-b71a-0af7a14f26d2
Tenant: 1716e63d-ed31-49bf-aa16-5effd27bc340
Environment/RG: jjflipbook-p2 / rg-jjflipbook-p2
Location: koreacentral

## References

- Design: `docs/superpowers/specs/2026-08-17-azure-subscription-migration-design.md`
- Execution plan: `docs/superpowers/plans/2026-08-17-azure-subscription-migration.md`
- Deployment workflow: `.github/workflows/azure-dev.yml`
- Validation report: `.superpowers/sdd/2026-08-17-azure-subscription-migration/task-7-validation-report.md`

## Local proof files

- `.azure/migration/source-freeze.json`
- `.azure/migration/data-verification.json`
- `.azure/migration/smoke-attestation.json`
- `.azure/migration/target-preview.txt`
- `.azure/migration/task10-delete.log`
- `.superpowers/sdd/2026-08-17-azure-subscription-migration/task-9-report.md`
- `.superpowers/sdd/2026-08-17-azure-subscription-migration/task-10-report.md`

## Final deployment and cleanup proof

- GitHub repository deployment variables remain pinned to the approved target: `AZURE_CLIENT_ID=006ea06f-0f34-41f3-af8e-cde27fffcd78`, `AZURE_TENANT_ID=1716e63d-ed31-49bf-aa16-5effd27bc340`, `AZURE_SUBSCRIPTION_ID=43ab425a-c793-4f2e-b71a-0af7a14f26d2`, `AZURE_ENV_NAME=jjflipbook-p2`, `AZURE_LOCATION=koreacentral`.
- Verified Preview run `32027174495` and full cutover run `32027631815` both completed successfully for workflow `Azure deployment` on commit `f99c24b0581c747a864d6b3eaac142c0f3f3b496`.
- Target resources now serving production traffic are:
  - Resource group / environment: `rg-jjflipbook-p2` / `jjflipbook-p2`
  - Container Apps environment: `cae-goua5wx3gj5qg`
  - Backend / Frontend apps: `ca-backend-goua5wx3gj5qg` / `ca-frontend-goua5wx3gj5qg`
  - Backend UAMI: `id-backend-goua5wx3gj5qg`
  - Storage / Cosmos / App Insights / Log Analytics: `stgoua5wx3gj5qg` / `cosmos-goua5wx3gj5qg` / `appi-goua5wx3gj5qg` / `log-goua5wx3gj5qg`
- Live target Frontend URL: `https://ca-frontend-goua5wx3gj5qg.politesmoke-658170a7.koreacentral.azurecontainerapps.io`
- Cutover revisions stayed at the expected immutable SHA and remained healthy after source deletion:
  - Backend revision `ca-backend-goua5wx3gj5qg--0000001` → `ghcr.io/freeman9844/jjflipbook-azure-backend:f99c24b0581c747a864d6b3eaac142c0f3f3b496`
  - Frontend revision `ca-frontend-goua5wx3gj5qg--0000001` → `ghcr.io/freeman9844/jjflipbook-azure-frontend:f99c24b0581c747a864d6b3eaac142c0f3f3b496`
- Local cutover attestations:
  - Source freeze: `.azure/migration/source-freeze.json` sha256 `3e2954171453f4f2b11c6516290ec2c45482a8a2ceec8c972f330969ea0a29c5`
  - Smoke: `.azure/migration/smoke-attestation.json` sha256 `e62d264278b6f70158ff715168a2124090a12c8f9b5727e1057e95e263679da8`
  - Post-smoke data: `.azure/migration/data-verification.json` sha256 `e1daf8d1f5dbde3c17f97983b3ee27e4761005804cd5075c9a6c812f2d57634c`
- Blob proof from the final attestation: `91` blobs, `188996921` bytes, manifest sha256 `53deb66ebc76862e0a6beda4a78077f50395e191b6c11cfc6028f0a629b519f2`.
- Cosmos proof from the final attestation: `users=1` (sha256 `9e615e80a379f1ab03082787de1fbe3d34909e13b7291086066503f8dbabc5db`), `folders=1` (sha256 `797951d3a3bf2c0783fa28c7201bd339875d5b7d117470f48ae04ba44d4dda74`), `flipbooks=2` (sha256 `fc37af71a0e1be80b8846bb72e3883de63d1a9edf165c4964833f7b64a01ee0a`), and `source_url_references_remaining=0`.
- Source deletion was executed only after the proof gates passed by running `scripts/delete_source_environment.sh` with explicit `TARGET_COSMOS_ACCOUNT=cosmos-goua5wx3gj5qg`, `TARGET_COSMOS_ROLE_ASSIGNMENT_ID=c599b13a-108d-5125-8127-e99a7958f31b`, and confirmation token `delete:8dd0dabf-d8c0-4651-a846-5b13e18e05eb:rg-jjflipbook-p2`; the script log spans `2026-08-17T21:45:47+09:00` to `2026-08-17T22:10:00+09:00`.
- Post-delete checks proved:
  - `az group exists --subscription 8dd0dabf-d8c0-4651-a846-5b13e18e05eb --name rg-jjflipbook-p2` → `false`
  - Source OIDC subscription-scope roles for service principal `069bad89-0fee-4193-a435-02b6c988b9d2` were removed (`Contributor` and `Role Based Access Control Administrator` count `0`)
  - Temporary operator roles were removed exactly as intended: target Storage role assignment `17f5589f-39a4-5afb-9128-5b6de1415331` absent and target Cosmos SQL role assignment `c599b13a-108d-5125-8127-e99a7958f31b` absent
  - Target backend runtime access remained exact: one `Storage Blob Data Contributor` Azure RBAC assignment on `stgoua5wx3gj5qg` plus one Cosmos DB Built-in Data Contributor SQL role assignment for backend principal `69310c48-6a2b-43e8-8116-0cd84eb396f1`
  - Target Frontend `/` and `/api/backend/healthz` both continued returning HTTP `200`

## Validation Checklist

- [x] AZD 1.31.1 is installed and authenticated; `jjflipbook-p2` is the selected local/default AZD environment.
- [x] Exact non-secret target values were verified: `AZURE_ENV_NAME=jjflipbook-p2`, `AZURE_SUBSCRIPTION_ID=43ab425a-c793-4f2e-b71a-0af7a14f26d2`, `AZURE_TENANT_ID=1716e63d-ed31-49bf-aa16-5effd27bc340`, `AZURE_LOCATION=koreacentral`, `RESOURCE_GROUP=rg-jjflipbook-p2`, `BACKEND_IMAGE=ghcr.io/freeman9844/jjflipbook-azure-backend:5594019c96f7cd2aeb251617997ce7e77fca3669`, and `FRONTEND_IMAGE=ghcr.io/freeman9844/jjflipbook-azure-frontend:5594019c96f7cd2aeb251617997ce7e77fca3669`; required secret keys `ADMIN_PASSWORD`, `INTERNAL_API_KEY`, and `SESSION_SECRET` were present without printing values.
- [x] `azure.yaml` validated successfully against the stable Azure Developer CLI schema.
- [x] `az bicep build --file infra/main.bicep --outfile infra/main.generated.json` succeeded; `infra/main.json` remained unchanged.
- [x] `git diff --check` passed with no whitespace errors.
- [x] Backend full test suite passed from `backend/` (`128 passed, 1 warning`).
- [x] Frontend Jest passed (`7` suites, `24` tests).
- [x] Dockerfiles and image references were validated: both Dockerfiles pin base images by digest, `frontend/package-lock.json` exists for `npm ci`, and both AZD image values are immutable commit-SHA tags rather than floating tags.
- [x] `azd provision --preview --no-prompt` succeeded for target subscription `43ab425a-c793-4f2e-b71a-0af7a14f26d2` and target resource group `rg-jjflipbook-p2`; sanitized output was saved to `.azure/migration/target-preview.txt`; the preview was create-only for exactly eight resources, contained no source-subscription references and no delete/replace operations, and the target resource group remained absent.
- [x] `azd package --no-prompt` succeeded for backend and frontend using Ubuntu Docker CLI 29.1.3 connected to rootless Podman 5.8.4 with `DOCKER_DEFAULT_PLATFORM=linux/amd64`; AZD only pulled/tagged local images and did not push.
- [x] Read-only provider metadata confirmed `koreacentral` support for Microsoft.App managed environments/container apps, Cosmos DB accounts, Storage accounts, Log Analytics workspaces, user-assigned managed identities, and Application Insights.
- [x] Read-only policy review found one inherited management-group assignment, `sys.blockwesteurope` (`Microsoft Azure region access restriction blocking West Europe region`); no deny policy blocking the planned resource types or `koreacentral` was identified.
- [x] Static RBAC review passed: only the backend has a user-assigned managed identity; Storage Blob Data Contributor is scoped to the Storage account; Cosmos DB Built-in Data Contributor is scoped to the Cosmos account; the frontend has no managed identity; and no generic data-plane `Contributor` substitution exists.
- [x] Backend code was cross-checked to require Blob read/write plus user-delegation SAS generation and Cosmos read/write/delete/query operations, matching the assigned roles.
- [x] Target resource group absence was confirmed before and after validation: `az group exists --subscription 43ab425a-c793-4f2e-b71a-0af7a14f26d2 --name rg-jjflipbook-p2` returned `false`.

## Planned runbook

1. Confirm GitHub deployment variables now target subscription `43ab425a-c793-4f2e-b71a-0af7a14f26d2` in tenant `1716e63d-ed31-49bf-aa16-5effd27bc340`.
2. Treat GitHub Actions validate-only run `32020155260` on main SHA `5594019c96f7cd2aeb251617997ce7e77fca3669` plus `.azure/migration/target-preview.txt` as the current non-destructive prerequisite proof before any full deployment.
3. Merge the separate GHCR cleanup child-manifest retention fix and regression tests before any workflow path that performs GHCR cleanup; this does not block the initial target `azd provision` because the repaired immutable images are now pullable and Task 7 does not run cleanup.
4. Execute one full target workflow only after data sync is ready; rely on workflow concurrency to queue the same subscription/environment instead of overlapping the `resources` ARM deployment.
5. Resolve the target Frontend Container App URL, verify `/` and `/api/backend/healthz`, then run the operator-visible smoke test.
6. Keep `.azure/migration/` local-only and retain the proof files above until the source environment deletion gate is explicitly approved.
7. After verified cutover and approval, update this file to `Status: Deployed` with the final workflow IDs, commit SHA, target URL, verification digests, and source cleanup proof.

## Guardrails

- Do not commit secrets, SAS tokens, copied data, or attestation payload contents.
- Do not push or run GitHub/Azure side-effect steps from this local preparation task.
- Do not bundle the separate GHCR cleanup retention fix or regression tests into this validation commit; the validation commit is documentation-only.

## Validation Proof

Validation timestamp: `2026-08-17T19:28:45+09:00`

### Commands and exact results

- `azd version` → `azd version 1.31.1 (commit 38c0e3235ee7a27a942a95431b0d0a8a530ae6b0) (stable)`.
- `azd auth login --check-status` → authenticated Azure Developer CLI session for the selected local environment.
- `azd env list` → `jjflipbook-p2` is both `DEFAULT=true` and `LOCAL=true`; `migration` also exists locally but is not selected.
- `azd env get-values` (sanitized) →
  - `AZURE_ENV_NAME="jjflipbook-p2"`
  - `AZURE_LOCATION="koreacentral"`
  - `AZURE_SUBSCRIPTION_ID="43ab425a-c793-4f2e-b71a-0af7a14f26d2"`
  - `AZURE_TENANT_ID="1716e63d-ed31-49bf-aa16-5effd27bc340"`
  - `RESOURCE_GROUP="rg-jjflipbook-p2"`
  - `BACKEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-backend:5594019c96f7cd2aeb251617997ce7e77fca3669"`
  - `FRONTEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-frontend:5594019c96f7cd2aeb251617997ce7e77fca3669"`
  - `ADMIN_PASSWORD`, `INTERNAL_API_KEY`, and `SESSION_SECRET` were present and intentionally redacted.
- Target Azure CLI context was set to subscription `43ab425a-c793-4f2e-b71a-0af7a14f26d2`, tenant `1716e63d-ed31-49bf-aa16-5effd27bc340`, name `Visual Studio Enterprise 구독`.
- Stable-schema validation of `azure.yaml` succeeded.
- `az bicep build --file infra/main.bicep --outfile infra/main.generated.json` → build succeeded and `infra/main.json` did not change. The build emitted only the pre-existing non-fatal warning `BCP334` at `infra/resources.bicep(53,9)` about a possible minimum-length mismatch.
- `git --no-pager diff --check` → exit code `0`, no output.
- `cd backend && python3 -m pytest tests/ -q` → `128 passed, 1 warning in 4.58s`.
- `cd frontend && npm test -- --runInBand --ci` → `7` suites passed, `24` tests passed, `0` snapshots.
- Docker/package-lock/image immutability validation confirmed:
  - `backend/Dockerfile`: `2` `FROM` lines, both digest-pinned.
  - `frontend/Dockerfile`: `2` `FROM` lines, both digest-pinned.
  - `frontend/package-lock.json`: present for `npm ci`.
  - `BACKEND_IMAGE` / `FRONTEND_IMAGE`: immutable commit-SHA tags, not floating tags.
- `azd provision --preview --no-prompt` (with target subscription selected and secret env vars injected from the AZD environment) →
  - `Subscription: Visual Studio Enterprise 구독 (43ab425a-c793-4f2e-b71a-0af7a14f26d2)`
  - `Location: Korea Central`
  - `Create : Resource group             : rg-jjflipbook-p2`
  - `Create : Container App              : ca-backend-goua5wx3gj5qg`
  - `Create : Container App              : ca-frontend-goua5wx3gj5qg`
  - `Create : Container Apps Environment : cae-goua5wx3gj5qg`
  - `Create : Azure Cosmos DB            : cosmos-goua5wx3gj5qg`
  - `Create : Application Insights       : appi-goua5wx3gj5qg`
  - `Create : Log Analytics workspace    : log-goua5wx3gj5qg`
  - `Create : Storage account            : stgoua5wx3gj5qg`
  - `SUCCESS: Generated provisioning preview in 27 seconds.`
- The saved preview in `.azure/migration/target-preview.txt` was re-checked and confirmed to contain only target-subscription/target-resource-group references, no source references, no `Delete`, and no `Replace` operations.
- Initial `azd package --no-prompt` failure exposed a real GHCR defect: the backend OCI index for `ghcr.io/freeman9844/jjflipbook-azure-backend:5594019c96f7cd2aeb251617997ce7e77fca3669` referenced AMD64 child manifest digest `sha256:335a9fba5498e71d3551cf88f4677d6310da0f45f804245c54229bcfc00ae8a7`, but GHCR returned HTTP `404` for that child manifest.
- Root cause analysis: GHCR cleanup was not retaining untagged child manifests referenced by a protected/tagged OCI index. The repository fix and regression tests are pending in a separate uncommitted change and are intentionally excluded from this validation commit.
- GitHub Actions validate-only run `32020155260` on main SHA `5594019c96f7cd2aeb251617997ce7e77fca3669` rebuilt and pushed both images, passed the public manifest check and source-subscription infrastructure preview, and intentionally skipped provisioning, smoke, and cleanup.
- Post-repair manifest verification confirmed that backend and frontend OCI index child manifests all returned HTTP `200`.
- `azd package --no-prompt` after the GHCR repair succeeded for backend and frontend using Ubuntu Docker CLI `29.1.3` connected to rootless Podman `5.8.4` with `DOCKER_DEFAULT_PLATFORM=linux/amd64`; AZD only pulled/tagged local images and did not push.
- Provider metadata checks confirmed `supported_in_koreacentral=True` for:
  - `Microsoft.App/managedEnvironments`
  - `Microsoft.App/containerApps`
  - `Microsoft.DocumentDB/databaseAccounts`
  - `Microsoft.Storage/storageAccounts`
  - `Microsoft.OperationalInsights/workspaces`
  - `Microsoft.ManagedIdentity/userAssignedIdentities`
  - `Microsoft.Insights/components`
- Effective policy review found one inherited management-group assignment, `sys.blockwesteurope` (`Microsoft Azure region access restriction blocking West Europe region`), and no deny policy blocking the planned resource types or `koreacentral`.
- Static RBAC review confirmed:
  - `backendIdentity` is the only user-assigned managed identity.
  - `blobContributor` is a Storage Blob Data Contributor assignment scoped to the Storage account.
  - `cosmosDataContributor` is a Cosmos DB Built-in Data Contributor assignment scoped to the Cosmos account.
  - `frontendApp` has no managed identity.
  - Backend blob/Cosmos code paths match the least-privilege data-plane roles.
- `az group exists --subscription 43ab425a-c793-4f2e-b71a-0af7a14f26d2 --name rg-jjflipbook-p2` → `false` before preview and `false` after validation.

### Overall result

Validation, cutover, and proof-gated source cleanup are complete and this plan is now `Status: Deployed`. The new subscription `43ab425a-c793-4f2e-b71a-0af7a14f26d2` is serving traffic at `https://ca-frontend-goua5wx3gj5qg.politesmoke-658170a7.koreacentral.azurecontainerapps.io`, the source resource group `rg-jjflipbook-p2` in subscription `8dd0dabf-d8c0-4651-a846-5b13e18e05eb` has been deleted after all gates passed, source OIDC subscription roles were revoked, and the temporary target operator Storage/Cosmos assignments were removed while backend runtime data access stayed intact.
