#!/usr/bin/env bash
set -euo pipefail

: "${SOURCE_SUBSCRIPTION_ID:?SOURCE_SUBSCRIPTION_ID is required}"
: "${TARGET_SUBSCRIPTION_ID:?TARGET_SUBSCRIPTION_ID is required}"
: "${SOURCE_RESOURCE_GROUP:?SOURCE_RESOURCE_GROUP is required}"
: "${TARGET_RESOURCE_GROUP:?TARGET_RESOURCE_GROUP is required}"
: "${TARGET_FRONTEND_URL:?TARGET_FRONTEND_URL is required}"
: "${EXPECTED_GITHUB_SHA:?EXPECTED_GITHUB_SHA is required}"
: "${TARGET_WORKFLOW_RUN_ID:?TARGET_WORKFLOW_RUN_ID is required}"
: "${MIGRATION_ATTESTATION_FILE:?MIGRATION_ATTESTATION_FILE is required}"
: "${SMOKE_ATTESTATION_FILE:?SMOKE_ATTESTATION_FILE is required}"
: "${SOURCE_FREEZE_STATE_FILE:?SOURCE_FREEZE_STATE_FILE is required}"
: "${AZURE_CLIENT_ID:?AZURE_CLIENT_ID is required}"
: "${MIGRATION_PRINCIPAL_OBJECT_ID:?MIGRATION_PRINCIPAL_OBJECT_ID is required}"
: "${TARGET_STORAGE_RESOURCE_ID:?TARGET_STORAGE_RESOURCE_ID is required}"
: "${TARGET_COSMOS_ACCOUNT:?TARGET_COSMOS_ACCOUNT is required}"
: "${TARGET_COSMOS_ROLE_ASSIGNMENT_ID:?TARGET_COSMOS_ROLE_ASSIGNMENT_ID is required}"
: "${CONFIRM_DELETE_SOURCE_RG:?CONFIRM_DELETE_SOURCE_RG is required}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APPROVED_SOURCE_SUBSCRIPTION_ID="8dd0dabf-d8c0-4651-a846-5b13e18e05eb"
APPROVED_TARGET_SUBSCRIPTION_ID="43ab425a-c793-4f2e-b71a-0af7a14f26d2"
APPROVED_RESOURCE_GROUP="rg-jjflipbook-p2"
EXPECTED_CONFIRMATION="delete:${APPROVED_SOURCE_SUBSCRIPTION_ID}:${APPROVED_RESOURCE_GROUP}"
EXPECTED_WORKFLOW_NAME="Azure deployment"

refuse() {
  echo "Refusing source deletion: $1" >&2
  exit 1
}

require_regular_file() {
  local label="$1"
  local path="$2"
  if [[ ! -f "$path" || -L "$path" ]]; then
    refuse "${label} must be a regular file."
  fi
}

[[ "$SOURCE_SUBSCRIPTION_ID" == "$APPROVED_SOURCE_SUBSCRIPTION_ID" ]] || refuse "SOURCE_SUBSCRIPTION_ID must match the approved subscription."
[[ "$TARGET_SUBSCRIPTION_ID" == "$APPROVED_TARGET_SUBSCRIPTION_ID" ]] || refuse "TARGET_SUBSCRIPTION_ID must match the approved subscription."
[[ "$SOURCE_RESOURCE_GROUP" == "$APPROVED_RESOURCE_GROUP" ]] || refuse "SOURCE_RESOURCE_GROUP must match the approved resource group."
[[ "$TARGET_RESOURCE_GROUP" == "$APPROVED_RESOURCE_GROUP" ]] || refuse "TARGET_RESOURCE_GROUP must match the approved resource group."
[[ "$CONFIRM_DELETE_SOURCE_RG" == "$EXPECTED_CONFIRMATION" ]] || refuse "CONFIRM_DELETE_SOURCE_RG must equal ${EXPECTED_CONFIRMATION}."

require_regular_file "Migration attestation file" "$MIGRATION_ATTESTATION_FILE"
require_regular_file "Smoke attestation file" "$SMOKE_ATTESTATION_FILE"
require_regular_file "Source freeze state file" "$SOURCE_FREEZE_STATE_FILE"

if ! jq -e \
  --arg source_subscription "$SOURCE_SUBSCRIPTION_ID" \
  --arg source_rg "$SOURCE_RESOURCE_GROUP" \
  '.subscription_id == $source_subscription and
   .resource_group == $source_rg' \
  "$SOURCE_FREEZE_STATE_FILE" >/dev/null; then
  refuse "Source freeze state file must match SOURCE_SUBSCRIPTION_ID and SOURCE_RESOURCE_GROUP."
fi

