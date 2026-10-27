# Naive Gateway for VPS

Naive Gateway разворачивается на чистом Ubuntu/Debian VPS через Ansible. Локальный
controller проверяет настройки и SSH, Ansible настраивает пользователя, firewall,
Docker и Caddy. Клиентская конфигурация в репозиторий не входит.

## Установка

Подготовьте VPS с доступом по SSH-ключу, домен с `A`-записью на его публичный
IPv4 и доступные `22/tcp` (или выбранный SSH-порт), `80/tcp`, `443/tcp`.
Если есть `AAAA`, она должна указывать на доступный IPv6 этого VPS.

На своём компьютере:

```bash
make init
# Заполните .env в редакторе: VPS_HOST, SSH_PRIVATE_KEY, DOMAIN, ACME_EMAIL.
make tooling
make provision
```

Используйте абсолютный путь к приватному ключу. Публичный ключ по умолчанию
ищется рядом с ним с расширением `.pub`. `GATEWAY_REF` должен указывать на
опубликованный commit или ветку с нужной версией проекта: Ansible получает исходники
непосредственно на VPS и не копирует незакоммиченные изменения controller.
Приватный Git-репозиторий должен быть доступен root-пользователю VPS.

`make provision` выбирает bootstrap или уже подготовленный host, запрашивает
sudo-пароль без echo, разворачивает gateway и проверяет его. В интерактивном
терминале в конце показываются endpoint и учётные данные. После установки их
можно повторно получить командой `make credentials`. Локальный `.env` не
копируется на сервер; runtime credentials хранятся в
`/etc/naive-gateway/gateway.env` с правами `root:root 0600`.

Доступные отдельные команды: `make check-config`, `make preflight`,
`make bootstrap`, `make deploy`, `make verify` и `make credentials`.
Обновление выполняется с controller через `make deploy`.

## Управление на VPS

```bash
sudo make -C /opt/naive-gateway/current status
sudo make -C /opt/naive-gateway/current check
sudo make -C /opt/naive-gateway/current logs
sudo make -C /opt/naive-gateway/current validate
sudo make -C /opt/naive-gateway/current backup
sudo make -C /opt/naive-gateway/current rotate-credentials
sudo make -C /opt/naive-gateway/current restart
```

Backup сохраняется в `/var/backups/naive-gateway/` с правами `0600` и содержит
действующие секреты. Источник обновляется на controller; версии Caddy и
`forwardproxy` закреплены в `versions.env` и не следуют за `latest`.

Подробности, восстановление и диагностика: [docs/vps-setup.md](docs/vps-setup.md).
Открытые приёмочные проверки: [план provisioning](docs/ansible-provisioning-plan.md).
Приёмка на disposable VPS, включая SSH reconnect, firewall, reboot и публичный
TLS/proxy, пока не выполнена.
