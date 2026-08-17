# JJFlipBook Azure Subscription Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the complete `jjflipbook-p2` production environment in Azure subscription `43ab425a-c793-4f2e-b71a-0af7a14f26d2`, copy and verify all Blob/Cosmos data, switch GitHub Actions, and delete the source resource group only after proof gates pass.

**Architecture:** Keep the source environment live while the same Bicep topology is provisioned in the target subscription. Use tested migration tools to mirror Blob data, transform Cosmos Blob URL references, freeze and restore Container Apps safely, and produce machine-readable attestations. Cut GitHub Actions over only after final synchronization; destructive cleanup consumes those attestations and validates the live target before deleting the source.

**Tech Stack:** Python 3.11, pytest, Azure Cosmos SDK, Azure Blob SDK, Azure Identity, Azure CLI, Azure Developer CLI, AzCopy v10, Bash, jq, GitHub CLI, GitHub Actions, Bicep

**Spec:** `docs/superpowers/specs/2026-08-17-azure-subscription-migration-design.md`

## Global Constraints

- Source subscription: `8dd0dabf-d8c0-4651-a846-5b13e18e05eb`.
- Target subscription: `43ab425a-c793-4f2e-b71a-0af7a14f26d2`.
- Tenant: `1716e63d-ed31-49bf-aa16-5effd27bc340`.
- Region: `koreacentral`.
- AZD environment and resource group remain `jjflipbook-p2` and `rg-jjflipbook-p2`.
- Rebuild resources in parallel; do not use ARM Move or Resource Mover.
- Keep Cosmos DB `disableLocalAuth: true`; do not create account keys or long-lived SAS tokens.
- Use the existing GitHub OIDC App Registration `jjflipbook-azure-github-p2`.
- Preserve `users`, `folders`, `flipbooks`, and `overlays`; rewrite only source-owned Blob URLs in `flipbooks.image_urls`, `flipbooks.cover_urls`, and `flipbooks.pdf_url`.
- Preserve external overlay `data_url` values unchanged.
- Keep the existing KEDA HTTP rules and `daily-warm-window` schedule unchanged.
- The target Frontend URL changes because there is no custom domain.
- Do not delete the source resource group until data, revisions, smoke tests, KEDA, RBAC, logs, and target GitHub Actions all pass.
- After the proof gates pass, delete the source resource group immediately and revoke the source subscription OIDC roles.
- Preserve the existing uncommitted `README.md` improvements; never discard or overwrite them.
- Execute implementation in an isolated worktree created with `superpowers:using-git-worktrees`.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/subscription_migration.py` | Cosmos copy, Blob/Cosmos manifests, source-to-target URL transformation, verification attestation |
| `scripts/sync_subscription_blobs.sh` | Entra-authenticated AzCopy initial/final synchronization |
| `scripts/subscription_cutover.py` | Capture Container App ingress/revision state, freeze source writes, verify freeze, restore source |
| `scripts/delete_source_environment.sh` | Validate attestations and live target state before deleting the source RG and old OIDC roles |
| `backend/tests/test_subscription_migration.py` | Unit tests for URL transformation, manifests, Cosmos copy, and attestation |
| `backend/tests/test_subscription_cutover.py` | Unit tests for freeze/restore state and Azure CLI commands |
| `backend/tests/test_deployment_config.py` | Shell contract tests, workflow concurrency checks, destructive cleanup refusal/success paths |
| `.github/workflows/azure-dev.yml` | Serialize deployments for one subscription/environment pair |
| `.gitignore` | Ignore local migration evidence under `.azure/migration/` |
| `.azure/deployment-plan.md` | Target subscription runbook and final deployment proof |
| `README.md` | Current deployment behavior, migration target, validation commands, final Frontend URL |

---

### Task 1: Build the data transformation and verification tool

**Files:**
- Create: `scripts/subscription_migration.py`
- Create: `backend/tests/test_subscription_migration.py`

**Interfaces:**
- Produces: `rewrite_flipbook_blob_urls(document: dict, source_blob_base: str, target_blob_base: str) -> dict`
- Produces: `canonical_document(document: dict) -> bytes`
- Produces: `build_cosmos_manifest(container_name: str, documents: Iterable[dict], rewrite_from_blob_base: str | None = None, rewrite_to_blob_base: str | None = None, forbidden_blob_base: str | None = None) -> dict`
- Produces: `build_blob_manifest(blobs: Iterable[object]) -> dict`
- Produces: `copy_cosmos_container(container_name: str, source_container: ContainerProxy, target_container: ContainerProxy, source_blob_base: str, target_blob_base: str, delete_target_extras: bool) -> dict`
- Produces CLI: `cosmos-copy`, `verify`, and `blob-manifest`
- Produces attestation schema version `1` for Task 4 and Task 10

- [ ] **Step 1: Write failing URL transformation and canonicalization tests**

```python
def test_rewrites_only_owned_flipbook_blob_urls():
    source = "https://stsource.blob.core.windows.net/flipbook-assets"
    target = "https://sttarget.blob.core.windows.net/flipbook-assets"
    document = {
        "id": "book-1",
        "image_urls": [f"{source}/flipbooks/book-1/page_1.webp"],
        "cover_urls": [f"{source}/flipbooks/book-1/cover_384.webp"],
        "pdf_url": f"{source}/flipbooks/book-1/original.pdf",
        "external_url": "https://example.com/keep",
        "_etag": "system",
    }

    rewritten = MODULE.rewrite_flipbook_blob_urls(document, source, target)

    assert rewritten["image_urls"] == [
        f"{target}/flipbooks/book-1/page_1.webp"
    ]
    assert rewritten["cover_urls"] == [
        f"{target}/flipbooks/book-1/cover_384.webp"
    ]
    assert rewritten["pdf_url"] == f"{target}/flipbooks/book-1/original.pdf"
    assert rewritten["external_url"] == "https://example.com/keep"
    assert document["image_urls"][0].startswith(source)


def test_canonical_document_removes_only_cosmos_system_fields():
    document = {
        "id": "book-1",
        "title": "Book",
        "_rid": "rid",
        "_self": "self",
        "_etag": "etag",
        "_attachments": "attachments/",
        "_ts": 123,
    }

    assert MODULE.canonical_document(document) == (
        b'{"id":"book-1","title":"Book"}'
    )
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
cd backend
python3 -m pytest tests/test_subscription_migration.py \
  -k 'rewrites_only or canonical_document' -q
```

Expected: FAIL because `scripts/subscription_migration.py` does not exist.

- [ ] **Step 3: Implement system-field removal and exact Blob-base rewriting**

```python
SYSTEM_FIELDS = {"_rid", "_self", "_etag", "_attachments", "_ts"}
FLIPBOOK_URL_FIELDS = ("image_urls", "cover_urls", "pdf_url")


def _rewrite_url(value: str, source_blob_base: str, target_blob_base: str) -> str:
    source = source_blob_base.rstrip("/")
    target = target_blob_base.rstrip("/")
    if value == source:
        return target
    if value.startswith(f"{source}/"):
        return f"{target}/{value[len(source) + 1:]}"
    return value


def rewrite_flipbook_blob_urls(
    document: dict,
    source_blob_base: str,
    target_blob_base: str,
) -> dict:
    rewritten = dict(document)
    for field in ("image_urls", "cover_urls"):
        rewritten[field] = [
            _rewrite_url(value, source_blob_base, target_blob_base)
            for value in rewritten.get(field) or []
        ]
    if rewritten.get("pdf_url"):
        rewritten["pdf_url"] = _rewrite_url(
            rewritten["pdf_url"], source_blob_base, target_blob_base
        )
    return rewritten


