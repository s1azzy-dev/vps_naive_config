#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

file_mode() {
  local path=$1
  case $(uname -s) in
    Darwin|FreeBSD) stat -f '%Lp' "$path" ;;
    *) stat -c '%a' "$path" ;;
  esac
}

write_config() {
  local path=$1 host=$2 port=$3 domain=$4 email=$5 private_key=$6 public_key=$7
  local naive_user=${8:-} naive_password=${9:-}
  printf '%s\n' \
    "VPS_HOST=$host" \
    "VPS_PORT=$port" \
    'VPS_BOOTSTRAP_USER=root' \
    'VPS_USER=slazzy' \
    "SSH_PRIVATE_KEY=$private_key" \
    "SSH_PUBLIC_KEY=$public_key" \
    "DOMAIN=$domain" \
    "ACME_EMAIL=$email" \
    'GATEWAY_REPOSITORY=https://github.com/s1azzy-dev/vps_naive_config.git' \
    'GATEWAY_REF=main' \
    "NAIVE_USER=$naive_user" \
    "NAIVE_PASSWORD=$naive_password" > "$path"
  chmod 600 "$path"
}

expect_failure() {
  local config=$1 expected=$2 output rc
  set +e
  output=$(make --no-print-directory -s -C "$ROOT_DIR" CONFIG_FILE="$config" check-config 2>&1)
  rc=$?
  set -e
  [[ $rc -ne 0 ]] || fail "check-config unexpectedly passed: $config"
  grep -Fq "$expected" <<<"$output" || fail "missing error '$expected' for $config"
}

command -v ssh-keygen >/dev/null 2>&1 || fail "ssh-keygen is required"
ssh-keygen -q -t ed25519 -N '' -f "$TMP_DIR/id_ed25519"

make --no-print-directory -s -C "$ROOT_DIR" CONFIG_FILE="$TMP_DIR/missing.env" help >/dev/null

init_env="$TMP_DIR/init.env"
make --no-print-directory -s -C "$ROOT_DIR" CONFIG_FILE="$init_env" init >/dev/null
[[ -f $init_env ]] || fail "make init did not create the config"
[[ $(file_mode "$init_env") == 600 ]] || fail "make init did not set mode 0600"
printf '# preserve-me\n' >> "$init_env"
make --no-print-directory -s -C "$ROOT_DIR" CONFIG_FILE="$init_env" init >/dev/null
grep -Fq '# preserve-me' "$init_env" || fail "make init overwrote an existing config"

valid_env="$TMP_DIR/valid.env"
write_config "$valid_env" 203.0.113.10 22 proxy.example.com admin@example.com \
  "$TMP_DIR/id_ed25519" "$TMP_DIR/id_ed25519.pub"
make --no-print-directory -s -C "$ROOT_DIR" CONFIG_FILE="$valid_env" check-config \
  | grep -Fxq 'Configuration: OK'

missing_host="$TMP_DIR/missing-host.env"
write_config "$missing_host" '' 22 proxy.example.com admin@example.com \
  "$TMP_DIR/id_ed25519" "$TMP_DIR/id_ed25519.pub"
expect_failure "$missing_host" 'VPS_HOST is required'

invalid_port="$TMP_DIR/invalid-port.env"
write_config "$invalid_port" 203.0.113.10 70000 proxy.example.com admin@example.com \
  "$TMP_DIR/id_ed25519" "$TMP_DIR/id_ed25519.pub"
expect_failure "$invalid_port" 'VPS_PORT must be an integer between 1 and 65535'

invalid_domain="$TMP_DIR/invalid-domain.env"
write_config "$invalid_domain" 203.0.113.10 22 invalid_domain admin@example.com \
  "$TMP_DIR/id_ed25519" "$TMP_DIR/id_ed25519.pub"
expect_failure "$invalid_domain" 'DOMAIN must be a valid fully-qualified hostname'

invalid_email="$TMP_DIR/invalid-email.env"
write_config "$invalid_email" 203.0.113.10 22 proxy.example.com invalid-email \
  "$TMP_DIR/id_ed25519" "$TMP_DIR/id_ed25519.pub"
expect_failure "$invalid_email" 'ACME_EMAIL must be a valid email address'

missing_key="$TMP_DIR/missing-key.env"
write_config "$missing_key" 203.0.113.10 22 proxy.example.com admin@example.com \
  "$TMP_DIR/missing-private-key" "$TMP_DIR/missing-private-key.pub"
expect_failure "$missing_key" 'SSH_PRIVATE_KEY must be a readable file'

invalid_public_key="$TMP_DIR/invalid-public-key"
printf 'not-a-public-key\n' > "$invalid_public_key"
invalid_public_env="$TMP_DIR/invalid-public.env"
write_config "$invalid_public_env" 203.0.113.10 22 proxy.example.com admin@example.com \
  "$TMP_DIR/id_ed25519" "$invalid_public_key"
expect_failure "$invalid_public_env" 'SSH_PUBLIC_KEY is not a valid OpenSSH public key'

partial_credentials="$TMP_DIR/partial-credentials.env"
write_config "$partial_credentials" 203.0.113.10 22 proxy.example.com admin@example.com \
  "$TMP_DIR/id_ed25519" "$TMP_DIR/id_ed25519.pub" explicit-user ''
expect_failure "$partial_credentials" 'NAIVE_USER and NAIVE_PASSWORD must both be set or both be empty'

insecure_env="$TMP_DIR/insecure.env"
write_config "$insecure_env" 203.0.113.10 22 proxy.example.com admin@example.com \
  "$TMP_DIR/id_ed25519" "$TMP_DIR/id_ed25519.pub"
chmod 644 "$insecure_env"
expect_failure "$insecure_env" 'must have mode 0600'

printf 'Config contract tests passed.\n'
