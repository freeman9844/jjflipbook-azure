# Azure Container Apps Cost Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the frontend warm every day from 10:00-20:00 KST while removing ACR and resource-level Defender for Storage costs, preserving backend scale-to-zero, and reducing duplicate access-log ingestion.

**Architecture:** GitHub Actions builds immutable public GHCR images and passes those image references into subscription-scope Bicep. Azure Container Apps remains on the Consumption plan; the frontend uses an HTTP rule plus a daily KEDA cron rule, while the backend retains its PDF-safe allocation and scales to zero. A storage-scoped Defender override, deployment smoke test, guarded legacy-resource cleanup, and GHCR retention script make the migration repeatable and reversible.

**Tech Stack:** Azure Container Apps Consumption, Bicep, Azure Developer CLI, GitHub Actions OIDC, GitHub Container Registry, Bash, Python 3.11, pytest, FastAPI/Uvicorn, Next.js 16, Application Insights, Log Analytics

**Spec:** `docs/superpowers/specs/2026-08-16-aca-cost-optimization-design.md`

## Global Constraints

- Keep the backend internal and the frontend public.
- Keep managed identity for Cosmos DB and Blob Storage; do not add registry credentials to Container Apps.
- Frontend schedule is every day, including weekends, with a 09:55 start and 20:05 end in `Asia/Seoul`.
- Frontend allocation is 0.25 vCPU / 0.5 GiB; backend remains 1 vCPU / 2 GiB.
- Both apps keep `minReplicas: 0`, `maxReplicas: 2`, and `cooldownPeriod: 60`.
- The backend has no cron rule and keeps HTTP concurrency at one.
- Use immutable GHCR commit-SHA tags and public anonymous pulls.
- Disable Defender for Storage only for the application storage account.
- Keep Application Insights, Container Apps system logs, and 30-day Log Analytics retention.
- Disable only Uvicorn request access logs; do not suppress application warnings or errors.
- Never delete ACR or the old frontend identity until the GHCR revision passes frontend, login, list, and PDF smoke tests.
- Preserve the latest five GHCR versions and the image tags used by the two newest Container App revisions.
- Use `Microsoft.App/*@2026-01-01` and stable `Microsoft.Security/defenderForStorageSettings@2025-06-01` for modified resources.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/Dockerfile` | Backend runtime command and GHCR package source metadata |
| `frontend/Dockerfile` | Frontend runtime image and GHCR package source metadata |
| `backend/tests/test_deployment_config.py` | Repository-level deployment configuration contract tests |
| `infra/main.bicep` | Subscription entry point and image parameters |
| `infra/main.parameters.json` | Maps `BACKEND_IMAGE` and `FRONTEND_IMAGE` into Bicep |
| `infra/resources.bicep` | ACA sizing/scaling, GHCR images, Defender override, and ACR removal |
| `infra/main.json` | Generated ARM output committed by the existing repository convention |
| `azure.yaml` | Image-mode service definitions for manual `azd` commands |
| `scripts/smoke_test_deployment.sh` | End-to-end frontend, login, list, upload, read, and cleanup smoke test |
| `scripts/cleanup_legacy_azure_resources.sh` | Guarded deletion of the old ACR and unused frontend identity |
| `scripts/cleanup_ghcr_versions.py` | Retains current rollback images and only the five newest package versions |
| `backend/tests/test_ghcr_cleanup.py` | Unit tests for safe GHCR retention selection |
| `.github/workflows/azure-dev.yml` | GHCR build, anonymous-pull gate, preview, provision, smoke test, and cleanup |
| `README.md` | Updated deployment, scaling, cold-start, registry, logging, and cost behavior |

---

### Task 1: Slim Runtime Logging and Image Metadata

**Files:**
- Create: `backend/tests/test_deployment_config.py`
- Modify: `backend/Dockerfile`
- Modify: `frontend/Dockerfile`

**Interfaces:**
- Consumes: Existing Docker build contexts `backend/` and `frontend/`
- Produces: Backend runtime with Uvicorn access logging disabled; GHCR-linked OCI image metadata; frontend image with no obsolete build-time backend URL

- [ ] **Step 1: Write failing deployment contract tests**

Create `backend/tests/test_deployment_config.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_backend_disables_uvicorn_access_log():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
    assert '"--no-access-log"' in dockerfile


def test_images_link_to_source_repository():
    expected = (
        'LABEL org.opencontainers.image.source='
        '"https://github.com/freeman9844/jjflipbook-azure"'
    )
    assert expected in (ROOT / "backend" / "Dockerfile").read_text()
    assert expected in (ROOT / "frontend" / "Dockerfile").read_text()


