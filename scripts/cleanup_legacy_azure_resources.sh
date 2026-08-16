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
