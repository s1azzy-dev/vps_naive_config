#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

grep -Fxq 'ansible-core==2.21.2' provisioning/requirements-controller.in || fail "direct ansible-core pin missing"
grep -Fxq 'ansible-lint==26.6.0' provisioning/requirements-controller.in || fail "direct ansible-lint pin missing"
grep -Fxq 'ansible-core==2.21.2' provisioning/requirements-controller.txt || fail "locked ansible-core pin missing"
grep -Fxq 'ansible-lint==26.6.0' provisioning/requirements-controller.txt || fail "locked ansible-lint pin missing"
if grep -Ev '^(#.*|[[:space:]]*|[A-Za-z0-9_.-]+==[^=[:space:]]+)$' provisioning/requirements-controller.txt >/dev/null; then
  fail "controller lock contains an unpinned requirement"
fi
grep -Fxq 'collections: []' provisioning/requirements.yml || fail "unexpected unused Ansible collection"

bash scripts/check-ansible-secrets.sh provisioning >/dev/null

fixture_dir=$(mktemp -d)
trap 'rm -rf "$fixture_dir"' EXIT
printf '%s\n' 'ansible_become_password: plaintext-test-value' > "$fixture_dir/leak.yml"
if bash scripts/check-ansible-secrets.sh "$fixture_dir" >/dev/null 2>&1; then
  fail "Ansible secret scan accepted a plaintext password"
fi