def test_frontend_backend_url_is_runtime_only():
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text()
    assert "ARG NEXT_PUBLIC_BACKEND_URL" not in dockerfile
    assert "ENV NEXT_PUBLIC_BACKEND_URL" not in dockerfile
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
cd backend
pytest tests/test_deployment_config.py -v
```

Expected: three failures because the access-log flag and OCI labels do not exist and the frontend still contains the build argument.

- [ ] **Step 3: Update both Dockerfiles**

Add this label to both runtime images:

```dockerfile
LABEL org.opencontainers.image.source="https://github.com/freeman9844/jjflipbook-azure"
```

Change the backend command to:

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
```

Remove these lines from `frontend/Dockerfile`:

```dockerfile
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
```

Also update the stale comment so it says the internal backend URL is injected into the Container App at runtime.

- [ ] **Step 4: Run targeted runtime validation**

Run:

```bash
cd backend
pytest tests/test_deployment_config.py -v
cd ../frontend
npm run type-check
npm run build
```

Expected: all deployment contract tests pass, TypeScript passes, and the production build succeeds without a backend build argument.

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile frontend/Dockerfile backend/tests/test_deployment_config.py
git commit -m "perf: reduce container access logging"
```

---

### Task 2: Replace ACR Infrastructure and Configure ACA Scaling

**Files:**
- Modify: `backend/tests/test_deployment_config.py`
- Modify: `infra/main.bicep`
- Modify: `infra/main.parameters.json`
- Modify: `infra/resources.bicep`
- Regenerate: `infra/main.json`

**Interfaces:**
- Consumes: `BACKEND_IMAGE` and `FRONTEND_IMAGE` environment variables containing immutable public GHCR references
- Produces: `backendImage` and `frontendImage` Bicep parameters; public GHCR-backed Container Apps; storage-scoped Defender disablement

- [ ] **Step 1: Add failing infrastructure contract tests**

Append to `backend/tests/test_deployment_config.py`:

```python
import json


def test_bicep_uses_ghcr_image_parameters_and_has_no_acr():
    main = (ROOT / "infra" / "main.bicep").read_text()
    resources = (ROOT / "infra" / "resources.bicep").read_text()

    assert "param backendImage string" in main
    assert "param frontendImage string" in main
    assert "param backendImage string" in resources
    assert "param frontendImage string" in resources
    assert "image: backendImage" in resources
    assert "image: frontendImage" in resources
    assert "Microsoft.ContainerRegistry/registries" not in resources
    assert "AcrPull" not in resources
    assert "id-frontend-" not in resources
    assert "AZURE_CONTAINER_REGISTRY_ENDPOINT" not in main


def test_bicep_defines_selected_scaling_policy():
    resources = (ROOT / "infra" / "resources.bicep").read_text()

    assert "cpu: json('0.25')" in resources
    assert "memory: '0.5Gi'" in resources
    assert "cooldownPeriod: 60" in resources
    assert "timezone: 'Asia/Seoul'" in resources
    assert "start: '55 9 * * *'" in resources
    assert "end: '5 20 * * *'" in resources
    assert "desiredReplicas: '1'" in resources
    assert resources.count("type: 'cron'") == 1


def test_bicep_disables_defender_only_at_storage_scope():
    resources = (ROOT / "infra" / "resources.bicep").read_text()

    assert (
        "Microsoft.Security/defenderForStorageSettings@2025-06-01"
        in resources
    )
    assert "scope: storage" in resources
    assert "name: 'current'" in resources
    assert "isEnabled: false" in resources
    assert "overrideSubscriptionLevelSettings: true" in resources


def test_parameter_file_maps_immutable_images():
    parameters = json.loads(
        (ROOT / "infra" / "main.parameters.json").read_text()
    )["parameters"]
    assert parameters["backendImage"]["value"] == "${BACKEND_IMAGE}"
    assert parameters["frontendImage"]["value"] == "${FRONTEND_IMAGE}"
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```bash
cd backend
pytest tests/test_deployment_config.py -v
```

Expected: Docker tests pass and the four new infrastructure tests fail.

- [ ] **Step 3: Add image parameters to the subscription entry point**

Add to `infra/main.bicep`:

```bicep
@description('Immutable public GHCR image for the backend')
param backendImage string

@description('Immutable public GHCR image for the frontend')
param frontendImage string
```

Pass them to the resource module:

```bicep
backendImage: backendImage
frontendImage: frontendImage
```

Remove:

```bicep
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.acrLoginServer
```

Add to `infra/main.parameters.json`:

```json
"backendImage": { "value": "${BACKEND_IMAGE}" },
"frontendImage": { "value": "${FRONTEND_IMAGE}" }
```

- [ ] **Step 4: Remove ACR-only resources and add the Defender override**

In `infra/resources.bicep`:

1. Add `backendImage` and `frontendImage` string parameters.
2. Remove `frontendIdentity`.
3. Remove the ACR resource and both ACR pull role assignments.
4. Remove `configuration.registries` from both apps.
5. Keep `backendIdentity` and its Cosmos/Storage role assignments.
6. Remove `acrLoginServer` output.
7. Add:

