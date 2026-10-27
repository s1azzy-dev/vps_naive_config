#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"
load_project_env

backup_dir=/var/backups/naive-gateway
install -d -m 700 -o root -g root "$backup_dir"
archive=$(mktemp "$backup_dir/naive-gateway-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX.tar.gz")
trap 'rm -f "$archive"' ERR
tar -czf "$archive" -C "$ROOT_DIR" Caddyfile Dockerfile Makefile compose.yml deployment.yml versions.env \
  site scripts .release-complete .runtime-env-path \
  -C "$ROOT_DIR/../../repository" .git/config \
  -C "$(dirname -- "$RUNTIME_ENV")" "$(basename -- "$RUNTIME_ENV")"
chmod 600 "$archive"
trap - ERR
printf 'Backup created: %s\n' "$archive"
printf 'WARNING: this archive contains live credentials. Store it as a secret.\n'
