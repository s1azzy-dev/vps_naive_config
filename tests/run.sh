#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { printf 'OK: %s\n' "$*"; }

bash -n install.sh scripts/*.sh tests/*.sh
pass "shell syntax"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck install.sh scripts/*.sh tests/*.sh
  pass "shellcheck"
elif [[ ${REQUIRE_SHELLCHECK:-0} == 1 ]]; then
  fail "shellcheck is required but not installed"
else
  printf 'SKIP: shellcheck is not installed (CI requires it)\n'
fi

bash tests/check-config.sh
pass "local config contract"

bash tests/ansible-quality.sh
pass "Ansible skeleton contract"

[[ $(awk -F= '$1 == "FORWARDPROXY_COMMIT" {print length($2)}' versions.env) == 40 ]] || fail "forwardproxy pin is not a full SHA"
grep -Fq 'CADDY_VERSION=2.11.4' versions.env || fail "reviewed Caddy pin missing"
if grep -Eiq '(^|[^[:alpha:]])latest([^[:alpha:]]|$)' Dockerfile compose.yml versions.env; then
  fail "production dependency follows latest"
fi
pass "reproducible version pins"

[[ -f site/index.html && -f site/about/index.html && -f site/notes/index.html ]] || fail "required site pages missing"
for asset in site/assets/site.css site/assets/site.js site/assets/logo.svg site/assets/hero.svg site/assets/favicon.svg; do
  [[ -s $asset ]] || fail "missing site asset: $asset"
done
grep -Fq '<meta name="description"' site/index.html || fail "homepage meta description missing"
grep -Fq '/assets/site.css' site/index.html || fail "homepage does not reference CSS"
grep -Fq '/assets/site.js' site/index.html || fail "homepage does not reference JS"
grep -Fq '/about/' site/index.html || fail "homepage does not reference about page"
grep -Fq '/notes/keeping-services-boring.html' site/index.html || fail "homepage does not reference article"
if grep -ERiq 'vpn|proxy|censorship|naiveproxy' site --include='*.html'; then
  fail "public HTML contains infrastructure terminology"
fi
if grep -ERiq 'https?://[^<{]' site --include='*.html'; then
  fail "public HTML depends on an external origin"
fi
pass "believable same-origin static site"

[[ -z $(git ls-files .env) ]] || fail ".env is tracked"
grep -Fxq '.env' .gitignore || fail ".env is not ignored"
if grep -ERn --exclude-dir=.git --exclude-dir=.ansible --exclude-dir=.venv --exclude-dir=tests --exclude='*.md' \
  -E -e '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|https://[A-Za-z0-9._~-]{8,}:[A-Za-z0-9._~-]{32,}@' . >/dev/null; then
  fail "possible credential or private key committed"
fi
grep -Fq 'exclude http.log.error' Caddyfile || fail "tunneled error logger is not suppressed"
[[ $(grep -Ec '^[[:space:]]*log[[:space:]]*\{' Caddyfile) == 1 ]] || fail "unexpected access logging configuration"
grep -Fq 'mime text/plain text/xml application/xml' Caddyfile || fail "site metadata template MIME types are incomplete"
pass "secret and logging policy"

fake_env=$(mktemp)
trap 'rm -f "$fake_env"' EXIT
printf '%s\n' \
  'DOMAIN=ci.example' \
  'ACME_EMAIL=ci@example.com' \
  'NAIVE_USER=0011223344556677' \
  'NAIVE_PASSWORD=00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff' > "$fake_env"
docker compose --env-file versions.env --env-file "$fake_env" -f compose.yml config --quiet
pass "docker compose config"

printf '\nStatic test suite passed.\n'
