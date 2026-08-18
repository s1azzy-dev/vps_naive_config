#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${SMOKE_IMAGE:-naive-gateway-caddy:2.11.4}
PORT=${SMOKE_PORT:-18443}
CONTAINER="naive-gateway-smoke-$$"
USER_VALUE=0011223344556677
PASSWORD_VALUE=00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff
SMOKE_CADDYFILE=$(mktemp)
TMP_DIR=$(mktemp -d)

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -f "$SMOKE_CADDYFILE"
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# Exercise the production file verbatim except for using Caddy's local issuer;
# a public ACME certificate cannot be issued for localhost in CI.
sed "s/tls {\$ACME_EMAIL}/tls internal/" "$ROOT_DIR/Caddyfile" > "$SMOKE_CADDYFILE"

docker run -d --name "$CONTAINER" \
  -p "127.0.0.1:${PORT}:443/tcp" \
  -e DOMAIN=smoke.localhost \
  -e ACME_EMAIL=ci@example.com \
  -e NAIVE_USER="$USER_VALUE" \
  -e NAIVE_PASSWORD="$PASSWORD_VALUE" \
  -v "$SMOKE_CADDYFILE:/etc/caddy/Caddyfile:ro" \
  -v "$ROOT_DIR/site:/srv/www:ro" \
  "$IMAGE" >/dev/null

ready=0
for _ in {1..20}; do
  if curl -kfsS --max-time 3 "https://localhost:${PORT}/" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if [[ $(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true) != true ]]; then
    docker logs "$CONTAINER" >&2 || true
    break
  fi
  sleep 1
done
[[ $ready == 1 ]] || { docker logs "$CONTAINER" >&2 || true; printf 'smoke server did not start\n' >&2; exit 1; }

curl -kfsS "https://localhost:${PORT}/" | grep -Fq 'Northline Notes'
curl -kfsS "https://localhost:${PORT}/sitemap.xml" | grep -Fq 'https://smoke.localhost/'
docker exec "$CONTAINER" wget -qO- http://127.0.0.1:2019/config/ >/dev/null

openssl s_client -connect "localhost:${PORT}" -servername smoke.localhost -alpn h2 </dev/null \
  >"$TMP_DIR/tls.txt" 2>&1
grep -Fq 'ALPN protocol: h2' "$TMP_DIR/tls.txt"

set +e
curl -ksS --proxy-insecure --max-time 15 --proxy "https://localhost:${PORT}" \
  https://example.com/ -D "$TMP_DIR/probe.headers" -o "$TMP_DIR/probe.body" \
  2>"$TMP_DIR/probe.error"
set -e
if grep -Eiq '(^|[[:space:]])407([[:space:]]|$)|Proxy-Authenticate|forward proxy' \
  "$TMP_DIR/probe.headers" "$TMP_DIR/probe.body" "$TMP_DIR/probe.error"; then
  printf 'unauthenticated probe exposed the proxy\n' >&2
  exit 1
fi

curl -kfsS --proxy-insecure --max-time 20 --proxy "https://localhost:${PORT}" \
  --proxy-user "${USER_VALUE}:${PASSWORD_VALUE}" https://example.com/ -o /dev/null

if docker logs "$CONTAINER" 2>&1 | grep -Fq 'example.com'; then
  printf 'tunneled destination appeared in Caddy logs\n' >&2
  exit 1
fi

printf 'Local Caddy runtime smoke passed.\n'
