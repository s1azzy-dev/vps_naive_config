#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SCAN_DIR=${1:-$ROOT_DIR/provisioning}

[[ -d $SCAN_DIR ]] || { printf 'Ansible secret scan: ERROR: directory not found: %s\n' "$SCAN_DIR" >&2; exit 1; }

secret_error=0
while IFS= read -r file; do
  if grep -Eq -- '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$file"; then
    printf 'Ansible secret scan: private key marker in %s\n' "$file" >&2
    secret_error=1
  fi

  if grep -Eq 'https?://[^/@[:space:]]+:[^/@[:space:]]+@' "$file"; then
    printf 'Ansible secret scan: credential-bearing URL in %s\n' "$file" >&2
    secret_error=1
  fi

  if ! awk '
    /^[[:space:]]*(ansible_password|ansible_become_password|become_pass|naive_password|NAIVE_PASSWORD)[[:space:]]*:/ {
      key = $0
      sub(/^[[:space:]]*/, "", key)
      sub(/[[:space:]]*:.*$/, "", key)

      value = $0
      sub(/^[^:]*:[[:space:]]*/, "", value)
      sub(/^["'\''[:space:]]*/, "", value)

      if (value != "" && value !~ /^\{\{/ && value !~ /^!vault([[:space:]]|$)/) {
        printf "%s:%d: plaintext value assigned to %s\n", FILENAME, FNR, key > "/dev/stderr"
        bad = 1
      }
    }
    END { exit bad }
  ' "$file"; then
    secret_error=1
  fi
done < <(find "$SCAN_DIR" -type f \( -name '*.yml' -o -name '*.yaml' \) -print)

(( secret_error == 0 )) || { printf 'Ansible secret scan: FAILED\n' >&2; exit 1; }
printf 'Ansible secret scan: OK\n'