def canonical_document(document: dict) -> bytes:
    clean = {
        key: value
        for key, value in document.items()
        if key not in SYSTEM_FIELDS
    }
    return json.dumps(
        clean,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
```

- [ ] **Step 4: Add failing Cosmos manifest and source-host detection tests**

```python
def test_cosmos_manifest_hashes_transformed_source_documents():
    source = "https://stsource.blob.core.windows.net/flipbook-assets"
    target = "https://sttarget.blob.core.windows.net/flipbook-assets"
    source_docs = [{
        "id": "book-1",
        "image_urls": [f"{source}/flipbooks/book-1/page_1.webp"],
    }]
    target_docs = [{
        "id": "book-1",
        "image_urls": [f"{target}/flipbooks/book-1/page_1.webp"],
    }]

    source_manifest = MODULE.build_cosmos_manifest(
        "flipbooks",
        source_docs,
        rewrite_from_blob_base=source,
        rewrite_to_blob_base=target,
        forbidden_blob_base=source,
    )
    target_manifest = MODULE.build_cosmos_manifest(
        "flipbooks",
        target_docs,
        forbidden_blob_base=source,
    )

    assert source_manifest["manifest_sha256"] == target_manifest["manifest_sha256"]
    assert target_manifest["source_url_references_remaining"] == 0


def test_blob_manifest_uses_name_size_and_available_md5():
    blobs = [
        SimpleNamespace(
            name="bgm/song.mp3",
            size=12,
            content_settings=SimpleNamespace(content_md5=b"\x01\x02"),
        ),
        SimpleNamespace(
            name="flipbooks/book/page.webp",
            size=34,
            content_settings=SimpleNamespace(content_md5=None),
        ),
    ]

    manifest = MODULE.build_blob_manifest(blobs)

    assert manifest["count"] == 2
    assert manifest["total_bytes"] == 46
    assert manifest["entries"][0] == {
        "name": "bgm/song.mp3",
        "size": 12,
        "content_md5": "AQI=",
    }
```

- [ ] **Step 5: Implement deterministic Cosmos and Blob manifests**

`build_cosmos_manifest()` must:

1. Rewrite Blob URLs only when `container_name == "flipbooks"` and both rewrite Blob bases are supplied.
2. Remove Cosmos system fields.
3. Hash each canonical document with SHA-256.
4. Sort entries by `(partition_key, id)`.
5. Hash the compact JSON encoding of the sorted entries.
6. Count occurrences of `forbidden_blob_base` in every canonical document.

Use this exact partition-key map:

```python
CONTAINER_PARTITION_KEYS = {
    "users": "id",
    "folders": "id",
    "flipbooks": "id",
    "overlays": "bookId",
}
```

`build_blob_manifest()` must sort entries by Blob name and return:

```python
{
    "count": len(entries),
    "total_bytes": sum(entry["size"] for entry in entries),
    "manifest_sha256": hashlib.sha256(canonical_entries).hexdigest(),
    "entries": entries,
}
```

- [ ] **Step 6: Add failing Cosmos copy tests with fake containers**

```python
def test_copy_cosmos_container_upserts_transformed_docs_and_deletes_extras():
    source = FakeContainer([
        {
            "id": "book-1",
            "image_urls": [
                "https://stsource.blob.core.windows.net/"
                "flipbook-assets/flipbooks/book-1/page_1.webp"
            ],
        }
    ])
    target = FakeContainer([
        {"id": "old-book", "image_urls": []}
    ])

    result = MODULE.copy_cosmos_container(
        container_name="flipbooks",
        source_container=source,
        target_container=target,
        source_blob_base=(
            "https://stsource.blob.core.windows.net/flipbook-assets"
        ),
        target_blob_base=(
            "https://sttarget.blob.core.windows.net/flipbook-assets"
        ),
        delete_target_extras=True,
    )

    assert result == {"upserted": 1, "deleted": 1}
    assert target.upserted[0]["image_urls"][0].startswith(
        "https://sttarget.blob.core.windows.net/"
    )
    assert target.deleted == [("old-book", "old-book")]
```

- [ ] **Step 7: Implement Cosmos copy and CLI subcommands**

Use `AzureCliCredential(tenant_id=args.tenant_id)` and the existing pinned
`azure-cosmos`, `azure-identity`, and `azure-storage-blob` dependencies.
Do not add a dependency.

CLI contract:

```text
subscription_migration.py cosmos-copy
  --tenant-id
  --source-cosmos-endpoint
  --target-cosmos-endpoint
  --source-storage-account
  --target-storage-account
  --database-name
  --container-name users|folders|flipbooks|overlays|all
  [--delete-target-extras]

subscription_migration.py verify
  --tenant-id
  --source-subscription-id
  --target-subscription-id
  --source-resource-group
  --target-resource-group
  --source-cosmos-endpoint
  --target-cosmos-endpoint
  --source-storage-account
  --target-storage-account
  --blob-container-name
  --database-name
  --output

subscription_migration.py blob-manifest
  --tenant-id
  --storage-account
  --blob-container-name
  --output
```

`verify` must atomically write a regular JSON file with this shape:

For `flipbooks`, build the source manifest with
`rewrite_from_blob_base=source`, `rewrite_to_blob_base=target`, and
`forbidden_blob_base=source`; build the target manifest with only
`forbidden_blob_base=source`. Compare those two transformed manifests.

```json
{
  "schema_version": 1,
  "completed": true,
  "source_subscription_id": "8dd0dabf-d8c0-4651-a846-5b13e18e05eb",
  "target_subscription_id": "43ab425a-c793-4f2e-b71a-0af7a14f26d2",
  "source_resource_group": "rg-jjflipbook-p2",
  "target_resource_group": "rg-jjflipbook-p2",
  "source_storage_account": "stx2zom66whjavy",
  "target_storage_account": "stexampletarget01",
  "blob": {
    "matched": true,
    "count": 0,
    "total_bytes": 0,
    "manifest_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "cosmos": {
    "matched": true,
    "source_url_references_remaining": 0,
    "containers": {}
  },
  "verified_at": "ISO-8601 UTC"
}
```

Exit nonzero and do not write `completed: true` when any count, byte total,
manifest digest, document digest, or source-host check differs.

- [ ] **Step 8: Run the migration tool tests**

Run:

```bash
cd backend
python3 -m pytest tests/test_subscription_migration.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit the data migration tool**

```bash
git add scripts/subscription_migration.py \
  backend/tests/test_subscription_migration.py
git commit -m "feat: add subscription data migration tool"
```

---

### Task 2: Add Entra-authenticated Blob synchronization

**Files:**
- Create: `scripts/sync_subscription_blobs.sh`
- Modify: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Consumes: Azure CLI login in tenant `1716e63d-ed31-49bf-aa16-5effd27bc340`
- Produces: `sync_subscription_blobs.sh initial|final`
- `initial` never deletes target-only blobs
- `final` sets `--delete-destination=true` to make the target an exact mirror

- [ ] **Step 1: Write a failing shell contract test**

Add a fake `azcopy` executable that records arguments, then invoke the script
twice:

```python
def test_blob_sync_uses_azure_cli_identity_and_final_exact_mirror(tmp_path):
    # Fake azcopy writes its argv and selected environment to a log file.
    initial = _run_blob_sync(tmp_path, "initial")
    final = _run_blob_sync(tmp_path, "final")

    assert "--from-to=BlobBlob" in initial
    assert "--recursive=true" in initial
    assert "--delete-destination=false" in initial
    assert "--delete-destination=true" in final
    assert "AZCOPY_AUTO_LOGIN_TYPE=AZCLI" in final
    assert (
        "AZCOPY_TENANT_ID=1716e63d-ed31-49bf-aa16-5effd27bc340"
        in final
    )
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd backend
python3 -m pytest tests/test_deployment_config.py \
  -k blob_sync_uses_azure_cli_identity -q
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement the exact AzCopy wrapper**

```bash
#!/usr/bin/env bash
set -euo pipefail

MODE="${1:?Usage: sync_subscription_blobs.sh initial|final}"
: "${AZURE_TENANT_ID:?AZURE_TENANT_ID is required}"
: "${SOURCE_STORAGE_ACCOUNT:?SOURCE_STORAGE_ACCOUNT is required}"
: "${TARGET_STORAGE_ACCOUNT:?TARGET_STORAGE_ACCOUNT is required}"
: "${BLOB_CONTAINER_NAME:?BLOB_CONTAINER_NAME is required}"

command -v azcopy >/dev/null || {
  echo "azcopy v10 is required." >&2
  exit 1
}

case "$MODE" in
  initial) DELETE_DESTINATION=false ;;
  final) DELETE_DESTINATION=true ;;
  *)
    echo "Mode must be initial or final." >&2
    exit 1
    ;;
esac

export AZCOPY_AUTO_LOGIN_TYPE=AZCLI
export AZCOPY_TENANT_ID="$AZURE_TENANT_ID"

azcopy sync \
  "https://${SOURCE_STORAGE_ACCOUNT}.blob.core.windows.net/${BLOB_CONTAINER_NAME}" \
  "https://${TARGET_STORAGE_ACCOUNT}.blob.core.windows.net/${BLOB_CONTAINER_NAME}" \
  --from-to=BlobBlob \
  --recursive=true \
  --delete-destination="$DELETE_DESTINATION"
```

- [ ] **Step 4: Add refusal tests**

Cover invalid mode, same source/target account, missing `azcopy`, and missing
required environment variables. Add an explicit same-account check before
calling AzCopy:

```bash
if [[ "$SOURCE_STORAGE_ACCOUNT" == "$TARGET_STORAGE_ACCOUNT" ]]; then
  echo "Source and target Storage Accounts must differ." >&2
  exit 1
fi
```

- [ ] **Step 5: Run the shell contract tests**

Run:

```bash
cd backend
python3 -m pytest tests/test_deployment_config.py \
  -k 'blob_sync' -q
```

Expected: PASS.

- [ ] **Step 6: Commit Blob synchronization**

```bash
git add scripts/sync_subscription_blobs.sh \
  backend/tests/test_deployment_config.py
