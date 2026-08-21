#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR=${VENV_DIR:-.venv}
PYTHON_BIN=${PYTHON_BIN:-python3}

if [[ $VENV_DIR != /* ]]; then
  VENV_DIR="$ROOT_DIR/$VENV_DIR"
fi

fail() { printf 'Tooling: ERROR: %s\n' "$*" >&2; exit 1; }

for command_name in "$PYTHON_BIN" ssh ssh-keygen make git; do
  command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

python_version=$(
  "$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)
case "$python_version" in
  3.12|3.13|3.14) ;;
  *) fail "Python 3.12-3.14 is required; found $python_version" ;;
esac

printf 'Creating or reusing controller virtualenv: %s\n' "$VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
PIP_CACHE_DIR="$ROOT_DIR/.ansible/pip-cache" "$VENV_DIR/bin/python" -m pip install \
  --disable-pip-version-check \
  --quiet \
  --requirement "$ROOT_DIR/provisioning/requirements-controller.txt"

mkdir -p "$ROOT_DIR/.ansible/collections"
if grep -Eq '^[[:space:]]*-[[:space:]]+name:' "$ROOT_DIR/provisioning/requirements.yml"; then
  ANSIBLE_CONFIG="$ROOT_DIR/provisioning/ansible.cfg" \
    ANSIBLE_HOME="$ROOT_DIR/.ansible" \
    ANSIBLE_LOCAL_TEMP="$ROOT_DIR/.ansible/tmp" \
    "$VENV_DIR/bin/ansible-galaxy" collection install \
      --requirements-file "$ROOT_DIR/provisioning/requirements.yml" \
      --collections-path "$ROOT_DIR/.ansible/collections"
else
  printf 'No Ansible collections are required in the current phase.\n'
fi

ANSIBLE_HOME="$ROOT_DIR/.ansible" \
  ANSIBLE_LOCAL_TEMP="$ROOT_DIR/.ansible/tmp" \
  VENV_DIR="$VENV_DIR" \
  bash "$ROOT_DIR/scripts/check-tooling.sh"
