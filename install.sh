#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT_DIR"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "run as root: sudo DOMAIN=example.com ACME_EMAIL=you@example.com ./install.sh"
[[ -r /etc/os-release ]] || die "cannot identify the operating system"

# shellcheck source=/etc/os-release
# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:22.04|ubuntu:24.04|ubuntu:26.04|debian:12|debian:13) ;;
  *) die "supported systems: Ubuntu 22.04+ and Debian 12+ (found ${ID:-unknown} ${VERSION_ID:-unknown})" ;;
esac

INPUT_DOMAIN=${DOMAIN:-}
INPUT_EMAIL=${ACME_EMAIL:-}
INPUT_USER=${NAIVE_USER:-}
INPUT_PASSWORD=${NAIVE_PASSWORD:-}

env_value() {
  local key=$1 file=$2
  [[ -f "$file" ]] || return 0
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$file"
}

DOMAIN=${INPUT_DOMAIN:-$(env_value DOMAIN .env)}
ACME_EMAIL=${INPUT_EMAIL:-$(env_value ACME_EMAIL .env)}
NAIVE_USER=${INPUT_USER:-$(env_value NAIVE_USER .env)}
NAIVE_PASSWORD=${INPUT_PASSWORD:-$(env_value NAIVE_PASSWORD .env)}

[[ -n $DOMAIN ]] || die "DOMAIN is required"
[[ -n $ACME_EMAIL ]] || die "ACME_EMAIL is required"
DOMAIN=${DOMAIN,,}
[[ $DOMAIN =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && $DOMAIN == *.* ]] || die "invalid DOMAIN: $DOMAIN"
[[ $ACME_EMAIL =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || die "invalid ACME_EMAIL"

install_packages() {
  log "Installing diagnostic prerequisites"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl dnsutils file gnupg openssl xz-utils
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker Engine and Compose plugin already present"
    return
  fi

  log "Installing Docker Engine from Docker's signed apt repository"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  local codename=${VERSION_CODENAME:-}
  [[ -n $codename ]] || die "VERSION_CODENAME is missing from /etc/os-release"
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" "$ID" "$codename" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

public_ipv4() {
  local value
  value=$(dig +short myip.opendns.com @resolver1.opendns.com 2>/dev/null | tail -n1 || true)
  if [[ ! $value =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    for endpoint in https://api.ipify.org https://ifconfig.co/ip https://icanhazip.com; do
      value=$(curl -4fsS --max-time 8 "$endpoint" 2>/dev/null | tr -d '[:space:]' || true)
      [[ $value =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] && break
    done
  fi
  [[ $value =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  printf '%s\n' "$value"
}

check_dns() {
  log "Checking public DNS"
  local public_ip a_records aaaa_records public_v6
  public_ip=$(public_ipv4) || die "could not determine public IPv4"
  a_records=$(dig +short A "$DOMAIN" | grep -E '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || true)
  [[ -n $a_records ]] || die "$DOMAIN has no A record"
  grep -Fxq "$public_ip" <<<"$a_records" || die "$DOMAIN resolves to [$a_records], but this server's public IPv4 is $public_ip"
  printf 'IPv4 OK: %s -> %s\n' "$DOMAIN" "$public_ip"

  aaaa_records=$(dig +short AAAA "$DOMAIN" | grep ':' || true)
  if [[ -n $aaaa_records ]]; then
    public_v6=$(curl -6fsS --max-time 8 https://api64.ipify.org 2>/dev/null | tr -d '[:space:]' || true)
    if [[ -z $public_v6 ]] || ! grep -Fxiq "$public_v6" <<<"$aaaa_records"; then
      printf 'WARNING: AAAA records exist but do not match a reachable local public IPv6: %s\n' "$aaaa_records" >&2
      printf 'Remove or correct AAAA before relying on IPv6 clients.\n' >&2
    else
      printf 'IPv6 OK: %s -> %s\n' "$DOMAIN" "$public_v6"
    fi
  fi
}

write_env() {
  log "Preparing credentials"
  NAIVE_USER=${NAIVE_USER:-$(openssl rand -hex 8)}
  NAIVE_PASSWORD=${NAIVE_PASSWORD:-$(openssl rand -hex 32)}
  [[ $NAIVE_USER =~ ^[A-Za-z0-9._~-]+$ ]] || die "NAIVE_USER must be URL-safe"
  [[ $NAIVE_PASSWORD =~ ^[A-Za-z0-9._~-]+$ ]] || die "NAIVE_PASSWORD must be URL-safe"

  local tmp
  tmp=$(mktemp "$ROOT_DIR/.env.tmp.XXXXXX")
  trap 'rm -f "${tmp:-}"' RETURN
  printf 'DOMAIN=%s\nACME_EMAIL=%s\nNAIVE_USER=%s\nNAIVE_PASSWORD=%s\n' \
    "$DOMAIN" "$ACME_EMAIL" "$NAIVE_USER" "$NAIVE_PASSWORD" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$ROOT_DIR/.env"
  trap - RETURN
}

firewall_notice() {
  log "Firewall notice"
  printf '%s\n' 'Required inbound ports: 22/tcp, 80/tcp, 443/tcp; 443/udp is optional for the ordinary HTTP/3 website.'
  if command -v ufw >/dev/null 2>&1; then
    printf 'UFW detected (%s). It was not modified.\n' "$(ufw status 2>/dev/null | head -n1 || true)"
  fi
  if command -v nft >/dev/null 2>&1; then
    printf 'nftables detected. Existing rules were not modified.\n'
  fi
  printf '%s\n' 'Open these ports in the provider firewall and the host firewall before continuing.'
}

install_packages
install_docker
check_dns
write_env
firewall_notice

set -a
# shellcheck source=versions.env
# shellcheck disable=SC1091
source "$ROOT_DIR/versions.env"
set +a

compose=(docker compose --env-file "$ROOT_DIR/versions.env" --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/compose.yml")

log "Building pinned custom Caddy"
"${compose[@]}" build

log "Validating Compose and Caddy configuration"
"${compose[@]}" config --quiet
"${compose[@]}" run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

log "Starting the gateway"
"${compose[@]}" up -d

log "Waiting for automatic public certificate issuance"
ready=0
for _ in {1..36}; do
  if curl -fsS --max-time 8 "https://${DOMAIN}/" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 5
done
[[ $ready -eq 1 ]] || {
  "${compose[@]}" logs --tail=100 caddy >&2 || true
  die "HTTPS did not become ready within 3 minutes"
}

"$ROOT_DIR/scripts/check-server.sh"

log "Installation complete"
printf 'Server: OK\nWebsite: https://%s\nNaive endpoint: https://%s:443\nUser: %s\nPassword: %s\n' \
  "$DOMAIN" "$DOMAIN" "$NAIVE_USER" "$NAIVE_PASSWORD"