```bicep
resource defenderForStorage 'Microsoft.Security/defenderForStorageSettings@2025-06-01' = {
  scope: storage
  name: 'current'
  properties: {
    isEnabled: false
    overrideSubscriptionLevelSettings: true
  }
}
```

- [ ] **Step 5: Apply the exact Container Apps template changes**

Use stable API version `2026-01-01` for both the managed environment and Container Apps.

Backend:

```bicep
image: backendImage
resources: {
  cpu: json('1.0')
  memory: '2Gi'
}
scale: {
  minReplicas: 0
  maxReplicas: 2
  cooldownPeriod: 60
  pollingInterval: 30
  rules: [
    {
      name: 'http-single'
      http: {
        metadata: {
          concurrentRequests: '1'
        }
      }
    }
  ]
}
```

Frontend:

```bicep
image: frontendImage
resources: {
  cpu: json('0.25')
  memory: '0.5Gi'
}
scale: {
  minReplicas: 0
  maxReplicas: 2
  cooldownPeriod: 60
  pollingInterval: 30
  rules: [
    {
      name: 'http'
      http: {
        metadata: {
          concurrentRequests: '10'
        }
      }
    }
    {
      name: 'daily-warm-window'
      custom: {
        type: 'cron'
        metadata: {
          timezone: 'Asia/Seoul'
          start: '55 9 * * *'
          end: '5 20 * * *'
          desiredReplicas: '1'
        }
      }
    }
  ]
}
```

Change the frontend identity to `None` by removing the entire `identity` block. Update backend dependencies to only the data-plane role assignments, and remove the obsolete frontend ACR dependency.

- [ ] **Step 6: Compile Bicep and run contract tests**

Run:

```bash
az bicep build --file infra/main.bicep --outfile infra/main.json
cd backend
pytest tests/test_deployment_config.py -v
```

Expected: Bicep compiles, generated `infra/main.json` contains the two image parameters and no ACR resource, and all deployment contract tests pass.

- [ ] **Step 7: Commit**

```bash
git add infra/main.bicep infra/main.parameters.json infra/resources.bicep infra/main.json backend/tests/test_deployment_config.py
git commit -m "infra: optimize container apps consumption"
```

---

### Task 3: Add Safe Deployment Smoke and Legacy Cleanup Scripts

**Files:**
- Create: `scripts/smoke_test_deployment.sh`
- Create: `scripts/cleanup_legacy_azure_resources.sh`

**Interfaces:**
- Consumes: `FRONTEND_URL`, `ADMIN_PASSWORD`, `AZURE_ENV_NAME`, and Azure CLI authentication
- Produces: End-to-end deployment verification and narrowly scoped deletion of the legacy ACR/frontend identity

- [ ] **Step 1: Create the deployment smoke test**

Create `scripts/smoke_test_deployment.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${FRONTEND_URL:?FRONTEND_URL is required}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD is required}"

COOKIE_JAR="$(mktemp)"
LOGIN_BODY="$(mktemp)"
BOOK_ID=""

cleanup() {
  if [[ -n "$BOOK_ID" ]]; then
    if ! curl --fail --silent --show-error \
      --cookie "$COOKIE_JAR" \
      --request DELETE \
      "$FRONTEND_URL/api/backend/flipbook/$BOOK_ID" >/dev/null; then
      echo "Warning: smoke-test flipbook cleanup failed for $BOOK_ID" >&2
    fi
  fi
  rm -f "$COOKIE_JAR" "$LOGIN_BODY"
}
trap cleanup EXIT

curl --fail --silent --show-error --location "$FRONTEND_URL" >/dev/null

jq -cn --arg password "$ADMIN_PASSWORD" \
  '{username:"admin", password:$password}' >"$LOGIN_BODY"

curl --fail --silent --show-error \
  --cookie-jar "$COOKIE_JAR" \
  --header "Content-Type: application/json" \
  --data-binary "@$LOGIN_BODY" \
  "$FRONTEND_URL/api/backend/login" |
  jq -e '.authenticated == true and .username == "admin"' >/dev/null

curl --fail --silent --show-error \
  --cookie "$COOKIE_JAR" \
  "$FRONTEND_URL/api/backend/flipbooks" |
  jq -e 'type == "array"' >/dev/null

UPLOAD_RESPONSE="$(
  curl --fail --silent --show-error \
    --cookie "$COOKIE_JAR" \
    --form "file=@backend/tests/test.pdf;type=application/pdf" \
    "$FRONTEND_URL/api/backend/upload?split_pages=true"
)"
BOOK_ID="$(jq -er '.book_id' <<<"$UPLOAD_RESPONSE")"

curl --fail --silent --show-error \
  --cookie "$COOKIE_JAR" \
  "$FRONTEND_URL/api/backend/flipbook/$BOOK_ID" |
  jq -e '.status == "success" and .page_count > 0' >/dev/null

curl --fail --silent --show-error \
  --cookie "$COOKIE_JAR" \
  --request DELETE \
  "$FRONTEND_URL/api/backend/flipbook/$BOOK_ID" |
  jq -e '.status == "ok"' >/dev/null
BOOK_ID=""
```

