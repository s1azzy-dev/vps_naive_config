#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"
load_project_env
require_command git
require_command docker

if ! git -C "$ROOT_DIR" diff --quiet || ! git -C "$ROOT_DIR" diff --cached --quiet; then
  die "working tree has tracked changes; review them before updating"
fi

printf 'Fetching reviewed repository updates (dependency pins never follow latest automatically)...\n'
git -C "$ROOT_DIR" pull --ff-only

# Shell environment has higher Compose precedence than --env-file. Reload the
# pins after the pull so a reviewed versions.env change takes effect.
set -a
# shellcheck source=../versions.env
# shellcheck disable=SC1091
source "$ROOT_DIR/versions.env"
set +a

compose build
compose config --quiet
compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
compose up -d
"$SCRIPT_DIR/check-server.sh"
