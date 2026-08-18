#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"
load_project_env
require_command openssl
require_command docker

old_env=$(mktemp "$ROOT_DIR/.env.rotate.XXXXXX")
new_env=$(mktemp "$ROOT_DIR/.env.rotate.XXXXXX")
trap 'rm -f "$old_env" "$new_env"' EXIT
cp -p "$ROOT_DIR/.env" "$old_env"

NAIVE_USER=$(random_hex 8)
NAIVE_PASSWORD=$(random_hex 32)
printf 'DOMAIN=%s\nACME_EMAIL=%s\nNAIVE_USER=%s\nNAIVE_PASSWORD=%s\n' \
  "$DOMAIN" "$ACME_EMAIL" "$NAIVE_USER" "$NAIVE_PASSWORD" > "$new_env"
chmod 600 "$new_env"
mv -f "$new_env" "$ROOT_DIR/.env"

rollback() {
  printf 'Credential activation failed; restoring the previous .env.\n' >&2
  cp -p "$old_env" "$ROOT_DIR/.env"
  compose up -d --force-recreate caddy >/dev/null 2>&1 || true
}

if ! compose up -d --force-recreate caddy; then
  rollback
  exit 1
fi
if ! "$SCRIPT_DIR/check-server.sh"; then
  rollback
  exit 1
fi

printf '\nCredentials rotated.\nEndpoint: https://%s:443\nUser: %s\nPassword: %s\n' \
  "$DOMAIN" "$NAIVE_USER" "$NAIVE_PASSWORD"
