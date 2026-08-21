.DEFAULT_GOAL := help
SHELL := /bin/sh
CONFIG_FILE ?= .env

-include $(CONFIG_FILE)

ifeq ($(strip $(VPS_PORT)),)
VPS_PORT := 22
endif
ifeq ($(strip $(VPS_BOOTSTRAP_USER)),)
VPS_BOOTSTRAP_USER := root
endif
ifeq ($(strip $(VPS_USER)),)
VPS_USER := slazzy
endif
ifeq ($(strip $(SSH_PUBLIC_KEY)),)
ifneq ($(strip $(SSH_PRIVATE_KEY)),)
SSH_PUBLIC_KEY := $(SSH_PRIVATE_KEY).pub
endif
endif
ifeq ($(strip $(GATEWAY_REPOSITORY)),)
GATEWAY_REPOSITORY := https://github.com/s1azzy-dev/vps_naive_config.git
endif
ifeq ($(strip $(GATEWAY_REF)),)
GATEWAY_REF := main
endif

COMPOSE := docker compose --env-file versions.env --env-file .env
VENV_DIR ?= .venv
ANSIBLE_CONFIG_FILE := $(CURDIR)/provisioning/ansible.cfg
ANSIBLE_PLAYBOOK := $(CURDIR)/$(VENV_DIR)/bin/ansible-playbook
ANSIBLE_LINT := $(CURDIR)/$(VENV_DIR)/bin/ansible-lint

.PHONY: help init tooling tooling-check ansible-check check-config install build up down restart logs status check update rotate-credentials backup validate test

help:
	@printf '%s\n' \
		'Controller configuration:' \
		'  make init          Create .env from .env.example without overwriting it' \
		'  make tooling       Install pinned Ansible tooling into .venv' \
		'  make tooling-check Verify controller commands and pinned tool versions' \
		'  make check-config  Validate local .env without connecting to a VPS' \
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
		'  make ansible-check Run Ansible syntax, lint, and secret checks' \
		'  make validate      Validate Compose and Caddy configuration' \
		'  make test          Run the static test suite'

init:
	@if [ -e "$(CONFIG_FILE)" ]; then \
		printf 'Configuration already exists: %s (unchanged)\n' "$(CONFIG_FILE)"; \
	else \
		install -m 600 .env.example "$(CONFIG_FILE)"; \
		printf 'Created %s with mode 0600. Fill: VPS_HOST, SSH_PRIVATE_KEY, DOMAIN, ACME_EMAIL.\n' "$(CONFIG_FILE)"; \
	fi

tooling:
	@VENV_DIR="$(VENV_DIR)" bash scripts/bootstrap-tooling.sh

tooling-check:
	@VENV_DIR="$(VENV_DIR)" bash scripts/check-tooling.sh

ansible-check: tooling-check
	@ANSIBLE_CONFIG="$(ANSIBLE_CONFIG_FILE)" ANSIBLE_HOME="$(CURDIR)/.ansible" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.ansible/tmp" "$(ANSIBLE_PLAYBOOK)" --syntax-check provisioning/playbooks/preflight.yml
	@ANSIBLE_CONFIG="$(ANSIBLE_CONFIG_FILE)" ANSIBLE_HOME="$(CURDIR)/.ansible" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.ansible/tmp" "$(ANSIBLE_PLAYBOOK)" --syntax-check provisioning/playbooks/bootstrap.yml
	@ANSIBLE_CONFIG="$(ANSIBLE_CONFIG_FILE)" ANSIBLE_HOME="$(CURDIR)/.ansible" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.ansible/tmp" "$(ANSIBLE_PLAYBOOK)" --syntax-check provisioning/playbooks/deploy.yml
	@ANSIBLE_CONFIG="$(ANSIBLE_CONFIG_FILE)" ANSIBLE_HOME="$(CURDIR)/.ansible" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.ansible/tmp" "$(ANSIBLE_PLAYBOOK)" --syntax-check provisioning/playbooks/verify.yml
	@PATH="$(CURDIR)/$(VENV_DIR)/bin:$$PATH" ANSIBLE_CONFIG="$(ANSIBLE_CONFIG_FILE)" ANSIBLE_HOME="$(CURDIR)/.ansible" ANSIBLE_LOCAL_TEMP="$(CURDIR)/.ansible/tmp" XDG_CACHE_HOME="$(CURDIR)/.ansible/cache" "$(ANSIBLE_LINT)" --offline
	@bash scripts/check-ansible-secrets.sh provisioning

check-config: export CONFIG_FILE := $(CONFIG_FILE)
check-config: export VPS_HOST := $(VPS_HOST)
check-config: export VPS_PORT := $(VPS_PORT)
check-config: export VPS_BOOTSTRAP_USER := $(VPS_BOOTSTRAP_USER)
check-config: export VPS_USER := $(VPS_USER)
check-config: export SSH_PRIVATE_KEY := $(SSH_PRIVATE_KEY)
check-config: export SSH_PUBLIC_KEY := $(SSH_PUBLIC_KEY)
check-config: export DOMAIN := $(DOMAIN)
check-config: export ACME_EMAIL := $(ACME_EMAIL)
check-config: export GATEWAY_REPOSITORY := $(GATEWAY_REPOSITORY)
check-config: export GATEWAY_REF := $(GATEWAY_REF)
check-config: export NAIVE_USER := $(NAIVE_USER)
check-config: export NAIVE_PASSWORD := $(NAIVE_PASSWORD)
check-config:
	@bash scripts/check-config.sh

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

test:
	./tests/run.sh