The trap intentionally ignores only cleanup failure after the primary smoke test has already failed; the main verification commands remain fail-closed.

- [ ] **Step 2: Create guarded legacy Azure cleanup**

Create `scripts/cleanup_legacy_azure_resources.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_ENV_NAME:?AZURE_ENV_NAME is required}"
RESOURCE_GROUP="rg-$AZURE_ENV_NAME"

IMAGES="$(
  az containerapp list --resource-group "$RESOURCE_GROUP" --output json |
    jq -r '.[].properties.template.containers[].image'
)"

if [[ -z "$IMAGES" ]] || grep -v '^ghcr\.io/freeman9844/' <<<"$IMAGES" >/dev/null; then
  echo "Refusing cleanup: every active Container App image must use public GHCR." >&2
  exit 1
fi

mapfile -t ACR_NAMES < <(
  az acr list --resource-group "$RESOURCE_GROUP" --output json |
    jq -r --arg env "$AZURE_ENV_NAME" \
      '.[] | select(.tags["azd-env-name"] == $env) | .name'
)

if (( ${#ACR_NAMES[@]} > 1 )); then
  echo "Refusing cleanup: more than one tagged ACR matched." >&2
  exit 1
fi

if (( ${#ACR_NAMES[@]} == 1 )); then
  az acr delete \
    --resource-group "$RESOURCE_GROUP" \
    --name "${ACR_NAMES[0]}" \
    --yes
fi

mapfile -t FRONTEND_IDENTITIES < <(
  az identity list --resource-group "$RESOURCE_GROUP" --output json |
    jq -r --arg env "$AZURE_ENV_NAME" \
      '.[] |
       select(.tags["azd-env-name"] == $env) |
       select(.name | startswith("id-frontend-")) |
       .name'
)

if (( ${#FRONTEND_IDENTITIES[@]} > 1 )); then
  echo "Refusing cleanup: more than one frontend identity matched." >&2
  exit 1
fi

if (( ${#FRONTEND_IDENTITIES[@]} == 1 )); then
  az identity delete \
    --resource-group "$RESOURCE_GROUP" \
    --name "${FRONTEND_IDENTITIES[0]}"
fi
```

- [ ] **Step 3: Validate shell syntax**

Run:

```bash
bash -n scripts/smoke_test_deployment.sh
bash -n scripts/cleanup_legacy_azure_resources.sh
```

Expected: both commands exit zero.

- [ ] **Step 4: Commit**

```bash
chmod +x scripts/smoke_test_deployment.sh scripts/cleanup_legacy_azure_resources.sh
git add scripts/smoke_test_deployment.sh scripts/cleanup_legacy_azure_resources.sh
git commit -m "test: add deployment migration smoke checks"
```

---

### Task 4: Add Rollback-Safe GHCR Retention

**Files:**
- Create: `scripts/cleanup_ghcr_versions.py`
- Create: `backend/tests/test_ghcr_cleanup.py`

**Interfaces:**
- Consumes: GitHub package-version JSON, the two newest revision image tags for each Container App, `GITHUB_TOKEN`, `GITHUB_REPOSITORY_OWNER`, and `AZURE_ENV_NAME`
- Produces: Package version IDs safe to delete while retaining at least five versions and the current/previous revision tags

- [ ] **Step 1: Write failing retention-selection tests**

Create `backend/tests/test_ghcr_cleanup.py`:

```python
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_ghcr_versions.py"
SPEC = importlib.util.spec_from_file_location("cleanup_ghcr_versions", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def version(version_id, created_at, *tags):
    return {
        "id": version_id,
        "created_at": created_at,
        "metadata": {"container": {"tags": list(tags)}},
    }


def test_keeps_five_newest_versions():
    versions = [
        version(i, f"2026-08-{i:02d}T00:00:00Z", f"sha-{i}")
        for i in range(1, 8)
    ]
    assert MODULE.version_ids_to_delete(versions, set(), keep=5) == [2, 1]


def test_keeps_protected_rollback_tag_even_when_old():
    versions = [
        version(i, f"2026-08-{i:02d}T00:00:00Z", f"sha-{i}")
        for i in range(1, 8)
    ]
    assert MODULE.version_ids_to_delete(
        versions, {"sha-1"}, keep=5
    ) == [2]


def test_keeps_untagged_version_if_it_is_among_five_newest():
    versions = [
        version(6, "2026-08-06T00:00:00Z"),
        version(5, "2026-08-05T00:00:00Z", "sha-5"),
        version(4, "2026-08-04T00:00:00Z", "sha-4"),
        version(3, "2026-08-03T00:00:00Z", "sha-3"),
        version(2, "2026-08-02T00:00:00Z", "sha-2"),
        version(1, "2026-08-01T00:00:00Z", "sha-1"),
    ]
    assert MODULE.version_ids_to_delete(versions, set(), keep=5) == [1]
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run:

```bash
cd backend
pytest tests/test_ghcr_cleanup.py -v
```

Expected: collection fails because `scripts/cleanup_ghcr_versions.py` does not exist.

- [ ] **Step 3: Implement deterministic selection logic**

Create `scripts/cleanup_ghcr_versions.py` with these public functions:

```python
import json
import os
import subprocess
import urllib.parse
import urllib.request


