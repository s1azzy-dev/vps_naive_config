# Naive Gateway for VPS

Минимальный Docker-проект для запуска NaiveProxy-сервера на чистом VPS. Клиентская конфигурация в репозиторий не входит.

## Статус Ansible provisioning

Локально реализованы и проверены bootstrap, user, SSH, UFW/`DOCKER-USER` и
Docker roles. Полные production gates намеренно открыты до reconnect,
lockout-negative, systemd/reboot и внешнего port-scan E2E на disposable VM/VPS.
Настроенный production VPS этой веткой пока не изменяйте.

Нужны:

- чистый VPS с Ubuntu 22.04/24.04/26.04 или Debian 12/13;
- домен с `A`-записью на публичный IPv4 VPS;
- открытые входящие порты `22/tcp`, `80/tcp`, `443/tcp`; `443/udp` закрыт.

`.env` копируется из `.env.example`, получает mode `0600` и заполняется
пользователем вручную. Значения и секреты не передаются через CLI. Переходный
`install.sh` больше не устанавливает Docker: он требует host, уже подготовленный
Ansible. Gateway deployment/controller будут завершены в фазах 7–8.

Текущий подробный workflow и открытые gates: [план provisioning](docs/ansible-provisioning-plan.md).

## Управление

```bash
sudo make status              # состояние контейнера
sudo make check               # полная внешняя проверка
sudo make logs                # журналы Caddy
sudo make backup              # архив конфигурации и секретов
sudo make rotate-credentials  # новые учётные данные
sudo make update              # git pull, пересборка и проверка
```

Подробная подготовка VPS и диагностика: [docs/vps-setup.md](docs/vps-setup.md).

## Что остаётся на сервере

- один контейнер Caddy;
- публичный HTTPS-сайт для обычного ответа на домене;
- Naive forward proxy на том же `443/tcp`;
- Docker volumes с сертификатами Caddy;
- `.env` с доменом и учётными данными.

Версии Caddy и модуля `forwardproxy` закреплены в `versions.env`; автоматического слежения за `latest` нет.