git commit -m "feat: add subscription blob synchronization"
```

---

### Task 3: Add reversible Container Apps freeze and restore

**Files:**
- Create: `scripts/subscription_cutover.py`
- Create: `backend/tests/test_subscription_cutover.py`

**Interfaces:**
- Produces CLI: `freeze`, `verify-frozen`, `restore`, `disable-ingress`
- Produces state schema version `1`
- `freeze` writes state before changing Azure resources
- `restore` consumes the state file and restores exact ingress settings and active revisions

- [ ] **Step 1: Write failing state-capture tests**

```python
def test_build_freeze_state_requires_backend_and_frontend():
    apps = [
        app("ca-backend", "backend", external=False, target_port=8000),
        app("ca-frontend", "frontend", external=True, target_port=3000),
    ]
    revisions = {
        "ca-backend": [revision("ca-backend--0000004")],
        "ca-frontend": [revision("ca-frontend--0000004")],
    }

    state = MODULE.build_freeze_state(
        subscription_id="source-sub",
        resource_group="rg-jjflipbook-p2",
        apps=apps,
        revisions_by_app=revisions,
    )

    assert state["schema_version"] == 1
    assert [item["service"] for item in state["apps"]] == [
        "backend", "frontend"
    ]
    assert state["apps"][1]["ingress"]["external"] is True
    assert state["apps"][1]["active_revisions"] == [
        "ca-frontend--0000004"
    ]
```

- [ ] **Step 2: Run the focused tests and verify they fail**

```bash
cd backend
python3 -m pytest tests/test_subscription_cutover.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement state capture and atomic file writing**

State shape:

```json
{
  "schema_version": 1,
  "subscription_id": "8dd0dabf-d8c0-4651-a846-5b13e18e05eb",
  "resource_group": "rg-jjflipbook-p2",
  "frozen": false,
  "apps": [
    {
      "service": "frontend",
      "name": "ca-frontend-x2zom66whjavy",
      "ingress": {
        "external": true,
        "targetPort": 3000,
        "transport": "Auto",
        "allowInsecure": false
      },
      "active_revisions": ["ca-frontend-x2zom66whjavy--0000004"]
    }
  ]
}
```

Write to a sibling temporary file, `fsync`, then `os.replace()`. Refuse symlink
state paths.

- [ ] **Step 4: Add failing freeze/restore command tests**

Mock the command runner and assert this order:

```text
freeze:
  az containerapp ingress disable
  az containerapp revision deactivate
  verify no ingress and no active revisions
  rewrite state with frozen=true

restore:
  az containerapp revision activate
  az containerapp ingress enable --type internal|external
  verify expected revisions are active
```

For ingress restore, preserve `targetPort`, `transport`, and `allowInsecure`.

- [ ] **Step 5: Implement Azure CLI operations without shell interpolation**

Use `subprocess.run(command, check=True, text=True, capture_output=True)` with
argument arrays. Discover apps by the existing `azd-service-name` tags and
require exactly one Backend and one Frontend.

CLI contract:

```text
subscription_cutover.py freeze
  --subscription
  --resource-group
  --state-file

subscription_cutover.py verify-frozen
  --state-file

subscription_cutover.py restore
  --state-file

subscription_cutover.py disable-ingress
  --subscription
  --resource-group
```

`freeze` must create the state file before the first Azure mutation. If a later
mutation fails, print `python3 scripts/subscription_cutover.py restore --state-file "$STATE_FILE"` and exit
nonzero; do not silently continue.

- [ ] **Step 6: Run cutover tests**

```bash
cd backend
python3 -m pytest tests/test_subscription_cutover.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit cutover tooling**

```bash
git add scripts/subscription_cutover.py \
  backend/tests/test_subscription_cutover.py
git commit -m "feat: add reversible subscription cutover"
```

---

### Task 4: Add the proof-gated source deletion script

**Files:**
- Create: `scripts/delete_source_environment.sh`
- Modify: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Consumes: Task 1 migration attestation
- Consumes: existing `scripts/smoke_test_deployment.sh` attestation
- Consumes: Task 3 source freeze state
- Consumes: successful GitHub Actions run ID and expected commit SHA
- Produces: deletion of source `rg-jjflipbook-p2`, revocation of source OIDC roles, and revocation of temporary target data roles

- [ ] **Step 1: Write refusal-path tests**

Add fake `az`, `gh`, and state files. Assert the script exits before any
`az group delete` call when:

1. An attestation is missing, a symlink, or not a regular file.
2. Source and target subscription IDs do not match the approved IDs.
3. Blob or Cosmos `matched` is not `true`.
4. `source_url_references_remaining` is not `0`.
5. Smoke attestation Frontend URL differs.
6. GitHub run conclusion is not `success` or `headSha` differs.
7. Source is not frozen.
8. Target KEDA, Backend RBAC, or post-revision error-log checks fail.
9. Confirmation text differs.

Use this exact confirmation:

```text
delete:8dd0dabf-d8c0-4651-a846-5b13e18e05eb:rg-jjflipbook-p2
```

- [ ] **Step 2: Run refusal tests and verify they fail**

```bash
cd backend
python3 -m pytest tests/test_deployment_config.py \
  -k delete_source_environment -q
```

Expected: FAIL because the cleanup script does not exist.

- [ ] **Step 3: Implement proof validation**

Require these environment variables:

```text
SOURCE_SUBSCRIPTION_ID
TARGET_SUBSCRIPTION_ID
SOURCE_RESOURCE_GROUP
TARGET_RESOURCE_GROUP
TARGET_FRONTEND_URL
EXPECTED_GITHUB_SHA
TARGET_WORKFLOW_RUN_ID
MIGRATION_ATTESTATION_FILE
SMOKE_ATTESTATION_FILE
SOURCE_FREEZE_STATE_FILE
AZURE_CLIENT_ID
MIGRATION_PRINCIPAL_OBJECT_ID
TARGET_STORAGE_RESOURCE_ID
TARGET_COSMOS_RESOURCE_ID
CONFIRM_DELETE_SOURCE_RG
```

Validate migration proof with `jq -e`:

```jq
.schema_version == 1 and
.completed == true and
.source_subscription_id == $source_subscription and
.target_subscription_id == $target_subscription and
.source_resource_group == $source_rg and
.target_resource_group == $target_rg and
.blob.matched == true and
.cosmos.matched == true and
.cosmos.source_url_references_remaining == 0
```

Validate the GitHub run:

```bash
RUN_JSON="$(
  gh run view "$TARGET_WORKFLOW_RUN_ID" \
    --repo freeman9844/jjflipbook-azure \
    --json conclusion,headSha,status,workflowName
)"
jq -e \
  --arg sha "$EXPECTED_GITHUB_SHA" \
  '.status == "completed" and
   .conclusion == "success" and
   .headSha == $sha and
   .workflowName == "Azure deployment"' \
  <<<"$RUN_JSON" >/dev/null
```

- [ ] **Step 4: Verify the live target and frozen source**

Implement these checks before deletion:

```bash
python3 scripts/subscription_cutover.py verify-frozen \
  --state-file "$SOURCE_FREEZE_STATE_FILE"

TARGET_APPS_JSON="$(
  az containerapp list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --output json
)"
jq -e '
  [.[] | select(
    .tags["azd-service-name"] == "backend" or
    .tags["azd-service-name"] == "frontend"
  )] as $apps |
  ($apps | length) == 2 and
  all($apps[];
    ([.properties.template.scale.rules[].name] | index("daily-warm-window")) != null and
    any(.properties.template.scale.rules[]; has("http"))
  )
' <<<"$TARGET_APPS_JSON" >/dev/null

while IFS=$'\t' read -r app_name service; do
  EXPECTED_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-${service}:${EXPECTED_GITHUB_SHA}"
  az containerapp revision list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --name "$app_name" \
    --output json |
    jq -e --arg image "$EXPECTED_IMAGE" '
      [.[] | select(.properties.active == true)] as $active |
      ($active | length) == 1 and
      $active[0].properties.healthState == "Healthy" and
      $active[0].properties.provisioningState == "Provisioned" and
      [$active[0].properties.template.containers[]?.image] == [$image]
    ' >/dev/null
done < <(
  jq -r '
    .[] |
    select(
      .tags["azd-service-name"] == "backend" or
      .tags["azd-service-name"] == "frontend"
    ) |
    [.name, .tags["azd-service-name"]] |
    @tsv
  ' <<<"$TARGET_APPS_JSON"
)

BACKEND_ID_NAME="$(
  az identity list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --query "[?starts_with(name, 'id-backend-')].name | [0]" \
    -o tsv
)"
BACKEND_PRINCIPAL_ID="$(
  az identity show \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --name "$BACKEND_ID_NAME" \
    --query principalId -o tsv
)"
test "$(
  az role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --assignee-object-id "$BACKEND_PRINCIPAL_ID" \
    --scope "$TARGET_STORAGE_RESOURCE_ID" \
    --query "[?roleDefinitionName=='Storage Blob Data Contributor'] | length(@)" \
    -o tsv
)" = "1"
test "$(
  az role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --assignee-object-id "$BACKEND_PRINCIPAL_ID" \
    --all \
    --query '[].roleDefinitionName | sort(@) | join(`,`, @)' \
    -o tsv
)" = "Storage Blob Data Contributor"

