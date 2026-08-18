#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"
load_project_env

require_command curl
require_command openssl
require_command docker

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

printf 'Checking website... '
status=$(curl -fsS --max-time 15 -o "$tmp_dir/site.html" -w '%{http_code}' "https://${DOMAIN}/")
[[ $status == 200 ]] || die "website returned HTTP $status"
grep -Fq 'Northline Notes' "$tmp_dir/site.html" || die "homepage marker not found"
printf 'OK (HTTP 200)\n'

printf 'Checking TLS hostname, trust, and HTTP/2... '
if ! openssl s_client -connect "${DOMAIN}:443" -servername "$DOMAIN" -verify_hostname "$DOMAIN" \
  -verify_return_error -alpn h2 </dev/null >"$tmp_dir/tls.txt" 2>&1; then
  die "TLS handshake or verification failed"
fi
grep -Fq 'Verify return code: 0 (ok)' "$tmp_dir/tls.txt" || die "certificate is not publicly trusted"
grep -Fq 'ALPN protocol: h2' "$tmp_dir/tls.txt" || die "HTTP/2 was not negotiated"
printf 'OK\n'

printf 'Checking unauthenticated CONNECT probe resistance... '
set +e
curl -sS --max-time 15 --proxy "https://${DOMAIN}:443" https://example.com/ \
  -D "$tmp_dir/probe.headers" -o "$tmp_dir/probe.body" 2>"$tmp_dir/probe.error"
set -e
if grep -Eiq '(^|[[:space:]])407([[:space:]]|$)|Proxy-Authenticate|forward proxy' \
  "$tmp_dir/probe.headers" "$tmp_dir/probe.body" "$tmp_dir/probe.error"; then
  die "unauthenticated probe exposed an obvious forward-proxy response"
fi
printf 'OK\n'

printf 'Checking authenticated HTTPS proxy path... '
proxy_h2=()
if curl --help all 2>/dev/null | grep -q -- '--proxy-http2'; then
  proxy_h2=(--proxy-http2)
fi
proxy_ok=0
for target in https://example.com/ https://www.cloudflare.com/cdn-cgi/trace; do
  if curl -fsS --max-time 25 "${proxy_h2[@]}" --proxy "https://${DOMAIN}:443" \
    --proxy-user "${NAIVE_USER}:${NAIVE_PASSWORD}" "$target" -o /dev/null; then
    proxy_ok=1
    break
  fi
done
[[ $proxy_ok -eq 1 ]] || die "authenticated proxy request failed"
printf 'OK\n'

printf 'Checking container state and health... '
container_id=$(compose ps -q caddy)
[[ -n $container_id ]] || die "caddy container is not running"
health=starting
for _ in {1..12}; do
  health=$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)
  [[ $health == healthy ]] && break
  sleep 5
done
[[ $health == healthy ]] || die "caddy health is $health"
printf 'OK\n\nServer checks passed.\n'
