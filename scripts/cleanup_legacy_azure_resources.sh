#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_ENV_NAME:?AZURE_ENV_NAME is required}"
: "${FRONTEND_URL:?FRONTEND_URL is required}"
: "${SMOKE_ATTESTATION_FILE:?SMOKE_ATTESTATION_FILE is required}"
RESOURCE_GROUP="rg-$AZURE_ENV_NAME"

if [[ ! -f "$SMOKE_ATTESTATION_FILE" || -L "$SMOKE_ATTESTATION_FILE" ]]; then
  echo "Refusing cleanup: smoke attestation file must be a regular file." >&2
  exit 1
fi

jq -e --arg frontend_url "$FRONTEND_URL" \
  'type == "object" and .completed == true and .FRONTEND_URL == $frontend_url' \
  "$SMOKE_ATTESTATION_FILE" >/dev/null || {
  echo "Refusing cleanup: smoke attestation is missing completion or FRONTEND_URL proof." >&2
  exit 1
}

mapfile -t CONTAINER_APPS < <(
  az containerapp list --resource-group "$RESOURCE_GROUP" --output json |
    jq -r '.[].name'
)

if (( ${#CONTAINER_APPS[@]} == 0 )); then
  echo "Refusing cleanup: no Container Apps found to verify." >&2
  exit 1
fi

for container_app in "${CONTAINER_APPS[@]}"; do
  ACTIVE_IMAGES="$(
    az containerapp revision list \
      --resource-group "$RESOURCE_GROUP" \
      --name "$container_app" \
      --output json |
      jq -r '.[] | select(.properties.active == true) | .properties.template.containers[]? | .image // empty'
  )"

  if [[ -z "$ACTIVE_IMAGES" ]]; then
    echo "Refusing cleanup: $container_app has no active revision images." >&2
    exit 1
  fi

  if grep -v '^ghcr\.io/freeman9844/' <<<"$ACTIVE_IMAGES" >/dev/null; then
    echo "Refusing cleanup: every active image for $container_app must use public GHCR." >&2
    exit 1
  fi
done

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