TARGET_COSMOS_ACCOUNT="$(
  az cosmosdb list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --query '[0].name' -o tsv
)"
test "$(
  az cosmosdb sql role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --account-name "$TARGET_COSMOS_ACCOUNT" \
    --query "[?principalId=='${BACKEND_PRINCIPAL_ID}' && ends_with(roleDefinitionId, '00000000-0000-0000-0000-000000000002')] | length(@)" \
    -o tsv
)" = "1"

TARGET_LOG_WORKSPACE="$(
  az monitor log-analytics workspace list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --query '[0].customerId' -o tsv
)"
FINAL_REVISION_START="$(
  while IFS= read -r app_name; do
    az containerapp revision list \
      --subscription "$TARGET_SUBSCRIPTION_ID" \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$app_name" \
      --query "[?properties.active].properties.createdTime | [0]" \
      -o tsv
  done < <(jq -r '.[].name' <<<"$TARGET_APPS_JSON") |
    sort |
    head -n 1
)"
ERROR_COUNT="$(
  az monitor log-analytics query \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --workspace "$TARGET_LOG_WORKSPACE" \
    --analytics-query "
      union isfuzzy=true ContainerAppConsoleLogs_CL, ContainerAppSystemLogs_CL
      | where TimeGenerated >= datetime(${FINAL_REVISION_START})
      | where Log_s matches regex @'(?i)(error|exception|traceback)'
      | count
    " \
    --query 'tables[0].rows[0][0]' -o tsv
)"
test "$ERROR_COUNT" = "0"
```

- [ ] **Step 5: Implement deletion and role cleanup**

Only after all checks pass:

```bash
az group delete \
  --subscription "$SOURCE_SUBSCRIPTION_ID" \
  --name "$SOURCE_RESOURCE_GROUP" \
  --yes \
  --no-wait

az group wait \
  --subscription "$SOURCE_SUBSCRIPTION_ID" \
  --name "$SOURCE_RESOURCE_GROUP" \
  --deleted \
  --interval 15 \
  --timeout 1800
```

Resolve the OIDC Service Principal object ID and remove only the two exact
source subscription role assignments:

```bash
OIDC_SP_OBJECT_ID="$(
  az ad sp show --id "$AZURE_CLIENT_ID" --query id -o tsv
)"
for role in Contributor "Role Based Access Control Administrator"; do
  az role assignment delete \
    --assignee-object-id "$OIDC_SP_OBJECT_ID" \
    --role "$role" \
    --scope "/subscriptions/$SOURCE_SUBSCRIPTION_ID"
done
```

Remove the migration principal's temporary target data roles only at the two
provided resource IDs:

```bash
az role assignment delete \
  --assignee-object-id "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  --role "Storage Blob Data Contributor" \
  --scope "$TARGET_STORAGE_RESOURCE_ID"
az role assignment delete \
  --assignee-object-id "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  --role "Cosmos DB Built-in Data Contributor" \
  --scope "$TARGET_COSMOS_RESOURCE_ID"
```

- [ ] **Step 6: Add a success-path test**

The fake commands must show this order:

```text
verify target -> verify source frozen -> group delete -> group wait
-> delete source Contributor -> delete source RBAC Administrator
-> delete target temporary Storage role -> delete target temporary Cosmos role
```

- [ ] **Step 7: Run cleanup tests**

```bash
cd backend
python3 -m pytest tests/test_deployment_config.py \
  -k delete_source_environment -q
```

Expected: PASS.

- [ ] **Step 8: Commit the destructive cleanup gate**

```bash
git add scripts/delete_source_environment.sh \
  backend/tests/test_deployment_config.py
git commit -m "feat: gate source subscription cleanup"
```

---

### Task 5: Serialize deployments and document the migration runbook

**Files:**
- Modify: `.github/workflows/azure-dev.yml`
- Modify: `backend/tests/test_deployment_config.py`
- Modify: `.gitignore`
- Modify: `.azure/deployment-plan.md`
- Modify: `README.md`

**Interfaces:**
- Produces: one active deployment per subscription/environment pair
- Produces: ignored local evidence directory `.azure/migration/`
- Preserves: the existing uncommitted README improvements

- [ ] **Step 1: Write a failing workflow concurrency test**

```python
def test_workflow_serializes_each_azure_environment():
    workflow = _load_workflow()
    assert workflow.startswith("name: Azure deployment\n")
    assert "concurrency:" in workflow
    assert (
        "group: azure-${{ vars.AZURE_SUBSCRIPTION_ID }}-"
        "${{ vars.AZURE_ENV_NAME }}" in workflow
    )
    assert "cancel-in-progress: false" in workflow
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd backend
python3 -m pytest tests/test_deployment_config.py \
  -k workflow_serializes_each_azure_environment -q
```

Expected: FAIL because the workflow has no concurrency group.

- [ ] **Step 3: Name and serialize the workflow**

Add this as the first line:

```yaml
name: Azure deployment
```

Place this after `permissions` and before `jobs`:

```yaml
concurrency:
  group: azure-${{ vars.AZURE_SUBSCRIPTION_ID }}-${{ vars.AZURE_ENV_NAME }}
  cancel-in-progress: false
```

Add a Korean comment explaining that automatic pushes and manual deployments
are queued instead of colliding on the `resources` ARM deployment.

- [ ] **Step 4: Ignore migration evidence**

Add:

```gitignore
# Local Azure subscription migration evidence
.azure/migration/
```

Do not ignore `.azure/deployment-plan.md`.

- [ ] **Step 5: Replace the deployment plan with the approved target runbook**

Set:

```text
Status: Planned
Mode: Parallel rebuild and verified cutover
Source: 8dd0dabf-d8c0-4651-a846-5b13e18e05eb
Target: 43ab425a-c793-4f2e-b71a-0af7a14f26d2
Tenant: 1716e63d-ed31-49bf-aa16-5effd27bc340
Environment/RG: jjflipbook-p2 / rg-jjflipbook-p2
```

Link the design and this plan. Include the proof file names:

```text
.azure/migration/source-freeze.json
.azure/migration/data-verification.json
.azure/migration/smoke-attestation.json
```

- [ ] **Step 6: Finish the pending README enhancement without losing it**

The primary checkout contains the pending README enhancement, while the
isolated implementation worktree does not. Import it before editing:

```bash
PRIMARY_REPO="$(
  git worktree list --porcelain |
    awk '/^worktree / {print $2; exit}'
)"
README_PATCH="$(mktemp)"
git -C "$PRIMARY_REPO" diff -- README.md > "$README_PATCH"
test -s "$README_PATCH"
git apply --check "$README_PATCH"
git apply "$README_PATCH"
rm -f -- "$README_PATCH"
```

Keep every existing local README improvement about:

- Both apps using `daily-warm-window`.
- Runtime Backend URL.
- Admin password synchronization.
- OIDC and `validate_only`.
- Revision convergence and smoke tests.
- GHCR retention.

Add an operations subsection documenting the approved target subscription,
the new URL behavior, and the verification commands from the spec. Do not put
secrets or attestation contents in README.

- [ ] **Step 7: Run the deployment contract tests**

```bash
az bicep build --file infra/main.bicep --outfile infra/main.json
cd backend
python3 -m pytest tests/test_deployment_config.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit workflow and runbook changes**

```bash
git add .github/workflows/azure-dev.yml \
  backend/tests/test_deployment_config.py \
  .gitignore \
  .azure/deployment-plan.md \
  README.md
git commit -m "docs: prepare verified subscription migration"
```

- [ ] **Step 9: Run the complete local test set before cloud operations**

```bash
cd backend
python3 -m pytest tests -q
cd ../frontend
npx jest --runInBand
```

Expected: all existing and new tests pass.

- [ ] **Step 10: Push tooling while GitHub still targets the source**

```bash
BEFORE_SOURCE_RUN_ID="$(
  gh run list \
    --repo freeman9844/jjflipbook-azure \
    --workflow azure-dev.yml \
    --branch main \
    --event push \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // 0'
)"
git push origin main
for attempt in $(seq 1 30); do
  SOURCE_DEPLOY_RUN_ID="$(
    gh run list \
      --repo freeman9844/jjflipbook-azure \
      --workflow azure-dev.yml \
      --branch main \
      --event push \
      --limit 1 \
      --json databaseId \
      --jq '.[0].databaseId // 0'
  )"
  [[ "$SOURCE_DEPLOY_RUN_ID" != "$BEFORE_SOURCE_RUN_ID" ]] && break
  (( attempt < 30 )) || exit 1
  sleep 2
done
gh run watch "$SOURCE_DEPLOY_RUN_ID" \
  --repo freeman9844/jjflipbook-azure \
  --exit-status
```

