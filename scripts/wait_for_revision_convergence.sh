#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_ENV_NAME:?AZURE_ENV_NAME is required}"
: "${BACKEND_IMAGE:?BACKEND_IMAGE is required}"
: "${FRONTEND_IMAGE:?FRONTEND_IMAGE is required}"

RESOURCE_GROUP="rg-$AZURE_ENV_NAME"
REVISION_VERIFY_ATTEMPTS="${REVISION_VERIFY_ATTEMPTS:-24}"
REVISION_VERIFY_DELAY_SECONDS="${REVISION_VERIFY_DELAY_SECONDS:-5}"

if [[ ! "$REVISION_VERIFY_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
  echo "REVISION_VERIFY_ATTEMPTS must be a positive integer." >&2
  exit 1
fi

if [[ ! "$REVISION_VERIFY_DELAY_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "REVISION_VERIFY_DELAY_SECONDS must be a non-negative integer." >&2
  exit 1
fi

APPS_JSON="$(az containerapp list --resource-group "$RESOURCE_GROUP" --output json)"

wait_for_service() {
  local service="$1"
  local expected_image="$2"
  local app_name
  local revisions

  mapfile -t app_names < <(
    jq -r --arg service "$service" \
      '.[] | select(.tags["azd-service-name"] == $service) | .name' \
      <<<"$APPS_JSON"
  )

  if (( ${#app_names[@]} != 1 )); then
    echo "Expected one $service Container App, found ${#app_names[@]}." >&2
    exit 1
  fi
  app_name="${app_names[0]}"

  for (( attempt = 1; attempt <= REVISION_VERIFY_ATTEMPTS; attempt++ )); do
    revisions="$(
      az containerapp revision list \
        --resource-group "$RESOURCE_GROUP" \
        --name "$app_name" \
        --output json
    )"

    if jq -e --arg image "$expected_image" '
      [.[] | select(.properties.active == true)] as $active |
      ($active | length) == 1 and
      $active[0].properties.healthState == "Healthy" and
      $active[0].properties.provisioningState == "Provisioned" and
      [$active[0].properties.template.containers[]?.image] == [$image]
    ' <<<"$revisions" >/dev/null; then
      echo "$service revision converged on $expected_image."
      return
    fi

    if (( attempt == REVISION_VERIFY_ATTEMPTS )); then
      echo "$service revision did not converge on $expected_image." >&2
      jq -r '
        .[] |
        select(.properties.active == true) |
        [
          .name,
          (.properties.healthState // "unknown"),
          (.properties.provisioningState // "unknown"),
          ([.properties.template.containers[]?.image] | join(","))
        ] |
        @tsv
      ' <<<"$revisions" >&2
      exit 1
    fi

    echo "Waiting for $service revision convergence ($attempt/$REVISION_VERIFY_ATTEMPTS)..."
    sleep "$REVISION_VERIFY_DELAY_SECONDS"
  done
}

wait_for_service backend "$BACKEND_IMAGE"
wait_for_service frontend "$FRONTEND_IMAGE"
