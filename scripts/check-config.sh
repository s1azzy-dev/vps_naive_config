#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_PATH=${CONFIG_FILE:-.env}
errors=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  errors=1
}

require_value() {
  local name=$1 value=$2
  [[ -n $value ]] || fail "$name is required in $CONFIG_PATH"
}

file_mode() {
  local path=$1
  case $(uname -s) in
    Darwin|FreeBSD) stat -f '%Lp' "$path" ;;
    *) stat -c '%a' "$path" ;;
  esac
}

valid_ipv4() {
  local value=$1 octet
  local -a octets
  IFS=. read -r -a octets <<<"$value"
  [[ ${#octets[@]} -eq 4 ]] || return 1
  for octet in "${octets[@]}"; do
    [[ $octet =~ ^[0-9]{1,3}$ ]] || return 1
    ((10#$octet <= 255)) || return 1
  done
}

valid_hostname() {
  local value=$1 require_dot=$2 label
  local -a labels
  [[ ${#value} -le 253 ]] || return 1
  [[ $value =~ ^[A-Za-z0-9.-]+$ ]] || return 1
  [[ $value != .* && $value != *. && $value != *..* ]] || return 1
  [[ $require_dot == 0 || $value == *.* ]] || return 1
  IFS=. read -r -a labels <<<"$value"
  for label in "${labels[@]}"; do
    [[ ${#label} -ge 1 && ${#label} -le 63 ]] || return 1
    [[ $label =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
  done
}

vps_host=${VPS_HOST:-}
vps_port=${VPS_PORT:-}
ssh_private_key=${SSH_PRIVATE_KEY:-}
ssh_public_key=${SSH_PUBLIC_KEY:-}
domain=${DOMAIN:-}
acme_email=${ACME_EMAIL:-}
gateway_repository=${GATEWAY_REPOSITORY:-}
gateway_ref=${GATEWAY_REF:-}
naive_user=${NAIVE_USER:-}
naive_password=${NAIVE_PASSWORD:-}

[[ -f $CONFIG_PATH ]] || {
  fail "configuration file not found: $CONFIG_PATH (run: make init)"
  exit 1
}

mode=$(file_mode "$CONFIG_PATH")
[[ $mode == 600 ]] || fail "$CONFIG_PATH must have mode 0600 (found $mode)"

require_value VPS_HOST "$vps_host"
require_value SSH_PRIVATE_KEY "$ssh_private_key"
require_value DOMAIN "$domain"
require_value ACME_EMAIL "$acme_email"

if [[ -n $vps_host ]]; then
  if [[ $vps_host =~ ^[0-9.]+$ ]]; then
    valid_ipv4 "$vps_host" || fail "VPS_HOST must be a valid IPv4 address or hostname"
  else
    valid_hostname "$vps_host" 0 || fail "VPS_HOST must be a valid IPv4 address or hostname"
  fi
fi

if [[ ! $vps_port =~ ^[0-9]+$ ]] || ((10#$vps_port < 1 || 10#$vps_port > 65535)); then
  fail "VPS_PORT must be an integer between 1 and 65535"
fi

if [[ -n $domain ]]; then
  valid_hostname "$domain" 1 || fail "DOMAIN must be a valid fully-qualified hostname"
fi

if [[ -n $acme_email && ! $acme_email =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]]; then
  fail "ACME_EMAIL must be a valid email address"
fi

if [[ -n $ssh_private_key ]]; then
  [[ $ssh_private_key == /* ]] || fail "SSH_PRIVATE_KEY must be an absolute path"
  [[ -f $ssh_private_key && -r $ssh_private_key ]] || fail "SSH_PRIVATE_KEY must be a readable file"
fi

if [[ -z $ssh_public_key && -n $ssh_private_key ]]; then
  ssh_public_key=${ssh_private_key}.pub
fi
if [[ -n $ssh_public_key ]]; then
  [[ $ssh_public_key == /* ]] || fail "SSH_PUBLIC_KEY must be an absolute path"
  if [[ -f $ssh_public_key && -r $ssh_public_key ]]; then
    line_count=$(awk 'END {print NR}' "$ssh_public_key")
    [[ $line_count -eq 1 ]] || fail "SSH_PUBLIC_KEY must contain exactly one key"
    if command -v ssh-keygen >/dev/null 2>&1; then
      ssh-keygen -lf "$ssh_public_key" >/dev/null 2>&1 || fail "SSH_PUBLIC_KEY is not a valid OpenSSH public key"
    else
      fail "ssh-keygen is required to validate SSH_PUBLIC_KEY"
    fi
  else
    fail "SSH_PUBLIC_KEY must be a readable file"
  fi
fi

if [[ -z $gateway_repository || $gateway_repository =~ [[:space:]] ]]; then
  fail "GATEWAY_REPOSITORY must be a non-empty URL without whitespace"
else
  case $gateway_repository in
    https://*|ssh://*|git@*:* ) ;;
    *) fail "GATEWAY_REPOSITORY must use https://, ssh://, or Git SSH syntax" ;;
  esac
fi

if [[ -z $gateway_ref || ! $gateway_ref =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ || $gateway_ref == *..* ]]; then
  fail "GATEWAY_REF must be a non-empty safe branch, tag, or commit"
fi

if [[ -n $naive_user || -n $naive_password ]]; then
  [[ -n $naive_user && -n $naive_password ]] || fail "NAIVE_USER and NAIVE_PASSWORD must both be set or both be empty"
  [[ $naive_user =~ ^[A-Za-z0-9._~-]+$ ]] || fail "NAIVE_USER must be URL-safe"
  [[ $naive_password =~ ^[A-Za-z0-9._~-]+$ ]] || fail "NAIVE_PASSWORD must be URL-safe"
fi

[[ $errors -eq 0 ]] || exit 1
printf 'Configuration: OK\n'