Do not start a manual full workflow at the same time.

---

### Task 6: Prepare the target subscription and isolated AZD environment

**Files:**
- Create locally only: `.azure/migration/source-resources.json`
- Create locally only: `.azure/migration/target-resources.json`

**Interfaces:**
- Consumes: committed migration tooling
- Produces: registered providers, target OIDC roles, captured source inventory
- Produces locally: `.azure/migration/context.env`, mode `0600`, for values that must persist across fresh shell processes

- [ ] **Step 1: Establish constants and verify both subscriptions share the tenant**

```bash
export SOURCE_SUBSCRIPTION_ID="8dd0dabf-d8c0-4651-a846-5b13e18e05eb"
export TARGET_SUBSCRIPTION_ID="43ab425a-c793-4f2e-b71a-0af7a14f26d2"
export AZURE_TENANT_ID="1716e63d-ed31-49bf-aa16-5effd27bc340"
export AZURE_ENV_NAME="jjflipbook-p2"
export AZURE_LOCATION="koreacentral"
export RESOURCE_GROUP="rg-jjflipbook-p2"
mkdir -p .azure/migration
umask 077
printf '%s=%q\n' \
  SOURCE_SUBSCRIPTION_ID "$SOURCE_SUBSCRIPTION_ID" \
  TARGET_SUBSCRIPTION_ID "$TARGET_SUBSCRIPTION_ID" \
  AZURE_TENANT_ID "$AZURE_TENANT_ID" \
  AZURE_ENV_NAME "$AZURE_ENV_NAME" \
  AZURE_LOCATION "$AZURE_LOCATION" \
  RESOURCE_GROUP "$RESOURCE_GROUP" \
  > .azure/migration/context.env
chmod 600 .azure/migration/context.env

az account show --subscription "$SOURCE_SUBSCRIPTION_ID" \
  --query '{id:id,tenantId:tenantId,state:state}' -o jsonc
az account show --subscription "$TARGET_SUBSCRIPTION_ID" \
  --query '{id:id,tenantId:tenantId,state:state}' -o jsonc
```

Expected: both states are `Enabled` and both tenant IDs equal
`1716e63d-ed31-49bf-aa16-5effd27bc340`.

- [ ] **Step 2: Register required Resource Providers**

```bash
source .azure/migration/context.env
for provider in \
  Microsoft.App \
  Microsoft.DocumentDB \
  Microsoft.ManagedIdentity \
  Microsoft.OperationalInsights \
  Microsoft.Storage
do
  az provider register \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --namespace "$provider" \
    --wait
done

az provider show \
  --subscription "$TARGET_SUBSCRIPTION_ID" \
  --namespace Microsoft.App \
  --query registrationState -o tsv
```

Expected: each provider returns `Registered`.

- [ ] **Step 3: Grant the existing OIDC Service Principal target deployment roles**

```bash
source .azure/migration/context.env
export AZURE_CLIENT_ID="$(
  gh variable get AZURE_CLIENT_ID \
    --repo freeman9844/jjflipbook-azure
)"
export OIDC_SP_OBJECT_ID="$(
  az ad sp show --id "$AZURE_CLIENT_ID" --query id -o tsv
)"
export TARGET_SCOPE="/subscriptions/$TARGET_SUBSCRIPTION_ID"
printf '%s=%q\n' \
  AZURE_CLIENT_ID "$AZURE_CLIENT_ID" \
  OIDC_SP_OBJECT_ID "$OIDC_SP_OBJECT_ID" \
  TARGET_SCOPE "$TARGET_SCOPE" \
  >> .azure/migration/context.env

for role in Contributor "Role Based Access Control Administrator"; do
  az role assignment create \
    --assignee-object-id "$OIDC_SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "$role" \
    --scope "$TARGET_SCOPE"
done
```

List the assignments and require exactly those two direct target-subscription
roles before continuing.

- [ ] **Step 4: Capture source resource inventory**

```bash
source .azure/migration/context.env
az resource list \
  --subscription "$SOURCE_SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --query '[].{id:id,name:name,type:type,location:location}' \
  -o json > .azure/migration/source-resources.json

jq -e '
  any(.type == "Microsoft.App/containerApps") and
  any(.type == "Microsoft.DocumentDB/databaseAccounts") and
  any(.type == "Microsoft.Storage/storageAccounts")
' .azure/migration/source-resources.json >/dev/null
```

- [ ] **Step 5: Confirm GitHub still targets the source**

```bash
source .azure/migration/context.env
gh variable get AZURE_SUBSCRIPTION_ID \
  --repo freeman9844/jjflipbook-azure
```

Expected: `8dd0dabf-d8c0-4651-a846-5b13e18e05eb`.

- [ ] **Step 6: Create the target AZD environment in the isolated worktree**

```bash
source .azure/migration/context.env
export PRIMARY_REPO="$(
  git worktree list --porcelain |
    awk '/^worktree / {print $2; exit}'
)"

azd env new "$AZURE_ENV_NAME" \
  --subscription "$TARGET_SUBSCRIPTION_ID" \
  --location "$AZURE_LOCATION" \
  --no-prompt

for key in ADMIN_PASSWORD INTERNAL_API_KEY SESSION_SECRET; do
  value="$(azd env get-value -C "$PRIMARY_REPO" -e "$AZURE_ENV_NAME" "$key")"
  azd env set "$key" "$value"
  unset value
done
```

Do not print the three secret values.

- [ ] **Step 7: Set immutable images and verify they are public**

```bash
source .azure/migration/context.env
export MIGRATION_SHA="$(git rev-parse HEAD)"
export BACKEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-backend:$MIGRATION_SHA"
export FRONTEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-frontend:$MIGRATION_SHA"

docker manifest inspect "$BACKEND_IMAGE" >/dev/null
docker manifest inspect "$FRONTEND_IMAGE" >/dev/null

azd env set BACKEND_IMAGE "$BACKEND_IMAGE"
azd env set FRONTEND_IMAGE "$FRONTEND_IMAGE"
printf '%s=%q\n' \
  MIGRATION_SHA "$MIGRATION_SHA" \
  BACKEND_IMAGE "$BACKEND_IMAGE" \
  FRONTEND_IMAGE "$FRONTEND_IMAGE" \
  >> .azure/migration/context.env
```

---

### Task 7: Provision the target and perform the initial copy

**Files:**
- Create locally only: `.azure/migration/target-preview.txt`
- Create locally only: `.azure/migration/target-resources.json`
- Create locally only: `.azure/migration/target-disabled.json`

**Interfaces:**
- Consumes: Task 6 target AZD environment
- Produces: complete target infrastructure, disabled target ingress, first Blob/Cosmos copy

- [ ] **Step 1: Preview target infrastructure**

```bash
source .azure/migration/context.env
az account set --subscription "$TARGET_SUBSCRIPTION_ID"

ADMIN_PASSWORD="$(azd env get-value ADMIN_PASSWORD)"
INTERNAL_API_KEY="$(azd env get-value INTERNAL_API_KEY)"
SESSION_SECRET="$(azd env get-value SESSION_SECRET)"
export ADMIN_PASSWORD INTERNAL_API_KEY SESSION_SECRET

azd provision --preview --no-prompt |
  tee .azure/migration/target-preview.txt
```

Review the output. It must target `rg-jjflipbook-p2` in the target subscription
and must not reference source resource IDs.

- [ ] **Step 2: Provision the target**

```bash
source .azure/migration/context.env
azd provision --no-prompt
unset ADMIN_PASSWORD INTERNAL_API_KEY SESSION_SECRET

AZURE_ENV_NAME="$AZURE_ENV_NAME" \
BACKEND_IMAGE="$BACKEND_IMAGE" \
FRONTEND_IMAGE="$FRONTEND_IMAGE" \
bash scripts/wait_for_revision_convergence.sh
```

- [ ] **Step 3: Discover and persist target resource names**

```bash
source .azure/migration/context.env
az resource list \
  --subscription "$TARGET_SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --query '[].{id:id,name:name,type:type,location:location}' \
  -o json > .azure/migration/target-resources.json

export TARGET_STORAGE_ACCOUNT="$(
  jq -er '.[] | select(.type == "Microsoft.Storage/storageAccounts") | .name' \
    .azure/migration/target-resources.json
)"
export TARGET_COSMOS_ACCOUNT="$(
  jq -er '.[] | select(.type == "Microsoft.DocumentDB/databaseAccounts") | .name' \
    .azure/migration/target-resources.json
)"
export TARGET_COSMOS_ENDPOINT="$(
  az cosmosdb show \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --name "$TARGET_COSMOS_ACCOUNT" \
    --query documentEndpoint -o tsv
)"
printf '%s=%q\n' \
  TARGET_STORAGE_ACCOUNT "$TARGET_STORAGE_ACCOUNT" \
  TARGET_COSMOS_ACCOUNT "$TARGET_COSMOS_ACCOUNT" \
  TARGET_COSMOS_ENDPOINT "$TARGET_COSMOS_ENDPOINT" \
  >> .azure/migration/context.env

test "$(
  jq '[.[] | select(.type == "Microsoft.Storage/storageAccounts")] | length' \
    .azure/migration/target-resources.json
)" = "1"
test "$(
  jq '[.[] | select(.type == "Microsoft.DocumentDB/databaseAccounts")] | length' \
    .azure/migration/target-resources.json
)" = "1"
```