PACKAGES = {
    "backend": "jjflipbook-azure-backend",
    "frontend": "jjflipbook-azure-frontend",
}


def version_ids_to_delete(
    versions: list[dict], protected_tags: set[str], keep: int = 5
) -> list[int]:
    ordered = sorted(
        versions,
        key=lambda item: item["created_at"],
        reverse=True,
    )
    protected_ids = {item["id"] for item in ordered[:keep]}
    for item in ordered:
        tags = set(item.get("metadata", {}).get("container", {}).get("tags", []))
        if tags & protected_tags:
            protected_ids.add(item["id"])
    return [item["id"] for item in ordered if item["id"] not in protected_ids]


def run_az(*args: str) -> list[dict]:
    completed = subprocess.run(
        ["az", *args, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def package_request(url: str, token: str, method: str = "GET") -> dict | list | None:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request) as response:
        if response.status == 204:
            return None
        return json.load(response)


def find_app_names(resource_group: str) -> dict[str, str]:
    apps = run_az("containerapp", "list", "--resource-group", resource_group)
    result = {}
    for service in PACKAGES:
        matches = [app["name"] for app in apps if service in app["name"]]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one {service} Container App, found {matches}"
            )
        result[service] = matches[0]
    return result


def protected_revision_tags(resource_group: str, app_name: str) -> set[str]:
    revisions = run_az(
        "containerapp",
        "revision",
        "list",
        "--resource-group",
        resource_group,
        "--name",
        app_name,
    )
    revisions.sort(
        key=lambda item: item.get("properties", {}).get("createdTime", ""),
        reverse=True,
    )
    tags = set()
    for revision in revisions[:2]:
        containers = revision["properties"]["template"]["containers"]
        for container in containers:
            image = container["image"]
            if ":" not in image:
                raise RuntimeError(f"Revision image has no immutable tag: {image}")
            tags.add(image.rsplit(":", 1)[1])
    return tags


def list_package_versions(owner: str, package: str, token: str) -> list[dict]:
    encoded = urllib.parse.quote(package, safe="")
    versions = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/users/{owner}/packages/container/"
            f"{encoded}/versions?per_page=100&page={page}"
        )
        batch = package_request(url, token)
        assert isinstance(batch, list)
        versions.extend(batch)
        if len(batch) < 100:
            return versions
        page += 1


def delete_package_version(
    owner: str, package: str, version_id: int, token: str
) -> None:
    encoded = urllib.parse.quote(package, safe="")
    package_request(
        (
            f"https://api.github.com/users/{owner}/packages/container/"
            f"{encoded}/versions/{version_id}"
        ),
        token,
        method="DELETE",
    )


def main() -> None:
    token = os.environ["GITHUB_TOKEN"]
    owner = os.environ["GITHUB_REPOSITORY_OWNER"]
    resource_group = f"rg-{os.environ['AZURE_ENV_NAME']}"
    app_names = find_app_names(resource_group)

    for service, package in PACKAGES.items():
        protected = protected_revision_tags(resource_group, app_names[service])
        versions = list_package_versions(owner, package, token)
        delete_ids = version_ids_to_delete(versions, protected, keep=5)
        print(
            f"{package}: retaining {len(versions) - len(delete_ids)} versions; "
            f"protected tags={sorted(protected)}"
        )
        for version_id in delete_ids:
            delete_package_version(owner, package, version_id, token)
            print(f"{package}: deleted version {version_id}")


if __name__ == "__main__":
    main()
```

This implementation uses only Python standard-library modules, paginates through
all package versions, retains the latest two revision tags, and propagates Azure
CLI and GitHub API errors.

- [ ] **Step 4: Run unit tests**

Run:

```bash
cd backend
pytest tests/test_ghcr_cleanup.py -v
```

Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cleanup_ghcr_versions.py backend/tests/test_ghcr_cleanup.py
git commit -m "chore: retain rollback-safe ghcr images"
```

---

### Task 5: Switch azd and GitHub Actions to GHCR

**Files:**
- Modify: `backend/tests/test_deployment_config.py`
- Modify: `azure.yaml`
- Modify: `.github/workflows/azure-dev.yml`

