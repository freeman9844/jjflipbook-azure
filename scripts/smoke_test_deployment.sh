#!/usr/bin/env bash
set -euo pipefail

: "${FRONTEND_URL:?FRONTEND_URL is required}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD is required}"
: "${SMOKE_ATTESTATION_FILE:?SMOKE_ATTESTATION_FILE is required}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ATTESTATION_DIR="$(cd -- "$(dirname -- "$SMOKE_ATTESTATION_FILE")" && pwd)"
COOKIE_JAR="$(mktemp "$SCRIPT_DIR/.smoke_test_deployment.cookie.XXXXXX")"
LOGIN_BODY="$(mktemp "$SCRIPT_DIR/.smoke_test_deployment.login.XXXXXX")"
ATTESTATION_TMP=""
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
  rm -f -- "$COOKIE_JAR" "$LOGIN_BODY"
  if [[ -n "$ATTESTATION_TMP" ]]; then
    rm -f -- "$ATTESTATION_TMP"
  fi
}
trap cleanup EXIT

rm -f -- "$SMOKE_ATTESTATION_FILE"

curl --fail --silent --show-error --location "$FRONTEND_URL" >/dev/null

python3 - "$LOGIN_BODY" <<'PY'
import json
import os
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"username": "admin", "password": os.environ["ADMIN_PASSWORD"]}, handle)
    handle.write("\n")
PY

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

ATTESTATION_TMP="$(mktemp "$ATTESTATION_DIR/.smoke-attestation.XXXXXX")"
python3 - "$ATTESTATION_TMP" <<'PY'
import json
import os
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"FRONTEND_URL": os.environ["FRONTEND_URL"], "completed": True}, handle)
    handle.write("\n")
PY
mv -f -- "$ATTESTATION_TMP" "$SMOKE_ATTESTATION_FILE"
ATTESTATION_TMP=""