if ! jq -e \
  --arg source_subscription "$SOURCE_SUBSCRIPTION_ID" \
  --arg target_subscription "$TARGET_SUBSCRIPTION_ID" \
  --arg source_rg "$SOURCE_RESOURCE_GROUP" \
  --arg target_rg "$TARGET_RESOURCE_GROUP" \
  '.schema_version == 1 and
   .completed == true and
   .source_subscription_id == $source_subscription and
   .target_subscription_id == $target_subscription and
   .source_resource_group == $source_rg and
   .target_resource_group == $target_rg and
   .blob.matched == true and
   .cosmos.matched == true' \
  "$MIGRATION_ATTESTATION_FILE" >/dev/null; then
  refuse "Migration attestation must prove a completed matched blob and cosmos migration."
fi

if ! jq -e '.cosmos.source_url_references_remaining == 0' \
  "$MIGRATION_ATTESTATION_FILE" >/dev/null; then
  refuse "Migration attestation must report source_url_references_remaining == 0."
fi

if ! jq -e \
  --arg frontend_url "$TARGET_FRONTEND_URL" \
  'type == "object" and .completed == true and .FRONTEND_URL == $frontend_url' \
  "$SMOKE_ATTESTATION_FILE" >/dev/null; then
  refuse "Smoke attestation is missing completion or FRONTEND_URL proof."
fi

RUN_JSON="$(
  gh run view "$TARGET_WORKFLOW_RUN_ID" \
    --repo freeman9844/jjflipbook-azure \
    --json conclusion,headSha,status,workflowName
)"
if ! jq -e \
  --arg sha "$EXPECTED_GITHUB_SHA" \
  --arg workflow_name "$EXPECTED_WORKFLOW_NAME" \
  '.status == "completed" and
   .conclusion == "success" and
   .headSha == $sha and
   .workflowName == $workflow_name' \
  <<<"$RUN_JSON" >/dev/null; then
  refuse "GitHub Actions run must be the completed successful Azure deployment for the expected SHA."
fi

TARGET_APPS_JSON="$(
  az containerapp list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --output json
)"
if ! jq -e '
  [.[] | select(
    .tags["azd-service-name"] == "backend" or
    .tags["azd-service-name"] == "frontend"
  )] as $apps |
  ($apps | length) == 2 and
  all($apps[];
    .properties.template.scale.minReplicas == 1 and
    .properties.template.scale.maxReplicas == 2 and
    if .tags["azd-service-name"] == "backend" then
      ([.properties.template.scale.rules[].name] | sort) == ["http-single"] and
      .properties.template.scale.rules[0].http.metadata.concurrentRequests == "1"
    else
      ([.properties.template.scale.rules[].name] | sort) == ["http"] and
      .properties.template.scale.rules[0].http.metadata.concurrentRequests == "10"
    end
  )
' <<<"$TARGET_APPS_JSON" >/dev/null; then
  refuse "Target Container Apps must preserve the expected scale rules."
fi

mapfile -t TARGET_APP_LINES < <(
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
(( ${#TARGET_APP_LINES[@]} == 2 )) || refuse "Target Container Apps must include exactly one backend and one frontend."

declare -a TARGET_ACTIVE_REVISIONS=()
for target_app_line in "${TARGET_APP_LINES[@]}"; do
  IFS=$'\t' read -r app_name service <<<"$target_app_line"
  expected_image="ghcr.io/freeman9844/jjflipbook-azure-${service}:${EXPECTED_GITHUB_SHA}"
  target_revisions_json="$(
    az containerapp revision list \
      --subscription "$TARGET_SUBSCRIPTION_ID" \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$app_name" \
      --output json
  )"
  if ! jq -e --arg image "$expected_image" '
    [.[] | select(.properties.active == true)] as $active |
    ($active | length) == 1 and
    $active[0].properties.healthState == "Healthy" and
    $active[0].properties.provisioningState == "Provisioned" and
    [$active[0].properties.template.containers[]?.image] == [$image]
  ' <<<"$target_revisions_json" >/dev/null; then
    refuse "Target active revision proof failed for ${service}."
  fi
  TARGET_ACTIVE_REVISIONS+=("$(
    jq -er '
      [.[] | select(.properties.active == true)][0].name
    ' <<<"$target_revisions_json"
  )")
done

BACKEND_ID_NAME="$(
  az identity list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --query "[?starts_with(name, 'id-backend-')].name | [0]" \
    -o tsv
)"
[[ -n "$BACKEND_ID_NAME" ]] || refuse "Target backend identity could not be resolved."

BACKEND_PRINCIPAL_ID="$(
  az identity show \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --name "$BACKEND_ID_NAME" \
    --query principalId -o tsv
)"
[[ -n "$BACKEND_PRINCIPAL_ID" ]] || refuse "Target backend principalId could not be resolved."

storage_role_count="$(
  az role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --assignee-object-id "$BACKEND_PRINCIPAL_ID" \
    --scope "$TARGET_STORAGE_RESOURCE_ID" \
    --query "[?roleDefinitionName=='Storage Blob Data Contributor'] | length(@)" \
    -o tsv
)"
[[ "$storage_role_count" == "1" ]] || refuse "Target backend must have exactly one Storage Blob Data Contributor assignment."