**Interfaces:**
- Consumes: GitHub `GITHUB_TOKEN`, existing Azure OIDC variables, `ADMIN_PASSWORD`, `INTERNAL_API_KEY`, and `SESSION_SECRET`
- Produces: Immutable public GHCR images, validated Bicep preview/provision, live smoke validation, and post-success cleanup

- [ ] **Step 1: Add failing workflow and azd contract tests**

Append to `backend/tests/test_deployment_config.py`:

```python
def test_azd_uses_prebuilt_ghcr_images():
    azure_yaml = (ROOT / "azure.yaml").read_text()
    assert "image: ${BACKEND_IMAGE}" in azure_yaml
    assert "image: ${FRONTEND_IMAGE}" in azure_yaml
    assert "remoteBuild:" not in azure_yaml
    assert "project:" not in azure_yaml


def test_workflow_builds_ghcr_and_previews_before_provisioning():
    workflow = (
        ROOT / ".github" / "workflows" / "azure-dev.yml"
    ).read_text()
    assert "packages: write" in workflow
    assert "ghcr.io/freeman9844/jjflipbook-azure-backend:${{ github.sha }}" in workflow
    assert "ghcr.io/freeman9844/jjflipbook-azure-frontend:${{ github.sha }}" in workflow
    assert "docker manifest inspect" in workflow
    assert "azd provision --preview --no-prompt" in workflow
    assert workflow.index("azd provision --preview --no-prompt") < workflow.index(
        "azd provision --no-prompt"
    )
    assert "scripts/smoke_test_deployment.sh" in workflow
    assert "scripts/cleanup_legacy_azure_resources.sh" in workflow
    assert "scripts/cleanup_ghcr_versions.py" in workflow
```

- [ ] **Step 2: Run tests and confirm the two new tests fail**

Run:

```bash
cd backend
pytest tests/test_deployment_config.py -v
```

Expected: existing tests pass and the azd/workflow tests fail.

- [ ] **Step 3: Convert `azure.yaml` to image mode**

Replace its service definitions with:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/azure/azure-dev/main/schemas/v1.0/azure.yaml.json
name: jjflipbook-azure
infra:
  provider: bicep
  path: infra
services:
  backend:
    host: containerapp
    image: ${BACKEND_IMAGE}
  frontend:
    host: containerapp
    image: ${FRONTEND_IMAGE}
```

- [ ] **Step 4: Rewrite the deployment workflow**

Keep the existing `workflow_dispatch` and `main` push triggers. Set:

```yaml
permissions:
  contents: read
  id-token: write
  packages: write
```

Add job-level image variables:

```yaml
BACKEND_IMAGE: ghcr.io/freeman9844/jjflipbook-azure-backend:${{ github.sha }}
FRONTEND_IMAGE: ghcr.io/freeman9844/jjflipbook-azure-frontend:${{ github.sha }}
```

Use these steps in order:

1. Checkout.
2. Install `azd`.
3. Configure Docker Buildx.
4. Log into GHCR:

```yaml
- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3

- name: Log in to GHCR
  uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}
```

5. Build and push immutable images:

```yaml
- name: Build and push backend image
  uses: docker/build-push-action@v6
  with:
    context: ./backend
    file: ./backend/Dockerfile
    push: true
    platforms: linux/amd64
    tags: ${{ env.BACKEND_IMAGE }}

- name: Build and push frontend image
  uses: docker/build-push-action@v6
  with:
    context: ./frontend
    file: ./frontend/Dockerfile
    push: true
    platforms: linux/amd64
    tags: ${{ env.FRONTEND_IMAGE }}
```

6. Verify anonymous pulls before touching Azure:

```yaml
- name: Verify images are public
  run: |
    docker logout ghcr.io
    docker manifest inspect "$BACKEND_IMAGE" >/dev/null
    docker manifest inspect "$FRONTEND_IMAGE" >/dev/null
```

This step is an intentional first-deployment gate. New GHCR packages are private
until their visibility is changed to public. If it fails, the old ACR-backed
revision remains untouched.

7. Log into Azure with the existing `azd auth login` OIDC command.
8. Run preview and provision with all secure parameters available:

```yaml
- name: Preview infrastructure changes
  run: azd provision --preview --no-prompt
  env:
    ADMIN_PASSWORD: ${{ secrets.ADMIN_PASSWORD }}
    INTERNAL_API_KEY: ${{ secrets.INTERNAL_API_KEY }}
    SESSION_SECRET: ${{ secrets.SESSION_SECRET }}

- name: Provision optimized infrastructure
  run: azd provision --no-prompt
  env:
    ADMIN_PASSWORD: ${{ secrets.ADMIN_PASSWORD }}
    INTERNAL_API_KEY: ${{ secrets.INTERNAL_API_KEY }}
    SESSION_SECRET: ${{ secrets.SESSION_SECRET }}
