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

container_id=$(compose ps -q caddy)
[[ -n $container_id ]] || die "caddy container is not running"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)

printf 'Checking website... '
site=$(curl -fsS --max-time 15 --max-filesize 1048576 -w '\n%{http_code}' "https://${DOMAIN}/")
status=${site##*$'\n'}
[[ $status == 200 ]] || die "website returned HTTP $status"
[[ $site == *'Northline Notes'* ]] || die "homepage marker not found"
printf 'OK (HTTP 200)\n'

printf 'Checking TLS hostname, trust, and HTTP/2... '
if ! tls=$(openssl s_client -connect "${DOMAIN}:443" -servername "$DOMAIN" -verify_hostname "$DOMAIN" \
  -verify_return_error -alpn h2 </dev/null 2>&1); then
  die "TLS handshake or verification failed"
fi
[[ $tls == *'Verify return code: 0 (ok)'* ]] || die "certificate is not publicly trusted"
[[ $tls == *'ALPN protocol: h2'* ]] || die "HTTP/2 was not negotiated"
printf 'OK\n'

printf 'Checking authenticated HTTPS proxy path... '
proxy_h2=()
if curl --help all 2>/dev/null | grep -q -- '--proxy-http2'; then
  proxy_h2=(--proxy-http2)
fi
proxy_ok=0
proxy_host=
proxy_target=
domain_lower=$(printf '%s' "$DOMAIN" | tr '[:upper:]' '[:lower:]')
for target in https://example.com/ https://www.cloudflare.com/cdn-cgi/trace; do
  target_host=${target#https://}
  target_host=${target_host%%/*}
  [[ $domain_lower == "$target_host" ]] && continue
  if authenticated_connect=$(printf 'proxy-user = "%s:%s"\n' "$NAIVE_USER" "$NAIVE_PASSWORD" | \
    curl --config - -fsS --max-time 25 "${proxy_h2[@]}" --proxy "https://${DOMAIN}:443" \
      "$target" -o /dev/null --write-out '%{http_connect}'); then
    [[ $authenticated_connect == 200 ]] || continue
    proxy_ok=1
    proxy_host=$target_host
    proxy_target=$target
    break
  fi
done
[[ $proxy_ok -eq 1 ]] || die "proxy checks inconclusive: no authenticated test target succeeded; check gateway and external target availability"
printf 'OK\n'

printf 'Checking unauthenticated CONNECT rejection and probe resistance... '
probe_rc=0
probe=$(curl -sS --include --max-time 15 --max-filesize 1048576 \
  --proxy "https://${DOMAIN}:443" "$proxy_target" --write-out '\n%{http_connect}' 2>&1) || probe_rc=$?
probe_code=${probe##*$'\n'}
if grep -Eiq '(^|[[:space:]])407([[:space:]]|$)|Proxy-Authenticate|forward proxy' <<<"$probe"; then
  die "unauthenticated probe exposed an obvious forward-proxy response"
fi
[[ $probe_code != 2[0-9][0-9] ]] || die "unauthenticated CONNECT was accepted"
[[ $probe_code == [34][0-9][0-9] && ( $probe_rc == 0 || $probe_rc == 56 ) ]] || \
  die "anonymous proxy check inconclusive: no explicit CONNECT rejection (transport errors are not evidence)"
printf 'OK\n'

printf 'Checking container state and health... '
health=starting
for _ in {1..12}; do
  health=$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)
  [[ $health == healthy ]] && break
  sleep 5
done
[[ $health == healthy ]] || die "caddy health is $health"
printf 'OK\n'

printf 'Checking proxy destination log suppression... '
logs=$(docker logs --since "$started" "$container_id" 2>&1) || die "cannot read Caddy logs"
case "$proxy_host" in
  example.com) destination_pattern='(^|[^a-z0-9.-])example\.com([^a-z0-9.-]|$)' ;;
  www.cloudflare.com) destination_pattern='(^|[^a-z0-9.-])www\.cloudflare\.com([^a-z0-9.-]|$)' ;;
  *) die "unexpected proxy test destination" ;;
esac
if grep -Eiq "$destination_pattern" <<<"$logs"; then
  die "proxy destination appeared in Caddy logs"
fi
printf 'OK\n\nServer checks passed.\n'
