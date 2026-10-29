# Текущий контракт

MVP: Ubuntu 26.04 LTS amd64, IPv4-only, без DOMAIN AAAA. Debian Molecule ниже —
локальный test fixture, не дополнительная production платформа. Актуальные
решения и отложенные VPS-gates — в [плане](../docs/ansible-provisioning-plan.md).

# Ansible provisioning

Локальная и Molecule-часть фаз 4–6 реализует `make bootstrap`, роли
`bootstrap`/`user`/`ssh`/`firewall`/`docker`, idempotence,
validate-before-reload, точный UFW/`DOCKER-USER` allowlist и безопасные Docker
publication defaults. Полные Gates 4–6 остаются открытыми до reconnect,
lockout-negative, systemd/reboot и внешнего port-scan E2E на disposable VM/VPS.
Gateway deployment реализуется ролью `naive_gateway` и командой `make deploy`.
`make provision` объединяет bootstrap, deploy и `verify`; `make credentials`
выводит действующие credentials в интерактивном терминале.

## Gateway deployment

Controller выполняет read-only preflight, требует managed SSH и запрашивает
текущий sudo password. Ansible проверяет sudo с новым timestamp до изменений,
проверяет Docker/порты и получает указанный source ref. Секреты передаются через
тот же inherited pipe, что и в bootstrap.

`/opt/naive-gateway/repository` служит source checkout. Активные bind mounts
указывают на отдельный snapshot `releases/<commit>`; `current` меняется после
успешной приёмки. Кандидат получает собственный image tag. До активации выполняются
проверка Compose boundary, build и `caddy validate` без production certificate
volumes. Существующий сервис при ошибке этих проверок не заменяется.

`gateway.env.pending` хранит подготовленные credentials с mode `0600`, чтобы
повтор после прерывания не генерировал их заново. Существующий `gateway.env` имеет
приоритет; явная пара из controller config заменяет credentials. После validation
runtime env записывается атомарно, Compose ожидает health, затем выполняются
public HTTPS и `check-server.sh`. При ошибке активации надо исправить причину и
повторить `make deploy`; deployment возвращает предыдущие env/release/container. При прерывании следующий
запуск сначала восстанавливает snapshot из `deployment-recovery`; при ошибке
самого recovery snapshot сохраняется и требуется диагностика.

Molecule использует отдельный Git fixture runtime-файлов этапа 7, настоящий
production Caddy image и local issuer. Он проверяет failed-first retry,
идемпотентность, отклонение invalid Caddy update, сохранение credentials и смену
source ref. Это не подтверждает public ACME и внешний acceptance.

`make verify` проверяет SSH, UFW, Docker ingress, права runtime файла, состояние
службы, commit/ref, фактические опубликованные порты и HTTPS/proxy; конфигурацию
сервера он не меняет. Для получения credentials controller читает runtime env
по SSH под sudo: пароль передаётся только через stdin, а результат печатается
только в интерактивном терминале. Изменения этапов 8–11 ещё не прошли gates.

## Граница firewall

- UFW защищает host services и разрешает только настроенный SSH TCP port,
  `80/tcp` и `443/tcp`; `443/udp` не открывается.
- Docker управляет NAT/forwarding, поэтому Ansible до его установки добавляет
  отдельную IPv4/IPv6 policy в `DOCKER-USER`: established traffic возвращается,
  к Docker bridges допускаются только original host TCP ports 80/443, остальное
  ingress к `docker0`/`br+` отбрасывается.
- Docker сохраняет firewall management, использует backend `iptables`, direct
  routing выключен, а неявные user-defined bridge publications по умолчанию
  bind-ятся к `127.0.0.1`. Compose публично объявляет только IPv4 TCP 80/443.
- Provider firewall полезен как независимый defense-in-depth, но не является
  предусловием: текущий хостер его не предоставляет, поэтому enforcement должен
  быть самодостаточным внутри VPS.
- Host/macvlan/ipvlan networking, Swarm, direct routing и application mounts
  Docker socket не входят в допустимую архитектуру.
- После deployment boundary подтверждается external sentinel/port scan на
  disposable VM/VPS; production VPS для destructive validation не используется.

## Правила секретов

- plaintext passwords и private keys запрещены в tracked inventory, variable и task files;
- sudo password существует только в памяти controller/Ansible process и передаётся
  через inherited `/dev/fd` pipe, не через environment, argv или временный файл;
- остальные чувствительные значения передаются только через runtime variables/templates
  либо Ansible Vault;
- каждая task, которая читает, генерирует, хеширует или записывает password,
  private key либо Naive credentials, обязана иметь `no_log: true`;
- `display_args_to_stdout = False` запрещает добавлять module arguments к task
  headings;
- pytest policy tests блокируют plaintext secrets и private keys до запуска
  playbook;
- ansible-lint с профилем `production` проверяет schema, включая role
  `meta/argument_specs.yml`;
- callback, пишущий task payload в файл или внешний сервис, не включается без
  отдельного security review.

## Проверки

Локально CI-контракты воспроизводятся командами:

```bash
make tooling
make lint
make test
make molecule
```

Molecule использует privileged disposable Debian 12 container, устанавливает
официальные Docker packages, запускает nested daemon и проверяет effective
loopback bind, UFW reload, Docker restart, exact chains и negative adoption.
Это не заменяет systemd boot и внешний network E2E на disposable VM/VPS.

GitHub Actions отдельно выполняет полный quality gate, pytest на Python
3.14 и Docker/Caddy runtime smoke. Workflow не запускает `preflight` и не
подключается к VPS.

Для локального Docker с отдельным CLI context (например, OrbStack) Python SDK
может потребовать явный сокет: `DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')" make molecule`.
Тестовый daemon ограничен watchdog на 2 часа; CI timeout остаётся 20 минут,
а обычное завершение сценария удаляет весь disposable instance.
