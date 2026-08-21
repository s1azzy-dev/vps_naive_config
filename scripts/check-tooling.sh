#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR=${VENV_DIR:-.venv}

if [[ $VENV_DIR != /* ]]; then
  VENV_DIR="$ROOT_DIR/$VENV_DIR"
fi

export ANSIBLE_CONFIG=${ANSIBLE_CONFIG:-$ROOT_DIR/provisioning/ansible.cfg}
export ANSIBLE_HOME=${ANSIBLE_HOME:-$ROOT_DIR/.ansible}
export ANSIBLE_LOCAL_TEMP=${ANSIBLE_LOCAL_TEMP:-$ROOT_DIR/.ansible/tmp}
mkdir -p "$ANSIBLE_LOCAL_TEMP"

fail() { printf 'Tooling: ERROR: %s\n' "$*" >&2; exit 1; }

for command_name in ssh ssh-keygen make git; do
  command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

for executable in ansible-playbook ansible-galaxy ansible-lint; do
  [[ -x $VENV_DIR/bin/$executable ]] || fail "run 'make tooling'; missing $VENV_DIR/bin/$executable"
done

core_version=$(
  "$VENV_DIR/bin/ansible-playbook" --version |
    awk 'NR == 1 {gsub(/[][]/, "", $3); print $3}'
)
lint_version=$(
  "$VENV_DIR/bin/python" -c 'import importlib.metadata; print(importlib.metadata.version("ansible-lint"))'
)

grep -Fxq "ansible-core==$core_version" "$ROOT_DIR/provisioning/requirements-controller.txt" ||
  fail "installed ansible-core $core_version does not match the exact project pin"
grep -Fxq "ansible-lint==$lint_version" "$ROOT_DIR/provisioning/requirements-controller.txt" ||
  fail "installed ansible-lint $lint_version does not match the exact project pin"

printf 'Tooling: OK (ansible-core %s, ansible-lint %s)\n' "$core_version" "$lint_version"