backend_role_names="$(
  az role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --assignee-object-id "$BACKEND_PRINCIPAL_ID" \
    --all \
    --query '[].roleDefinitionName | sort(@) | join(`,`, @)' \
    -o tsv
)"
[[ "$backend_role_names" == "Storage Blob Data Contributor" ]] || refuse "Target backend must have no extra target Azure RBAC roles."

cosmos_role_count="$(
  az cosmosdb sql role assignment list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --account-name "$TARGET_COSMOS_ACCOUNT" \
    --query "[?principalId=='${BACKEND_PRINCIPAL_ID}' && ends_with(roleDefinitionId, '00000000-0000-0000-0000-000000000002')] | length(@)" \
    -o tsv
)"
[[ "$cosmos_role_count" == "1" ]] || refuse "Target backend must have exactly one Cosmos DB data-plane role assignment."

TARGET_LOG_WORKSPACE="$(
  az monitor log-analytics workspace list \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --query '[0].customerId' -o tsv
)"
[[ -n "$TARGET_LOG_WORKSPACE" ]] || refuse "Target Log Analytics workspace could not be resolved."

FINAL_REVISION_START="$(
  for target_app_line in "${TARGET_APP_LINES[@]}"; do
    IFS=$'\t' read -r app_name _ <<<"$target_app_line"
    az containerapp revision list \
      --subscription "$TARGET_SUBSCRIPTION_ID" \
      --resource-group "$TARGET_RESOURCE_GROUP" \
      --name "$app_name" \
      --query "[?properties.active].properties.createdTime | [0]" \
      -o tsv
  done |
    sort |
    head -n 1
)"
[[ -n "$FINAL_REVISION_START" ]] || refuse "Target final revision start time could not be resolved."

ANALYTICS_QUERY="$(
  cat <<EOF
      union withsource=SourceTable isfuzzy=true ContainerAppConsoleLogs_CL, ContainerAppSystemLogs_CL
      | where TimeGenerated >= datetime(${FINAL_REVISION_START})
      | where Log_s matches regex @'(?i)(error|exception|traceback)'
      | where not(
          SourceTable == "ContainerAppSystemLogs_CL" and
          RevisionName_s in ("${TARGET_ACTIVE_REVISIONS[0]}", "${TARGET_ACTIVE_REVISIONS[1]}") and
          Log_s == strcat("Error provisioning revision ", RevisionName_s)
        )
      | count
EOF
)"
ERROR_COUNT="$(
  az monitor log-analytics query \
    --subscription "$TARGET_SUBSCRIPTION_ID" \
    --workspace "$TARGET_LOG_WORKSPACE" \
    --analytics-query "$ANALYTICS_QUERY" \
    --query '[0].Count' -o tsv
)"
[[ "$ERROR_COUNT" == "0" ]] || refuse "Target post-revision unexplained error logs must be zero."

python3 "$SCRIPT_DIR/subscription_cutover.py" verify-frozen \
  --state-file "$SOURCE_FREEZE_STATE_FILE"

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

OIDC_SP_OBJECT_ID="$(
  az ad sp show --id "$AZURE_CLIENT_ID" --query id -o tsv
)"
[[ -n "$OIDC_SP_OBJECT_ID" ]] || refuse "OIDC service principal object ID could not be resolved."

for role in Contributor "Role Based Access Control Administrator"; do
  az role assignment delete \
    --assignee-object-id "$OIDC_SP_OBJECT_ID" \
    --role "$role" \
    --scope "/subscriptions/$SOURCE_SUBSCRIPTION_ID"
done

az role assignment delete \
  --assignee-object-id "$MIGRATION_PRINCIPAL_OBJECT_ID" \
  --role "Storage Blob Data Contributor" \
  --scope "$TARGET_STORAGE_RESOURCE_ID"

az cosmosdb sql role assignment delete \
  --subscription "$TARGET_SUBSCRIPTION_ID" \
  --resource-group "$TARGET_RESOURCE_GROUP" \
  --account-name "$TARGET_COSMOS_ACCOUNT" \
  --role-assignment-id "$TARGET_COSMOS_ROLE_ASSIGNMENT_ID" \
  --yes

echo "Source environment deleted after proof verification."
