SHELL := /bin/sh
COMPOSE := docker compose --env-file versions.env --env-file .env

.PHONY: install build up down restart logs status check update rotate-credentials backup validate test

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