- [ ] **Step 4: Disable target ingress during data loading**

```bash
source .azure/migration/context.env
python3 scripts/subscription_cutover.py disable-ingress \
  --subscription "$TARGET_SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP"
```

- [ ] **Step 5: Grant temporary data-plane roles**

```bash
source .azure/migration/context.env
export MIGRATION_PRINCIPAL_OBJECT_ID="$(
  az ad signed-in-user show --query id -o tsv
)"
export TARGET_STORAGE_RESOURCE_ID="$(
  jq -er '.[] | select(.type == "Microsoft.Storage/storageAccounts") | .id' \
    .azure/migration/target-resources.json
)"
export TARGET_COSMOS_RESOURCE_ID="$(
  jq -er '.[] | select(.type == "Microsoft.DocumentDB/databaseAccounts") | .id' \
    .azure/migration/target-resources.json
)"
export SOURCE_STORAGE_RESOURCE_ID="$(
  jq -er '.[] | select(.type == "Microsoft.Storage/storageAccounts") | .id' \
    .azure/migration/source-resources.json
)"
export SOURCE_COSMOS_RESOURCE_ID="$(
  jq -er '.[] | select(.type == "Microsoft.DocumentDB/databaseAccounts") | .id' \
    .azure/migration/source-resources.json
)"

az role assignment create \
  --assignee-object-id "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  --role "Storage Blob Data Contributor" \
  --scope "$SOURCE_STORAGE_RESOURCE_ID"
az role assignment create \
  --assignee-object-id "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  --role "Storage Blob Data Contributor" \
  --scope "$TARGET_STORAGE_RESOURCE_ID"
az role assignment create \
  --assignee-object-id "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  --role "Cosmos DB Built-in Data Contributor" \
  --scope "$SOURCE_COSMOS_RESOURCE_ID"
az role assignment create \
  --assignee-object-id "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  --role "Cosmos DB Built-in Data Contributor" \
  --scope "$TARGET_COSMOS_RESOURCE_ID"

export SOURCE_STORAGE_ACCOUNT="stx2zom66whjavy"
export SOURCE_COSMOS_ENDPOINT="https://cosmos-x2zom66whjavy.documents.azure.com:443/"
export BLOB_CONTAINER_NAME="flipbook-assets"
printf '%s=%q\n' \
  MIGRATION_PRINCIPAL_OBJECT_ID "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  TARGET_STORAGE_RESOURCE_ID "$TARGET_STORAGE_RESOURCE_ID" \
  TARGET_COSMOS_RESOURCE_ID "$TARGET_COSMOS_RESOURCE_ID" \
  SOURCE_STORAGE_RESOURCE_ID "$SOURCE_STORAGE_RESOURCE_ID" \
  SOURCE_COSMOS_RESOURCE_ID "$SOURCE_COSMOS_RESOURCE_ID" \
  SOURCE_STORAGE_ACCOUNT "$SOURCE_STORAGE_ACCOUNT" \
  SOURCE_COSMOS_ENDPOINT "$SOURCE_COSMOS_ENDPOINT" \
  BLOB_CONTAINER_NAME "$BLOB_CONTAINER_NAME" \
  >> .azure/migration/context.env
```

Wait for role propagation with bounded authorization-only retries:

```bash
source .azure/migration/context.env
for attempt in $(seq 1 10); do
  if az storage blob list \
    --account-name "$SOURCE_STORAGE_ACCOUNT" \
    --container-name flipbook-assets \
    --auth-mode login \
    --num-results 1 \
    --only-show-errors >/dev/null 2>.azure/migration/blob-auth.err &&
     az storage blob list \
    --account-name "$TARGET_STORAGE_ACCOUNT" \
    --container-name flipbook-assets \
    --auth-mode login \
    --num-results 1 \
    --only-show-errors >/dev/null 2>>.azure/migration/blob-auth.err
  then
    break
  fi
  grep -Eq 'AuthorizationPermissionMismatch|Forbidden|403' \
    .azure/migration/blob-auth.err || {
      cat .azure/migration/blob-auth.err >&2
      exit 1
    }
  (( attempt < 10 )) || exit 1
  sleep 30
done

for attempt in $(seq 1 10); do
  if python3 - \
    "$AZURE_TENANT_ID" \
    "$SOURCE_COSMOS_ENDPOINT" \
    "$TARGET_COSMOS_ENDPOINT" <<'PY'
import sys
from azure.cosmos import CosmosClient
from azure.identity import AzureCliCredential

credential = AzureCliCredential(tenant_id=sys.argv[1])
for endpoint in sys.argv[2:]:
    container = (
        CosmosClient(endpoint, credential=credential)
        .get_database_client("jjflipbook")
        .get_container_client("users")
    )
    next(iter(container.query_items(
        "SELECT TOP 1 c.id FROM c",
        enable_cross_partition_query=True,
    )), None)
PY
  then
    break
  fi
  (( attempt < 10 )) || exit 1
  sleep 30
done
```

- [ ] **Step 6: Run the initial Blob copy**

```bash
source .azure/migration/context.env
AZURE_TENANT_ID="$AZURE_TENANT_ID" \
SOURCE_STORAGE_ACCOUNT="$SOURCE_STORAGE_ACCOUNT" \
TARGET_STORAGE_ACCOUNT="$TARGET_STORAGE_ACCOUNT" \
BLOB_CONTAINER_NAME="$BLOB_CONTAINER_NAME" \
bash scripts/sync_subscription_blobs.sh initial
```

- [ ] **Step 7: Run the initial Cosmos copy**

```bash
source .azure/migration/context.env
python3 scripts/subscription_migration.py cosmos-copy \
  --tenant-id "$AZURE_TENANT_ID" \
  --source-cosmos-endpoint "$SOURCE_COSMOS_ENDPOINT" \
  --target-cosmos-endpoint "$TARGET_COSMOS_ENDPOINT" \
  --source-storage-account "$SOURCE_STORAGE_ACCOUNT" \
  --target-storage-account "$TARGET_STORAGE_ACCOUNT" \
  --database-name jjflipbook \
  --container-name all
```

Expected: all four containers report successful upserts.

---

### Task 8: Freeze the source, run the final mirror, and verify data

**Files:**
- Create locally only: `.azure/migration/source-freeze.json`
- Create locally only: `.azure/migration/data-verification.json`

**Interfaces:**
- Consumes: Task 3 cutover tool and Task 1 data verifier
- Produces: frozen source and completed data attestation
- Rollback: `python3 scripts/subscription_cutover.py restore --state-file .azure/migration/source-freeze.json`

- [ ] **Step 1: Freeze source writes**

```bash
source .azure/migration/context.env
python3 scripts/subscription_cutover.py freeze \
  --subscription "$SOURCE_SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --state-file .azure/migration/source-freeze.json
```

- [ ] **Step 2: Verify the source is frozen**

```bash
source .azure/migration/context.env
python3 scripts/subscription_cutover.py verify-frozen \
  --state-file .azure/migration/source-freeze.json
```

Expected: both apps have ingress disabled and zero active revisions.

- [ ] **Step 3: Run the final exact Blob mirror**

```bash
source .azure/migration/context.env
AZURE_TENANT_ID="$AZURE_TENANT_ID" \
SOURCE_STORAGE_ACCOUNT="$SOURCE_STORAGE_ACCOUNT" \
TARGET_STORAGE_ACCOUNT="$TARGET_STORAGE_ACCOUNT" \
BLOB_CONTAINER_NAME="$BLOB_CONTAINER_NAME" \
bash scripts/sync_subscription_blobs.sh final
```

- [ ] **Step 4: Run the final Cosmos mirror**

```bash
source .azure/migration/context.env
python3 scripts/subscription_migration.py cosmos-copy \
  --tenant-id "$AZURE_TENANT_ID" \
  --source-cosmos-endpoint "$SOURCE_COSMOS_ENDPOINT" \
  --target-cosmos-endpoint "$TARGET_COSMOS_ENDPOINT" \
  --source-storage-account "$SOURCE_STORAGE_ACCOUNT" \
  --target-storage-account "$TARGET_STORAGE_ACCOUNT" \
  --database-name jjflipbook \
  --container-name all \
  --delete-target-extras
```

