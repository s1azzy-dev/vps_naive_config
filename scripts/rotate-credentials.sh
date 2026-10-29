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
[[ ! -e $(dirname -- "$RUNTIME_ENV")/deployment-recovery ]] || \
  die "recover the unfinished deployment before rotating credentials"

old_env=$(mktemp "${RUNTIME_ENV}.rotate.XXXXXX")
new_env=$(mktemp "${RUNTIME_ENV}.rotate.XXXXXX")
rotation_active=0

rollback() {
  printf 'Credential activation failed; restoring the previous runtime env.\n' >&2
  cp -p "$old_env" "$new_env" || return 1
  mv -f "$new_env" "$RUNTIME_ENV" || return 1
  if ! compose up -d --force-recreate --wait --wait-timeout 180 caddy >/dev/null 2>&1; then
    printf 'ERROR: previous credentials were restored but Caddy could not be restarted; inspect the service.\n' >&2
    return 1
  fi
}

cleanup() {
  if [[ $rotation_active == 1 ]]; then
    if ! rollback; then
      printf 'Previous credentials were retained in %s for recovery.\n' "$old_env" >&2
      rm -f "$new_env"
      return
    fi
  fi
  rm -f "$old_env" "$new_env"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cp -p "$RUNTIME_ENV" "$old_env"

NAIVE_USER=$(random_hex 8)
NAIVE_PASSWORD=$(random_hex 32)
printf 'DOMAIN=%s\nACME_EMAIL=%s\nNAIVE_USER=%s\nNAIVE_PASSWORD=%s\n' \
  "$DOMAIN" "$ACME_EMAIL" "$NAIVE_USER" "$NAIVE_PASSWORD" > "$new_env"
chmod 600 "$new_env"
rotation_active=1
mv -f "$new_env" "$RUNTIME_ENV"

if ! compose up -d --force-recreate --wait --wait-timeout 180 caddy; then
  exit 1
fi
if ! "$SCRIPT_DIR/check-server.sh"; then
  exit 1
fi
rotation_active=0

printf '\nCredentials rotated.\n'
if [[ -t 1 ]]; then
  printf 'Endpoint: https://%s:443\nUser: %s\nPassword: %s\n' \
    "$DOMAIN" "$NAIVE_USER" "$NAIVE_PASSWORD"
fi
