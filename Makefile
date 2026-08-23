.DEFAULT_GOAL := help
SHELL := /bin/sh
CONFIG_FILE ?= .env

COMPOSE := docker compose --env-file versions.env --env-file .env
VENV_DIR ?= .venv
PYTHON ?= python3
UV_VERSION := 0.12.5
UV_CACHE_DIR := $(CURDIR)/.ansible/uv-cache
ifneq ($(filter /%,$(VENV_DIR)),)
VENV_PATH := $(VENV_DIR)
else
VENV_PATH := $(CURDIR)/$(VENV_DIR)
endif
VENV_BIN := $(VENV_PATH)/bin
CONTROLLER := $(VENV_BIN)/gateway-controller
UV := $(VENV_BIN)/uv
ANSIBLE_CONFIG_FILE := $(CURDIR)/provisioning/ansible.cfg
ANSIBLE_PLAYBOOK := $(VENV_BIN)/ansible-playbook
ANSIBLE_LINT := $(VENV_BIN)/ansible-lint
ANSIBLE_ENV := ANSIBLE_CONFIG="$(ANSIBLE_CONFIG_FILE)" ANSIBLE_HOME="$(CURDIR)/.ansible" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.ansible/tmp"
SHELL_FILES := install.sh $(wildcard scripts/*.sh) tests/smoke-local.sh

.PHONY: help init tooling tooling-check lint ansible-check check-config preflight install build up down restart logs status check update rotate-credentials backup validate test

help:
	@printf '%s\n' \
		'Controller configuration:' \
		'  make init          Create .env from .env.example without overwriting it' \
		'  make tooling       Install pinned Ansible tooling into .venv' \
		'  make tooling-check Verify controller commands and pinned tool versions' \
		'  make check-config  Validate local .env without connecting to a VPS' \
		'  make preflight     Read-only DNS, TCP, host-key, and SSH readiness checks' \
		'' \
		'Current server/runtime commands:' \
		'  make install       Run the transitional shell installer' \
		'  make status        Show the Caddy container status' \
		'  make check         Run the server acceptance checks' \
		'  make logs          Follow Caddy logs' \
		'  make backup        Create a credentials-bearing backup' \
		'  make rotate-credentials  Rotate credentials with rollback' \
		'  make update        Run the transitional server-side update' \
		'' \
		'Project checks:' \
		'  make lint          Run Ruff, mypy, shell, and Ansible static checks' \
		'  make ansible-check Run Ansible syntax and production lint checks' \
		'  make validate      Validate Compose and Caddy configuration' \
		'  make test          Run the pytest suite'

init:
	@if [ -e "$(CONFIG_FILE)" ]; then \
		printf 'Configuration already exists: %s (unchanged)\n' "$(CONFIG_FILE)"; \
	else \
		install -m 600 .env.example "$(CONFIG_FILE)"; \
		printf 'Created %s with mode 0600. Fill: VPS_HOST, SSH_PRIVATE_KEY, DOMAIN, ACME_EMAIL.\n' "$(CONFIG_FILE)"; \
	fi

tooling:
	@for command_name in "$(PYTHON)" ssh ssh-keygen make git; do \
		command -v "$$command_name" >/dev/null 2>&1 || { printf 'Tooling: ERROR: required command is missing: %s\n' "$$command_name" >&2; exit 1; }; \
	done
	@python_version="$$($(PYTHON) -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"; \
		case "$$python_version" in 3.12|3.13|3.14) ;; *) printf 'Tooling: ERROR: Python 3.12-3.14 is required; found %s\n' "$$python_version" >&2; exit 1 ;; esac
	@printf 'Creating or reusing controller virtualenv: %s\n' "$(VENV_PATH)"
	@$(PYTHON) -m venv "$(VENV_PATH)"
	@if ! "$(VENV_BIN)/python" -c 'import importlib.metadata, sys; raise SystemExit(importlib.metadata.version("uv") != sys.argv[1])' "$(UV_VERSION)" 2>/dev/null; then \
		PIP_CACHE_DIR="$(UV_CACHE_DIR)/pip" "$(VENV_BIN)/python" -m pip install --disable-pip-version-check --quiet "uv==$(UV_VERSION)"; \
	fi
	@UV_CACHE_DIR="$(UV_CACHE_DIR)" UV_PROJECT_ENVIRONMENT="$(VENV_PATH)" "$(UV)" sync --frozen
	@"$(CONTROLLER)" install-collections
	@"$(CONTROLLER)" tooling-check

tooling-check:
	@if [ ! -x "$(CONTROLLER)" ]; then printf 'Tooling: ERROR: run '\''make tooling'\''; missing %s\n' "$(CONTROLLER)" >&2; exit 1; fi
	@"$(CONTROLLER)" tooling-check

ansible-check: tooling-check
	@$(ANSIBLE_ENV) "$(ANSIBLE_PLAYBOOK)" --syntax-check provisioning/playbooks/bootstrap.yml
	@$(ANSIBLE_ENV) "$(ANSIBLE_PLAYBOOK)" --syntax-check provisioning/playbooks/deploy.yml
	@$(ANSIBLE_ENV) "$(ANSIBLE_PLAYBOOK)" --syntax-check provisioning/playbooks/verify.yml
	@PATH="$(VENV_BIN):$$PATH" $(ANSIBLE_ENV) XDG_CACHE_HOME="$(CURDIR)/.ansible/cache" "$(ANSIBLE_LINT)" --offline

lint: ansible-check
	@"$(VENV_BIN)/ruff" check .
	@"$(VENV_BIN)/ruff" format --check .
	@"$(VENV_BIN)/mypy" src
	@bash -n $(SHELL_FILES)
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck $(SHELL_FILES); \
	elif [ "$${REQUIRE_SHELLCHECK:-0}" = 1 ]; then \
		printf 'ERROR: shellcheck is required\n' >&2; exit 1; \
	else \
		printf 'SKIP: shellcheck is not installed (CI requires it)\n'; \
	fi

check-config: tooling-check
	@"$(CONTROLLER)" check-config --config "$(CONFIG_FILE)"

preflight: tooling-check
	@"$(CONTROLLER)" preflight --config "$(CONFIG_FILE)"

install:
	./install.sh

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart caddy

logs:
	$(COMPOSE) logs --tail=200 -f caddy

status:
	$(COMPOSE) ps

check:
	./scripts/check-server.sh

update:
	./scripts/update-server.sh

rotate-credentials:
	./scripts/rotate-credentials.sh

backup:
	./scripts/backup.sh

validate:
	$(COMPOSE) config --quiet
	$(COMPOSE) run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

test: tooling-check
	@"$(VENV_BIN)/pytest"