- [ ] **Step 5: Generate final data verification proof**

```bash
source .azure/migration/context.env
python3 scripts/subscription_migration.py verify \
  --tenant-id "$AZURE_TENANT_ID" \
  --source-subscription-id "$SOURCE_SUBSCRIPTION_ID" \
  --target-subscription-id "$TARGET_SUBSCRIPTION_ID" \
  --source-resource-group "$RESOURCE_GROUP" \
  --target-resource-group "$RESOURCE_GROUP" \
  --source-cosmos-endpoint "$SOURCE_COSMOS_ENDPOINT" \
  --target-cosmos-endpoint "$TARGET_COSMOS_ENDPOINT" \
  --source-storage-account "$SOURCE_STORAGE_ACCOUNT" \
  --target-storage-account "$TARGET_STORAGE_ACCOUNT" \
  --blob-container-name "$BLOB_CONTAINER_NAME" \
  --database-name jjflipbook \
  --output .azure/migration/data-verification.json

jq -e '
  .completed == true and
  .blob.matched == true and
  .cosmos.matched == true and
  .cosmos.source_url_references_remaining == 0
' .azure/migration/data-verification.json >/dev/null
```

- [ ] **Step 6: Restore source immediately if verification fails**

Run only on failure:

```bash
source .azure/migration/context.env
python3 scripts/subscription_cutover.py restore \
  --state-file .azure/migration/source-freeze.json
```

Do not change GitHub variables until the attestation passes.

---

### Task 9: Switch GitHub Actions and validate the target

**Files:**
- Create locally only: `.azure/migration/smoke-attestation.json`
- Refresh locally only: `.azure/migration/data-verification.json`

**Interfaces:**
- Consumes: frozen source and verified data
- Produces: successful target Preview/full workflow, live target URL, smoke proof, post-smoke data proof

- [ ] **Step 1: Change only the Azure target variables**

```bash
source .azure/migration/context.env
gh variable set AZURE_SUBSCRIPTION_ID \
  --repo freeman9844/jjflipbook-azure \
  --body "$TARGET_SUBSCRIPTION_ID"
gh variable set AZURE_TENANT_ID \
  --repo freeman9844/jjflipbook-azure \
  --body "$AZURE_TENANT_ID"
gh variable set AZURE_ENV_NAME \
  --repo freeman9844/jjflipbook-azure \
  --body "$AZURE_ENV_NAME"
gh variable set AZURE_LOCATION \
  --repo freeman9844/jjflipbook-azure \
  --body "$AZURE_LOCATION"
```

Keep `AZURE_CLIENT_ID` unchanged.

- [ ] **Step 2: Run and approve Preview**

```bash
source .azure/migration/context.env
BEFORE_PREVIEW_RUN_ID="$(
  gh run list \
    --repo freeman9844/jjflipbook-azure \
    --workflow azure-dev.yml \
    --event workflow_dispatch \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // 0'
)"
gh workflow run azure-dev.yml \
  --repo freeman9844/jjflipbook-azure \
  -f validate_only=true

for attempt in $(seq 1 30); do
  PREVIEW_RUN_ID="$(
    gh run list \
      --repo freeman9844/jjflipbook-azure \
      --workflow azure-dev.yml \
      --event workflow_dispatch \
      --limit 1 \
      --json databaseId \
      --jq '.[0].databaseId // 0'
  )"
  [[ "$PREVIEW_RUN_ID" != "$BEFORE_PREVIEW_RUN_ID" ]] && break
  (( attempt < 30 )) || exit 1
  sleep 2
done
gh run watch "$PREVIEW_RUN_ID" \
  --repo freeman9844/jjflipbook-azure \
  --exit-status
printf '%s=%q\n' PREVIEW_RUN_ID "$PREVIEW_RUN_ID" \
  >> .azure/migration/context.env
```

Inspect the Preview log and confirm it targets the target subscription and
contains no unexpected replacement or deletion.

```bash
source .azure/migration/context.env
gh run view "$PREVIEW_RUN_ID" \
  --repo freeman9844/jjflipbook-azure \
  --log > .azure/migration/target-preview-action.log
grep -F "$TARGET_SUBSCRIPTION_ID" \
  .azure/migration/target-preview-action.log >/dev/null
```

- [ ] **Step 3: Run one full target workflow**

```bash
source .azure/migration/context.env
BEFORE_TARGET_RUN_ID="$(
  gh run list \
    --repo freeman9844/jjflipbook-azure \
    --workflow azure-dev.yml \
    --event workflow_dispatch \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // 0'
)"
gh workflow run azure-dev.yml \
  --repo freeman9844/jjflipbook-azure \
  -f validate_only=false

for attempt in $(seq 1 30); do
  TARGET_WORKFLOW_RUN_ID="$(
    gh run list \
      --repo freeman9844/jjflipbook-azure \
      --workflow azure-dev.yml \
      --event workflow_dispatch \
      --limit 1 \
      --json databaseId \
      --jq '.[0].databaseId // 0'
  )"
  [[ "$TARGET_WORKFLOW_RUN_ID" != "$BEFORE_TARGET_RUN_ID" ]] && break
  (( attempt < 30 )) || exit 1
  sleep 2
done
gh run watch "$TARGET_WORKFLOW_RUN_ID" \
  --repo freeman9844/jjflipbook-azure \
  --exit-status
printf '%s=%q\n' TARGET_WORKFLOW_RUN_ID "$TARGET_WORKFLOW_RUN_ID" \
  >> .azure/migration/context.env
```

The concurrency guard must queue any automatic run rather than overlap it.

- [ ] **Step 4: Resolve the live target URL and exact deployed SHA**

```bash
source .azure/migration/context.env
export TARGET_FRONTEND_URL="$(
  az containerapp list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?tags.\"azd-service-name\"=='frontend'].properties.configuration.ingress.fqdn | [0]" \
    -o tsv |
    sed 's#^#https://#'
)"
export EXPECTED_GITHUB_SHA="$(
  gh run view "$TARGET_WORKFLOW_RUN_ID" \
    --repo freeman9844/jjflipbook-azure \
    --json headSha \
    --jq .headSha
)"
printf '%s=%q\n' \
  TARGET_FRONTEND_URL "$TARGET_FRONTEND_URL" \
  EXPECTED_GITHUB_SHA "$EXPECTED_GITHUB_SHA" \
  >> .azure/migration/context.env
```

- [ ] **Step 5: Run an operator-visible smoke test**

```bash
source .azure/migration/context.env
ADMIN_PASSWORD="$(azd env get-value ADMIN_PASSWORD)"
FRONTEND_URL="$TARGET_FRONTEND_URL" \
ADMIN_PASSWORD="$ADMIN_PASSWORD" \
SMOKE_ATTESTATION_FILE=".azure/migration/smoke-attestation.json" \
bash scripts/smoke_test_deployment.sh
unset ADMIN_PASSWORD
```

- [ ] **Step 6: Re-run data verification after smoke cleanup**

```bash
source .azure/migration/context.env
python3 scripts/subscription_migration.py verify \
  --tenant-id "$AZURE_TENANT_ID" \
  --source-subscription-id "$SOURCE_SUBSCRIPTION_ID" \
  --target-subscription-id "$TARGET_SUBSCRIPTION_ID" \
  --source-resource-group "$RESOURCE_GROUP" \
  --target-resource-group "$RESOURCE_GROUP" \
  --source-cosmos-endpoint "$SOURCE_COSMOS_ENDPOINT" \
  --target-cosmos-endpoint "$TARGET_COSMOS_ENDPOINT" \
  --source-storage-account "$SOURCE_STORAGE_ACCOUNT" \
  --target-storage-account "$TARGET_STORAGE_ACCOUNT" \
  --blob-container-name "$BLOB_CONTAINER_NAME" \
  --database-name jjflipbook \
  --output .azure/migration/data-verification.json

jq -e '
  .completed == true and
  .blob.matched == true and
  .cosmos.matched == true and
  .cosmos.source_url_references_remaining == 0
' .azure/migration/data-verification.json >/dev/null
```

- [ ] **Step 7: Verify revisions, KEDA, RBAC, and logs**

