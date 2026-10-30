# Устройство Ansible и тестов

Пошаговая установка, схема, все настройки и команды находятся в
[основном README](../README.md). Здесь описаны файлы provisioning и проверки.
Production target: Ubuntu 26.04 LTS amd64, IPv4.

## Что запускается

Controller передаёт single-host inventory и runtime variables при запуске
Ansible; `inventory/empty.yml` не содержит адресов/секретов. Конфигурация
`ansible.cfg` задаёт project-local roles, collections, cache и SSH policy.

| Playbook | Порядок действий |
| --- | --- |
| `playbooks/bootstrap.yml` | prerequisites → user → managed SSH/sudo → SSH hardening → firewall |
| `playbooks/deploy.yml` | ownership/sudo → facts → Docker → gateway release/activation |
| `playbooks/verify.yml` | ownership/SSH → UFW/ingress → permissions/runtime → installed release/image → real ports → HTTPS/proxy |
| `playbooks/restore.yml` | ownership/sudo → Docker → acceptance tools → backup transfer → restore |

| Role / файл | Ответственность |
| --- | --- |
| `roles/bootstrap` | Python/sudo prerequisites, ОС/архитектура/часы |
| `roles/user` | account, один ключ, ownership marker; пароль задаётся только при создании |
| `roles/ssh` | Проверка всей SSH config, drop-in, reload и восстановление при ошибке |
| `roles/ssh_policy` | Общая проверка effective `sshd -T -C` для root/managed контекстов |
| `roles/firewall` | UFW и IPv4/IPv6 Docker ingress; выбран только IPv4 endpoint |
| `roles/docker` | Официальный apt repository, daemon config, service и ingress boundary |
| `roles/naive_gateway` | Проверка входов → `release.yml` → `credentials.yml` → `activate.yml`; diagnostics при отказе |
| `vars/docker_ingress.yml` | Единый allowlist для firewall templates, Docker role и verify |
| `scripts/runtime_state.py` | Приватный snapshot, атомарные env/current, commit/recover runtime |

Повторные проверки перед изменением кандидата и после запуска сервиса проверяют
разные состояния. SSH reload выполняется внутри recovery block; Docker/UFW
handlers срабатывают при изменении конфигурации. Неиспользуемых SSH handlers нет.
Пути установки фиксированы; test-only switches не являются поддержкой других ОС.

## Секреты и границы

Sudo passwords передаются через inherited `/dev/fd` pipe, не через argv,
environment или временный файл. Читающие/генерирующие/записывающие секреты tasks
имеют `no_log`; `display_args_to_stdout = False` скрывает аргументы в headings.
Private keys и plaintext passwords запрещены в tracked inventory/vars/tasks.
Callback, экспортирующий payload, не входит в проект.

UFW защищает host services. Docker управляет NAT/forwarding, поэтому отдельный
`DOCKER-USER` allowlist допускает к Docker bridges только original host TCP
ports 80/443 и established traffic. Обе address families защищены, хотя endpoint
IPv4-only. Неявные bridge publications bind-ятся к loopback; direct routing
выключен. Host/macvlan/ipvlan, Swarm и Docker socket mounts не используются.

## Локальные проверки и CI

```bash
make tooling
REQUIRE_SHELLCHECK=1 make lint
make test
make molecule
```

Lint проверяет Python/types, shell и Ansible syntax/production profile.
Pytest проверяет controller, secrets, recovery и backup/restore; scoped release
checks выполняют настоящие задачи `verify.yml` на временных файлах с Docker/Git
заглушками. Для них Ansible должен иметь доступ к локальному RPC/socket.

Molecule создаёт **privileged disposable Debian 12 container**: настоящий sshd,
UFW, Docker packages и nested daemon. `converge.yml` применяет host roles,
`side_effect.yml` проверяет негативные случаи и firewall persistence, подключает
`audit.yml`, `deployment.yml` и `audit-runtime.yml` для deployment/recovery/rotation.
Testinfra проверяет итоговое состояние. Причина ожидаемого отказа должна
подтверждаться; произвольная ошибка не считается успешным negative test.

Debian — только fixture, не production support. Из-за отсутствия systemd внутри
контейнера service management заменяется явным запуском daemon. Watchdog — 2 часа,
обычный сценарий заканчивается destroy; CI job ограничен 20 минутами.
Для отдельного Docker context Python SDK может требовать явный socket:

```bash
DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')" make molecule
```

Отдельный Caddy smoke использует production Dockerfile/Caddyfile/site и local
issuer вместо публичного ACME. Нужны Docker, OpenSSL и curl с HTTP/2 и
`--proxy-http2`. В корне проекта создайте временный env и соберите image:

```bash
smoke_env=$(mktemp)
chmod 600 "$smoke_env"
printf '%s\n' 'DOMAIN=smoke.localhost' 'ACME_EMAIL=ci@example.com' \
  'NAIVE_USER=smoke-user' 'NAIVE_PASSWORD=smoke-password' > "$smoke_env"
docker compose --env-file versions.env --env-file "$smoke_env" -f compose.yml build
rm -f "$smoke_env"
./tests/smoke-local.sh
```

Временные значения тестовые, `.env` владельца не используется. Smoke выбирает
image по `versions.env`; `SMOKE_IMAGE` позволяет явно выбрать другой собранный
image. Проверяются site, sitemap/robots, TLS/HTTP2, CONNECT с credentials и отказ
без них, отсутствие proxy destinations в логах. Затем только в тестовом контейнере
read-body idle timeout сокращается до 1 секунды и разрешается local origin:
authenticated CONNECT по HTTP/2 должен получить его ответ после паузы 3 секунды.
Production Caddyfile не меняется. Тестовые containers/files удаляются.

GitHub Actions отдельно запускает lint, pytest, Molecule и Caddy smoke, без VPS
credentials. Проверки source config и настоящего runtime сохраняют разные границы;
дополнительных reusable workflows/artifact pipelines для объединения build нет.
Контейнерные результаты не подтверждают Ubuntu systemd/reboot, внешний port scan
и публичный ACME. Открытая приёмка — в [текущем плане](../docs/ansible-provisioning-plan.md).
