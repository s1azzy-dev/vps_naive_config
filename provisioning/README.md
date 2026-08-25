# Ansible provisioning

Локальная и Molecule-часть фаз 4–6 реализует `make bootstrap`, роли
`bootstrap`/`user`/`ssh`/`firewall`/`docker`, idempotence,
validate-before-reload, точный UFW/`DOCKER-USER` allowlist и безопасные Docker
publication defaults. Полные Gates 4–6 остаются открытыми до reconnect,
lockout-negative, systemd/reboot и внешнего port-scan E2E на disposable VM/VPS.
Gateway deployment и `verify` ещё являются каркасом следующих фаз плана.

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
3.12–3.14 и Docker/Caddy runtime smoke. Workflow не запускает `preflight` и не
подключается к VPS.