```

Do not run `azd deploy`: provisioning already supplies the immutable images to
the Container App templates and a second deployment would create unnecessary
revision churn.

9. Resolve `FRONTEND_URL` from `az containerapp list` and write it to
   `$GITHUB_ENV`.
10. Run `scripts/smoke_test_deployment.sh` with `ADMIN_PASSWORD`.
11. Run `scripts/cleanup_legacy_azure_resources.sh`.
12. Run `python3 scripts/cleanup_ghcr_versions.py` with
    `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.

- [ ] **Step 5: Run local static validation**

Run:

```bash
cd backend
pytest tests/test_deployment_config.py -v
cd ..
bash -n scripts/smoke_test_deployment.sh
bash -n scripts/cleanup_legacy_azure_resources.sh
az bicep build --file infra/main.bicep --outfile infra/main.json
```

Expected: all contract tests and syntax checks pass.

- [ ] **Step 6: Commit**

```bash
git add azure.yaml .github/workflows/azure-dev.yml infra/main.json backend/tests/test_deployment_config.py
git commit -m "ci: deploy immutable images from ghcr"
```

---

### Task 6: Update Operations Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Final scaling, registry, cost, logging, and deployment behavior
- Produces: Operator guidance that matches the live infrastructure

- [ ] **Step 1: Update architecture and CI/CD documentation**

Document these exact behaviors:

- Images are built by GitHub Actions and published to public GHCR packages with
  commit-SHA tags.
- `azd provision` deploys those immutable images; ACR is no longer provisioned.
- Frontend is warm daily from 09:55 to 20:05 KST and otherwise scales to zero.
- Backend always scales to zero when idle and may cold-start on login/list/upload.
- Frontend is 0.25 vCPU / 0.5 GiB; backend is 1 vCPU / 2 GiB.
- Defender for Storage is disabled only for this application's storage account.
- Uvicorn access logs are disabled while Application Insights request telemetry
  and ACA system logs remain enabled.
- The first GHCR migration requires making both packages public before rerunning
  the failed anonymous-pull gate.
- GHCR cleanup retains the latest five versions and the two newest ACA revision
  tags.

Remove stale references to:

- ACR remote builds.
- `AZURE_CONTAINER_REGISTRY_ENDPOINT`.
- Frontend ACR pull managed identity.
- `azd deploy` as a required CI stage.

- [ ] **Step 2: Review the rendered content for contradictory claims**

Run:

```bash
rg -n "ACR|remoteBuild|azd deploy|Container Registry|GHCR|09:55|20:05|Defender" README.md
git diff --check
```

Expected: ACR appears only in migration/history wording, current deployment
instructions name GHCR, and `git diff --check` exits zero.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document container apps cost controls"
```

---

### Task 7: Run Full Local and IaC Validation

**Files:**
- No new files

**Interfaces:**
- Consumes: All implementation tasks
- Produces: A release candidate safe to push

- [ ] **Step 1: Run backend tests**

```bash
cd backend
pytest -v
```

Expected: all existing and new backend tests pass.

- [ ] **Step 2: Run frontend checks**

```bash
cd frontend
npm test -- --runInBand
npm run type-check
npm run lint
npm run build
```

Expected: tests, type-check, lint, and production build pass.

- [ ] **Step 3: Compile Bicep and inspect generated resources**

```bash
cd ..
az bicep build --file infra/main.bicep --outfile infra/main.json
jq -e '
  [.. | objects |
   select(.type? == "Microsoft.ContainerRegistry/registries")] |
  length == 0
' infra/main.json
rg -n "defenderForStorageSettings|daily-warm-window|Asia/Seoul" infra/main.json
```

Expected: no ACR resource and positive matches for Defender, cron scaling, and
image parameters.

- [ ] **Step 4: Review the complete diff**

```bash
git diff --check
git status --short
git log --oneline -8
```

Expected: only intended files are changed and each implementation unit has its
own commit.

---

### Task 8: Bootstrap Public GHCR and Deploy Safely

**Files:**
- No code changes unless validation finds a defect

**Interfaces:**
- Consumes: Completed branch, GitHub repository admin access, Azure OIDC deployment identity, existing application secrets
- Produces: Live GHCR-backed optimized environment with legacy cost resources removed

- [ ] **Step 1: Merge the implementation branch into local `main` and push**

Use the repository's normal non-interactive merge flow, then:

```bash
git push origin main
```

Expected: the first workflow creates both GHCR packages. It may stop at
`Verify images are public`; this is safe and expected because Azure has not yet
been modified.

- [ ] **Step 2: Confirm the first run stopped before Azure provisioning**

```bash
RUN_ID="$(
  gh run list \
    --repo freeman9844/jjflipbook-azure \
    --workflow azure-dev.yml \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId'
)"
gh run view "$RUN_ID" --repo freeman9844/jjflipbook-azure --log-failed
```

Expected: failure is only anonymous GHCR manifest access. If build or publish
failed, fix that failure before changing package visibility.

- [ ] **Step 3: Make both packages public**

Open these package settings pages while authenticated as `freeman9844`:

- `https://github.com/users/freeman9844/packages/container/package/jjflipbook-azure-backend/settings`
- `https://github.com/users/freeman9844/packages/container/package/jjflipbook-azure-frontend/settings`

