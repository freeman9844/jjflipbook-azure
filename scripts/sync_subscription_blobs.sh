#!/usr/bin/env bash
set -euo pipefail

MODE="${1:?Usage: sync_subscription_blobs.sh initial|final}"
: "${AZURE_TENANT_ID:?AZURE_TENANT_ID is required}"
: "${SOURCE_STORAGE_ACCOUNT:?SOURCE_STORAGE_ACCOUNT is required}"
: "${TARGET_STORAGE_ACCOUNT:?TARGET_STORAGE_ACCOUNT is required}"
: "${BLOB_CONTAINER_NAME:?BLOB_CONTAINER_NAME is required}"

if [[ "$SOURCE_STORAGE_ACCOUNT" == "$TARGET_STORAGE_ACCOUNT" ]]; then
  echo "Source and target Storage Accounts must differ." >&2
  exit 1
fi

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
