#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"
load_project_env

mkdir -p "$ROOT_DIR/backups"
archive="$ROOT_DIR/backups/naive-gateway-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -C "$ROOT_DIR" -czf "$archive" .env Caddyfile compose.yml versions.env
chmod 600 "$archive"
printf 'Backup created: %s\n' "$archive"
printf 'WARNING: this archive contains live credentials. Store it as a secret.\n'