For each package, choose **Change visibility**, select **Public**, type the exact
package name, and confirm. GitHub does not provide a documented REST endpoint for
this visibility change, so this is an explicit one-time administrative step.

- [ ] **Step 4: Verify anonymous image access**

Use the SHA from the pushed commit:

```bash
COMMIT_SHA="$(git rev-parse origin/main)"
TOKEN="$(curl -fsS \
  'https://ghcr.io/token?scope=repository:freeman9844/jjflipbook-azure-backend:pull' |
  jq -r .token)"
curl -fsS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  "https://ghcr.io/v2/freeman9844/jjflipbook-azure-backend/manifests/$COMMIT_SHA" \
  >/dev/null

TOKEN="$(curl -fsS \
  'https://ghcr.io/token?scope=repository:freeman9844/jjflipbook-azure-frontend:pull' |
  jq -r .token)"
curl -fsS \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  "https://ghcr.io/v2/freeman9844/jjflipbook-azure-frontend/manifests/$COMMIT_SHA" \
  >/dev/null
```

Expected: both anonymous manifest requests return HTTP 200.

- [ ] **Step 5: Rerun the workflow and monitor it**

```bash
gh run rerun "$RUN_ID" --repo freeman9844/jjflipbook-azure
gh run watch "$RUN_ID" --repo freeman9844/jjflipbook-azure --exit-status
```

Expected sequence:

1. GHCR build/push succeeds.
2. Anonymous pull gate succeeds.
3. Azure OIDC login succeeds.
4. Bicep preview succeeds.
5. Provision succeeds.
6. Frontend/login/list/PDF smoke test succeeds.
7. Old ACR and frontend identity are deleted.
8. GHCR retention succeeds.

- [ ] **Step 6: Verify live Azure state**

```bash
az containerapp list -g rg-jjflipbook \
  --query '[].{
    name:name,
    image:properties.template.containers[0].image,
    cpu:properties.template.containers[0].resources.cpu,
    memory:properties.template.containers[0].resources.memory,
    min:properties.template.scale.minReplicas,
    max:properties.template.scale.maxReplicas,
    rules:properties.template.scale.rules
  }' -o json

az acr list -g rg-jjflipbook -o table
az identity list -g rg-jjflipbook \
  --query "[?starts_with(name, 'id-frontend-')]" -o table
az rest --method get \
  --url "https://management.azure.com$(az storage account show -g rg-jjflipbook -n st3nbgqlm6mwuwo --query id -o tsv)/providers/Microsoft.Security/defenderForStorageSettings/current?api-version=2025-06-01"
```

Expected:

- Both images use `ghcr.io/freeman9844/`.
- Frontend has the daily cron rule and 0.25/0.5 allocation.
- Backend has no cron rule and retains 1/2 allocation.
- ACR list is empty.
- No frontend identity remains.
- Defender response has `isEnabled: false` and
  `overrideSubscriptionLevelSettings: true`.

- [ ] **Step 7: Verify scaling behavior**

During 10:00-20:00 KST:

```bash
az containerapp replica list \
  -g rg-jjflipbook \
  -n "$(az containerapp list -g rg-jjflipbook --query \"[?contains(name, 'frontend')].name | [0]\" -o tsv)" \
  --query 'length(@)' -o tsv
```

Expected: at least one frontend replica.

After smoke-test traffic has been idle for at least 150 seconds:

```bash
az containerapp replica list \
  -g rg-jjflipbook \
  -n "$(az containerapp list -g rg-jjflipbook --query \"[?contains(name, 'backend')].name | [0]\" -o tsv)" \
  --query 'length(@)' -o tsv
```

Expected: zero backend replicas.

- [ ] **Step 8: Record the post-migration cost baseline**

Query the resource group after Cost Management has ingested the deployment day:

```bash
az rest --method post \
  --url "/subscriptions/e9c89382-b9fd-4856-8ae4-647988d62a44/resourceGroups/rg-jjflipbook/providers/Microsoft.CostManagement/query?api-version=2023-11-01" \
  --headers "ClientType=GitHubCopilotForAzure" \
  --body '{
    "type": "ActualCost",
    "timeframe": "MonthToDate",
    "dataset": {
      "granularity": "None",
      "aggregation": {
        "totalCost": {"name": "Cost", "function": "Sum"}
      },
      "grouping": [
        {"type": "Dimension", "name": "ServiceName"}
      ]
    }
  }'
```

Expected after billing settles: no new Container Registry charges and no new
Defender for Storage charges for `st3nbgqlm6mwuwo`. Continue monitoring frontend
idle consumption for one complete billing month before changing the warm window
or minimum resource allocation.
