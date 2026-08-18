# Naive Gateway for VPS

Минимальный Docker-проект для запуска NaiveProxy-сервера на чистом VPS. Клиентская конфигурация в репозиторий не входит.

## Быстрый запуск

Сначала настройте пользователя `slazzy`, вход по SSH-ключу и firewall по шагам 1–6 в [подробном VPS-гайде](docs/vps-setup.md). Команды ниже выполняются в его SSH-сессии; `sudo` используется только для системных операций.

Нужны:

- чистый VPS с Ubuntu 22.04/24.04/26.04 или Debian 12/13;
- домен с `A`-записью на публичный IPv4 VPS;
- открытые входящие порты `22/tcp`, `80/tcp`, `443/tcp` и, при необходимости HTTP/3 для сайта, `443/udp`.

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/s1azzy-dev/vps_naive_config.git
cd vps_naive_config
sudo DOMAIN=proxy.example.com ACME_EMAIL=admin@example.com ./install.sh
```

Скрипт установит Docker из официального репозитория, проверит DNS, создаст случайные учётные данные, соберёт закреплённую версию Caddy с `forwardproxy`, выпустит TLS-сертификат и проверит запущенный сервер. В конце он выведет endpoint, имя пользователя и пароль. Они также хранятся в `.env` с правами `600`.

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
