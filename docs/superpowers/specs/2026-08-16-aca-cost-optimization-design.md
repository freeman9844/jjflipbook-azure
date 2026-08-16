# Azure Container Apps Cost Optimization Design

**Date:** 2026-08-16
**Status:** Approved design
**Scope:** `rg-jjflipbook` in subscription `e9c89382-b9fd-4856-8ae4-647988d62a44`

## 1. Goals

- Keep the public frontend responsive during the user-selected daily window of
  10:00-20:00 Korea Standard Time.
- Accept a backend cold start on the first login, data request, or PDF upload.
- Remove the two dominant fixed-cost services: Azure Container Registry and
  Defender for Storage for this storage account.
- Preserve the current security boundary: the backend remains internal, data
  access continues through managed identity, and no registry credential is
  added to Container Apps.
- Reduce unnecessary log ingestion without losing request telemetry or platform
  diagnostics.
- Apply all repeatable configuration through Bicep and GitHub Actions, with
  one-time resource cleanup only after the replacement deployment is healthy.

## 2. Baseline

The 30-day cost query contained charges from the previous deployment on
2026-07-25 through 2026-07-27. The current resources reuse the same deterministic
resource names, so those charges are useful for identifying cost drivers even
though they are not a full monthly forecast.

| Service | Observed cost | Share |
| --- | ---: | ---: |
| Microsoft Defender for Cloud | $0.4622 | 49.8% |
| Container Registry | $0.4195 | 45.2% |
| Log Analytics | $0.0472 | 5.1% |
| Cosmos DB and Storage usage | $0.0001 | <0.1% |
| Azure Container Apps | $0.0000 | 0% |
| **Total** | **$0.9290** | **100%** |

Azure Container Apps is already using the Consumption workload profile with
`minReplicas: 0`. Its low request volume remained within the monthly free grant.
The official free grant includes 180,000 vCPU-seconds, 360,000 GiB-seconds, and
two million requests per subscription per month.

Observed application utilization was low:

- Frontend maximum CPU and memory percentages were approximately 1% and 3%.
- Backend maximum CPU and memory percentages were approximately 2% and 3%
  during light API activity.
- The backend sample did not include a representative large PDF conversion, so
  its 1 vCPU / 2 GiB allocation must not be reduced without workload testing.
- Backend console logs contained more than 41,000 stderr rows and about 18 MiB
  of billed data, dominated by Uvicorn access logging and health probes.

Azure Advisor returned no cost recommendations for the resource group. Azure
Quick Review could not run because the `azqr` executable was not installed; the
design therefore uses direct resource, cost, metric, Advisor, and Log Analytics
queries.

## 3. Selected Architecture

### 3.1 Container Apps environment

Keep the existing Azure Container Apps Consumption environment. Do not move to a
Dedicated workload profile because the workload is small, bursty, and benefits
from scale-to-zero.

### 3.2 Frontend scaling

Configure the frontend with:

- 0.25 vCPU and 0.5 GiB memory.
- `minReplicas: 0`.
- `maxReplicas: 2`.
- `cooldownPeriod: 60`.
- The existing HTTP scaler behavior.
- A KEDA cron rule using `Asia/Seoul`:
  - Start: `55 9 * * *`
  - End: `5 20 * * *`
  - Desired replicas: `1`

The five-minute margins make one frontend replica available before 10:00 and
avoid an immediate scale-down at exactly 20:00. The rule applies every day,
including weekends.

### 3.3 Backend scaling

Keep the backend at:

- 1 vCPU and 2 GiB memory.
- `minReplicas: 0`.
- `maxReplicas: 2`.
- `cooldownPeriod: 60`.
- HTTP concurrency target of one request per replica.

Do not add scheduled warming. The backend handles login, flipbook and folder
data, overlays, music, deletion, and PDF conversion, so its first request can
experience a cold start. This is an explicitly accepted trade-off. Keeping the
current memory allocation avoids introducing PDF conversion failures without a
representative workload benchmark.

Splitting lightweight APIs from PDF processing is outside this change. It would
change the upload contract and require a queue or job-based processing model.

## 4. Container Image Migration

### 4.1 Registry target

Publish public images to:

- `ghcr.io/freeman9844/jjflipbook-azure-backend:<commit-sha>`
- `ghcr.io/freeman9844/jjflipbook-azure-frontend:<commit-sha>`

The repository source is already public. Runtime secrets are injected through
Container Apps and are not included in image layers. Public GHCR images therefore
do not disclose additional application secrets and allow anonymous pulls without
adding a long-lived GitHub token to Azure.

The packages must be explicitly verified as public before Container Apps is
switched to them. GitHub packages do not automatically become public solely
because their source repository is public.

### 4.2 GitHub Actions

Update the deployment workflow to grant:

- `contents: read`
- `packages: write`
- `id-token: write`

The workflow will:

1. Authenticate to GHCR with the job-scoped `GITHUB_TOKEN`.
2. Build and push both images with the immutable commit SHA tag.
3. Set `BACKEND_IMAGE` and `FRONTEND_IMAGE` for the deployment.
4. Authenticate to Azure through the existing OIDC managed identity.
5. Run Bicep validation/what-if before deployment.
6. Provision the infrastructure with the GHCR image references.

`NEXT_PUBLIC_BACKEND_URL` is only read by Next.js server routes at runtime. Remove
the obsolete Docker build argument and continue injecting the internal backend
URL through the Container App environment.

Configure `azure.yaml` services in image mode so manual `azd` operations use the
same GHCR image references instead of requesting an ACR build.

### 4.3 Bicep changes

- Add `backendImage` and `frontendImage` parameters and use them directly in the
  Container App templates.
- Remove the ACR resource, ACR pull role assignments, registry configuration,
  and the ACR-only frontend managed identity from the desired infrastructure.
- Keep the backend managed identity for Cosmos DB and Blob Storage access.
- Remove the `AZURE_CONTAINER_REGISTRY_ENDPOINT` output.
- Add a storage-scoped
  `Microsoft.Security/defenderForStorageSettings` extension resource named
  `current`, with `isEnabled: false` and
  `overrideSubscriptionLevelSettings: true`.

Bicep deployments are incremental and do not delete resources removed from a
template. The existing ACR and frontend identity therefore require a controlled,
one-time cleanup after the GHCR deployment is proven healthy.

## 5. Defender for Storage

Disable Defender for Storage only at the
`st3nbgqlm6mwuwo` resource scope. Do not change the subscription-wide Defender
plan or any other storage account.

The storage account remains:

- Private at the container level.
- Restricted to HTTPS and TLS 1.2.
- Protected from shared-key access.
- Accessible to the backend through managed identity.
- Exposed to readers only through exact-blob, read-only user-delegation SAS
  tokens.

This is a deliberate cost-versus-security decision based on the application
allowing only the administrator to upload trusted PDF files.

## 6. Logging and Observability

- Start Uvicorn with access logging disabled.
- Keep application warnings and errors on stdout/stderr.
- Keep Azure Container Apps system logs.
- Keep workspace-based Application Insights request and dependency telemetry.
- Keep Log Analytics retention at 30 days.

Application Insights provides request telemetry, so removing duplicate Uvicorn
access lines does not remove the primary request-monitoring surface. No telemetry
sampling change is needed at the current volume.

## 7. Deployment and Rollback

Use the following migration sequence:

1. Build and push both GHCR images.
2. Confirm that both packages are public and anonymously pullable.
3. Compile Bicep and run subscription-scope what-if.
4. Deploy the GHCR-backed Container App revisions.
5. Verify:
   - Frontend returns HTTP 200.
   - `admin` login succeeds.
   - Authenticated list operations succeed.
   - A representative PDF uploads and converts successfully.
   - The frontend cron and backend scale rules match the design.
   - Application Insights and Container Apps system logs continue to arrive.
6. Disable Defender for Storage at the storage-account scope.
7. Delete only the old ACR and the unused frontend managed identity.

Do not delete ACR if image pull, startup, login, or PDF processing fails. Before
ACR deletion, rollback uses the last healthy ACR-backed revision. After deletion,
rollback uses the previous immutable GHCR commit SHA.

Retain at least the five most recent GHCR image versions for each service. Image
cleanup must never delete a digest referenced by an active or rollback revision.

## 8. Expected Cost Effect

The change removes the two services responsible for approximately 95% of the
observed historical cost:

- ACR Basic fixed cost.
- Defender for Storage charges for this storage account.

Scheduled frontend warming introduces idle Container Apps consumption for about
10 hours and 10 minutes per day. The frontend is reduced to the smallest
appropriate CPU/memory pair, and the backend remains scale-to-zero. Actual net
monthly savings depend on regional idle rates and whether the subscription's
Container Apps free grant is shared with other workloads, so the first complete
billing month must be reviewed rather than relying on a fixed savings promise.

## 9. Validation

- Existing backend and frontend test suites pass.
- Frontend production build succeeds without the backend build argument.
- Both Docker images build successfully.
- Bicep compiles and subscription-scope what-if contains only expected changes.
- GHCR anonymous pulls succeed.
- The deployed application passes login, list, and PDF upload smoke tests.
- After the schedule window, the frontend reaches zero replicas.
- During the schedule window, the frontend maintains one replica.
- Outside active backend requests, the backend reaches zero replicas.
- Cost Management is queried again after enough billing data is available to
  confirm that ACR and Defender charges stop.

## 10. References

- Azure Container Apps pricing:
  <https://azure.microsoft.com/pricing/details/container-apps/>
- Azure Container Apps scaling:
  <https://learn.microsoft.com/azure/container-apps/scale-app>
- Azure Developer CLI `azure.yaml` image deployment:
  <https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-schema>
- GitHub Packages access and visibility:
  <https://docs.github.com/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility>
- Defender for Storage resource-level settings:
  <https://learn.microsoft.com/azure/templates/microsoft.security/defenderforstoragesettings>