```bash
source .azure/migration/context.env
AZURE_ENV_NAME="$AZURE_ENV_NAME" \
BACKEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-backend:$EXPECTED_GITHUB_SHA" \
FRONTEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-frontend:$EXPECTED_GITHUB_SHA" \
bash scripts/wait_for_revision_convergence.sh

az containerapp list \
  --subscription "$TARGET_SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP" \
  --output json |
  jq -e '
    length == 2 and
    all(.[];
      ([.properties.template.scale.rules[].name] | index("daily-warm-window")) != null and
      any(.properties.template.scale.rules[]; has("http"))
    )
  ' >/dev/null

export TARGET_BACKEND_ID_NAME="$(
  az identity list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?starts_with(name, 'id-backend-')].name | [0]" \
    -o tsv
)"
export TARGET_BACKEND_PRINCIPAL_ID="$(
  az identity show \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --name "$TARGET_BACKEND_ID_NAME" \
    --query principalId -o tsv
)"

test "$(
  az role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --assignee-object-id "$TARGET_BACKEND_PRINCIPAL_ID" \
    --scope "$TARGET_STORAGE_RESOURCE_ID" \
    --query "[?roleDefinitionName=='Storage Blob Data Contributor'] | length(@)" \
    -o tsv
)" = "1"

test "$(
  az role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --assignee-object-id "$TARGET_BACKEND_PRINCIPAL_ID" \
    --all \
    --query '[].roleDefinitionName | sort(@) | join(`,`, @)' \
    -o tsv
)" = "Storage Blob Data Contributor"

test "$(
  az cosmosdb sql role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$TARGET_COSMOS_ACCOUNT" \
    --query "[?principalId=='${TARGET_BACKEND_PRINCIPAL_ID}' && ends_with(roleDefinitionId, '00000000-0000-0000-0000-000000000002')] | length(@)" \
    -o tsv
)" = "1"

export TARGET_LOG_WORKSPACE="$(
  jq -er '.[] | select(.type == "Microsoft.OperationalInsights/workspaces") | .name' \
    .azure/migration/target-resources.json
)"
export TARGET_LOG_WORKSPACE_ID="$(
  az monitor log-analytics workspace show \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$TARGET_LOG_WORKSPACE" \
    --query customerId -o tsv
)"
export FINAL_REVISION_START="$(
  while IFS= read -r app_name; do
    az containerapp revision list \
      --subscription "$TARGET_SUBSCRIPTION_ID" \
      --resource-group "$RESOURCE_GROUP" \
      --name "$app_name" \
      --query "[?properties.active].properties.createdTime | [0]" \
      -o tsv
  done < <(
    az containerapp list \
      --subscription "$TARGET_SUBSCRIPTION_ID" \
      --resource-group "$RESOURCE_GROUP" \
      --query '[].name' -o tsv
  ) | sort | head -n 1
)"
export ERROR_COUNT="$(
  az monitor log-analytics query \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --workspace "$TARGET_LOG_WORKSPACE_ID" \
    --analytics-query "
      union isfuzzy=true ContainerAppConsoleLogs_CL, ContainerAppSystemLogs_CL
      | where TimeGenerated >= datetime(${FINAL_REVISION_START})
      | where Log_s matches regex @'(?i)(error|exception|traceback)'
      | count
    " \
    --query 'tables[0].rows[0][0]' -o tsv
)"
test "$ERROR_COUNT" = "0"
```

- [ ] **Step 8: Roll back before deletion if any gate fails**

```bash
source .azure/migration/context.env
gh variable set AZURE_SUBSCRIPTION_ID \
  --repo freeman9844/jjflipbook-azure \
  --body "$SOURCE_SUBSCRIPTION_ID"
python3 scripts/subscription_cutover.py disable-ingress \
  --subscription "$TARGET_SUBSCRIPTION_ID" \
  --resource-group "$RESOURCE_GROUP"
python3 scripts/subscription_cutover.py restore \
  --state-file .azure/migration/source-freeze.json
```

Do not run the deletion task.

---

### Task 10: Delete the source and finalize operational documentation

**Files:**
- Modify: `.azure/deployment-plan.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Task 9 proof and live target checks
- Produces: deleted source RG, revoked source OIDC roles, target-only deployment documentation

- [ ] **Step 1: Run the proof-gated deletion**

```bash
source .azure/migration/context.env
export CONFIRM_DELETE_SOURCE_RG="delete:${SOURCE_SUBSCRIPTION_ID}:${RESOURCE_GROUP}"

SOURCE_SUBSCRIPTION_ID="$SOURCE_SUBSCRIPTION_ID" \
TARGET_SUBSCRIPTION_ID="$TARGET_SUBSCRIPTION_ID" \
SOURCE_RESOURCE_GROUP="$RESOURCE_GROUP" \
TARGET_RESOURCE_GROUP="$RESOURCE_GROUP" \
TARGET_FRONTEND_URL="$TARGET_FRONTEND_URL" \
EXPECTED_GITHUB_SHA="$EXPECTED_GITHUB_SHA" \
TARGET_WORKFLOW_RUN_ID="$TARGET_WORKFLOW_RUN_ID" \
MIGRATION_ATTESTATION_FILE=".azure/migration/data-verification.json" \
SMOKE_ATTESTATION_FILE=".azure/migration/smoke-attestation.json" \
SOURCE_FREEZE_STATE_FILE=".azure/migration/source-freeze.json" \
AZURE_CLIENT_ID="$AZURE_CLIENT_ID" \
MIGRATION_PRINCIPAL_OBJECT_ID="$MIGRATION_PRINCIPAL_OBJECT_ID" \
TARGET_STORAGE_RESOURCE_ID="$TARGET_STORAGE_RESOURCE_ID" \
TARGET_COSMOS_RESOURCE_ID="$TARGET_COSMOS_RESOURCE_ID" \
CONFIRM_DELETE_SOURCE_RG="$CONFIRM_DELETE_SOURCE_RG" \
bash scripts/delete_source_environment.sh
```

- [ ] **Step 2: Verify source absence and target health**

```bash
source .azure/migration/context.env
test "$(
  az group exists \
    --subscription "$SOURCE_SUBSCRIPTION_ID" \
    --name "$RESOURCE_GROUP"
)" = "false"

curl --fail --silent --show-error "$TARGET_FRONTEND_URL" >/dev/null
curl --fail --silent --show-error \
  "$TARGET_FRONTEND_URL/api/backend/healthz" >/dev/null
```

- [ ] **Step 3: Confirm GitHub and OIDC now target only the new subscription**

```bash
source .azure/migration/context.env
gh variable get AZURE_SUBSCRIPTION_ID \
  --repo freeman9844/jjflipbook-azure

az role assignment list \
  --assignee-object-id "$OIDC_SP_OBJECT_ID" \
  --scope "/subscriptions/$SOURCE_SUBSCRIPTION_ID" \
  --query '[].roleDefinitionName' -o tsv
```

Expected: GitHub returns the target subscription and the source role query
returns no direct assignments.

- [ ] **Step 4: Record final proof without committing data**

Update `.azure/deployment-plan.md`:

- Set `Status: Deployed`.
- Record target subscription, target resource names, target Frontend URL.
- Record Preview and full workflow run IDs.
- Record final commit SHA and revision names.
- Record Blob count/bytes/digest and Cosmos per-container counts/digests.
- Record source RG deletion completion and source OIDC role removal.
- Do not copy document contents, password hashes, SAS tokens, or secrets.

Update README with the target subscription and new Frontend URL. Keep all prior
README enhancements.

- [ ] **Step 5: Commit final documentation**

```bash
source .azure/migration/context.env
BEFORE_FINAL_RUN_ID="$(
  gh run list \
    --repo freeman9844/jjflipbook-azure \
    --workflow azure-dev.yml \
    --branch main \
    --event push \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId // 0'
)"
printf '%s=%q\n' BEFORE_FINAL_RUN_ID "$BEFORE_FINAL_RUN_ID" \
  >> .azure/migration/context.env
git add .azure/deployment-plan.md README.md
git commit -m "docs: record completed subscription migration"
git push origin main
```

- [ ] **Step 6: Wait for the documentation push deployment**

Because GitHub now targets the new subscription, the push must deploy only to
the target.

```bash
source .azure/migration/context.env
for attempt in $(seq 1 30); do
  FINAL_WORKFLOW_RUN_ID="$(
    gh run list \
      --repo freeman9844/jjflipbook-azure \
      --workflow azure-dev.yml \
      --branch main \
      --event push \
      --limit 1 \
      --json databaseId \
      --jq '.[0].databaseId // 0'
  )"
  [[ "$FINAL_WORKFLOW_RUN_ID" != "$BEFORE_FINAL_RUN_ID" ]] && break
  (( attempt < 30 )) || exit 1
  sleep 2
done
gh run watch "$FINAL_WORKFLOW_RUN_ID" \
  --repo freeman9844/jjflipbook-azure \
  --exit-status
```

- [ ] **Step 7: Run final target checks**

```bash
source .azure/migration/context.env
AZURE_ENV_NAME="$AZURE_ENV_NAME" \
BACKEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-backend:$(git rev-parse HEAD)" \
FRONTEND_IMAGE="ghcr.io/freeman9844/jjflipbook-azure-frontend:$(git rev-parse HEAD)" \
bash scripts/wait_for_revision_convergence.sh

curl --fail --silent --show-error "$TARGET_FRONTEND_URL" >/dev/null
curl --fail --silent --show-error \
  "$TARGET_FRONTEND_URL/api/backend/healthz" >/dev/null
```

Expected: exact final SHA revisions are Healthy and both endpoints return
HTTP 200.
