#!/usr/bin/env bash
# Set the API's secrets on Fly.io from .env.
#
# Values are read as plain text, never `source`d: DATABASE_URL contains '&', which a shell
# would treat as "run in the background". They go to `fly secrets import` on stdin, so they
# never appear on a command line or in shell history.
#
#   scripts/fly-secrets.sh                 # makes a new API_TOKEN and prints it once
#   API_TOKEN=<existing> scripts/fly-secrets.sh
set -euo pipefail
cd "$(dirname "$0")/.."

get() {
  sed -n "s/^$1=//p" .env | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

for key in DATABASE_URL S3_ENDPOINT S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET; do
  if [ -z "$(get "$key")" ]; then
    echo "error: $key is empty or missing in .env" >&2
    exit 1
  fi
done

token="${API_TOKEN:-$(openssl rand -hex 32)}"

{
  for key in DATABASE_URL S3_ENDPOINT S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET; do
    printf '%s=%s\n' "$key" "$(get "$key")"
  done
  printf 'API_TOKEN=%s\n' "$token"
} | fly secrets import

if [ -z "${API_TOKEN:-}" ]; then
  echo
  echo "API_TOKEN (shown once; save it in your password manager, then use it as"
  echo "SOIVI_API_TOKEN on Vercel):"
  echo "  $token"
fi
