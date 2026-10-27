# План перехода на Ansible provisioning

Статус: **In progress — найдены незакрытые дефекты реализации; приёмочные gates открыты**

Замечания аудита, обязательные исправления и предложения по упрощению собраны в
[разделе 10](#10-аудит-и-план-исправлений). До их устранения нельзя считать, что
остались только VPS-gates; прежние результаты относятся к состоянию на дату запуска.

Область: чистый Ubuntu/Debian VPS с доступом по SSH-ключу → работающий Naive Gateway  
Цель: одна основная команда `make provision`, при необходимости — раздельные проверяемые команды для каждого этапа.

## 1. Правила выполнения плана

1. Этапы выполняются строго по порядку.
2. Следующий этап начинается после прохождения gate предыдущего этапа, если владелец
   явно не согласовал отсрочку; отложенный gate остаётся открытым.
3. Любое изменение архитектуры сначала вносится в этот документ, затем в код.
4. Каждый этап должен оставлять проект в рабочем и проверяемом состоянии.
5. Переходный вызов `install.sh` допустим только до достижения функционального parity с Ansible.
6. После достижения parity `install.sh` удаляется: двух реализаций установки быть не должно.
7. Существующие незаконченные пользовательские изменения не перезаписываются и не откатываются.

## 2. Целевая модель

### 2.1. Ответственность локального компьютера

Локальный компьютер является Ansible controller и хранит:

- локальный checkout репозитория;
- `.env` с параметрами VPS и deployment;
- приватный SSH-ключ пользователя;
- Ansible и закреплённые версии необходимых collections;
- SSH host key VPS в project-local `provisioning/known_hosts` с правами `0600`.

Локальный `.env` никогда не копируется на VPS целиком.

### 2.2. Ответственность VPS

После provisioning на VPS остаются:

- административный пользователь `slazzy`;
- доступ только по SSH-ключу;
- пароль `slazzy`, используемый только для `sudo`;
- запрещённый root login по SSH;
- запрещённый password и keyboard-interactive login по SSH;
- UFW с разрешёнными `22/tcp`, `80/tcp`, `443/tcp`;
- Ansible-owned Docker ingress policy в `DOCKER-USER`, которая разрешает только
  исходные host ports `80/tcp` и `443/tcp` и блокирует остальные опубликованные
  container ports независимо от Docker DNAT;
- Docker Engine и Docker Compose plugin из официального apt-репозитория;
- root-owned checkout в `/opt/naive-gateway`;
- runtime-конфигурация `/etc/naive-gateway/gateway.env` с правами `0600`;
- контейнер Caddy и Docker volumes с сертификатами;
- серверные команды проверки, backup и ротации credentials.

`443/udp` в MVP не открывается: текущая конфигурация публикует только TCP и разрешает HTTP/1.1 и HTTP/2.

### 2.3. Что остаётся вне provider-neutral MVP

Ansible не создаёт и не изменяет:

- сам VPS через API провайдера;
- firewall в панели VPS-провайдера, если такая функция доступна;
- DNS-записи через API DNS-провайдера;
- локальный приватный SSH-ключ;
- клиентскую конфигурацию NaiveProxy.

До `make provision` должны существовать VPS, root/bootstrap SSH-доступ и корректная
`A`-запись. Provider firewall, если он доступен, рекомендуется как независимый
defense-in-depth слой для `VPS_PORT/tcp`, `80/tcp`, `443/tcp`, но не является
предусловием: полный обязательный ingress allowlist применяется внутри VPS до
первого публичного Docker container.

## 3. Конфигурационные файлы

### 3.1. Локальный `.env`

`.env.example` хранится в Git. `.env` создаётся пользователем, игнорируется Git и получает права `0600`.

Целевая схема:

```dotenv
VPS_HOST=
VPS_PORT=22
VPS_BOOTSTRAP_USER=root
VPS_USER=slazzy

SSH_PRIVATE_KEY=/absolute/path/to/slazzy_vps
SSH_PUBLIC_KEY=/absolute/path/to/slazzy_vps.pub

DOMAIN=
ACME_EMAIL=

GATEWAY_REPOSITORY=https://github.com/s1azzy-dev/vps_naive_config.git
GATEWAY_REF=main

# Необязательная фиксация credentials для восстановления/миграции.
# Должны быть заполнены оба значения или ни одного.
NAIVE_USER=
NAIVE_PASSWORD=
```

Обязательные пользовательские значения:

- `VPS_HOST`;
- `SSH_PRIVATE_KEY`;
- `DOMAIN`;
- `ACME_EMAIL`.

Правила:

- `SSH_PUBLIC_KEY`, если не задан, определяется как `${SSH_PRIVATE_KEY}.pub`;
- пути к ключам должны быть абсолютными;
- `NAIVE_USER` и `NAIVE_PASSWORD` либо оба пусты, либо оба заполнены;
- если Naive credentials пусты и серверного runtime-файла ещё нет, они генерируются один раз;
- sudo/root passwords в `.env` не хранятся;
- `.env` читает типизированный controller; Make не импортирует и не экспортирует его значения;
- отсутствие `.env` не должно ломать `make help` и `make init`.

### 3.2. Серверный `gateway.env`

Путь: `/etc/naive-gateway/gateway.env`  
Владелец: `root:root`  
Права: `0600`

Состав:

```dotenv
DOMAIN=proxy.example.com
ACME_EMAIL=admin@example.com
NAIVE_USER=generated-or-explicit-user
NAIVE_PASSWORD=generated-or-explicit-password
```

Инварианты:

- повторный `provision` или `deploy` не меняет существующие credentials;
- изменение `DOMAIN` или `ACME_EMAIL` применяется явно из локального `.env`;
- credentials изменяются только через `make rotate-credentials` либо явно переданные значения;
- значения не выводятся Ansible в обычных task logs;
- Compose читает именно этот файл, а не локальный `.env`.

## 4. Целевая структура проекта

```text
pyproject.toml
uv.lock

src/naive_gateway_controller/
  cli.py
  config.py
  network.py
  ssh.py
  preflight.py
  tooling.py

provisioning/
  ansible.cfg
  requirements.yml
  playbooks/
    bootstrap.yml
    deploy.yml
    verify.yml
  roles/
    bootstrap/
    user/
    ssh/
    firewall/
    docker/
    naive_gateway/
      meta/argument_specs.yml
  templates/
    ssh-hardening.conf.j2
    gateway.env.j2

scripts/
  check-server.sh
  backup.sh
  rotate-credentials.sh

tests/
  test_config.py
  test_network.py
  test_ssh.py
  test_preflight.py
  test_repository.py

.env.example
Makefile
```

Controller реализуется как типизированный Python package с CLI. Он отвечает только за локальную конфигурацию, read-only probes, выбор bootstrap/deploy path и запуск Ansible. Вся изменяющая VPS логика находится в Ansible.

### 4.1. Инструменты качества и тестовая пирамида

Быстрый локальный gate, запускаемый до обращения к VPS:

1. Ruff проверяет стиль, ошибки и формат Python-кода.
2. mypy в strict-режиме проверяет типы controller package.
3. pytest проверяет config, DNS, SSH state machine, CLI и repository contracts без сети.
4. `ansible-playbook --syntax-check` и ansible-lint с профилем `production` проверяют playbooks и roles.
5. `meta/argument_specs.yml` задаёт типизированный публичный контракт каждой роли и валидируется Ansible/ansible-lint.
6. Закреплённые зависимости устанавливаются через `uv sync --frozen` из `pyproject.toml` и `uv.lock`.

Интеграционный gate для каждой реальной Ansible role:

1. Molecule создаёт изолированный test instance, выполняет `converge`, второй idempotence run и `verify`.
2. pytest-testinfra проверяет итоговое состояние packages, users, files, services и commands.
3. Molecule и pytest-testinfra добавляются одновременно с первой ролью, которая их использует; в пустой skeleton они не устанавливаются.

Полный destructive E2E gate:

1. Выполняется только на disposable VM/VPS, никогда на production host.
2. Проверяет настоящий systemd, sshd, UFW, Docker, reconnect и lockout-negative scenarios.
3. Container-based Molecule не считается достаточным доказательством для SSH/UFW/systemd boundary.
4. Для Docker обязательно публикует test-only sentinel port на `0.0.0.0`,
   подтверждает его локальную доступность и внешний отказ при сохранении внешней
   доступности `80/tcp`/`443/tcp`; тест повторяется после UFW reload, Docker restart
   и reboot для IPv4 и, если включён, IPv6.
5. `ansible-test` не используется, пока проект не оформлен как Ansible collection; при таком переходе решение пересматривается.

Make остаётся стабильным пользовательским facade: команды принимают только путь к `.env`, а значения конфигурации через CLI не передаются.

## 5. Контракт пользовательских команд

### 5.1. `make init`

Назначение: подготовить локальную конфигурацию.

Пошагово:

1. Проверяет наличие `.env.example`.
2. Если `.env` отсутствует, копирует `.env.example` в `.env`.
3. Устанавливает `.env` права `0600`.
4. Если `.env` уже существует, не изменяет и не перезаписывает его.
5. Выводит путь к файлу и список обязательных полей.
6. Не подключается к VPS и ничего не устанавливает.

Успешный результат: локальный `.env` существует и готов к ручному заполнению.

### 5.2. `make tooling`

Назначение: установить или проверить controller-side зависимости отдельно от VPS.

Пошагово:

1. Проверяет наличие Python 3.12–3.14, `ssh`, `ssh-keygen`, `make` и Git.
2. Создаёт или повторно использует project-local `.venv`.
3. Устанавливает точную версию uv в project-local `.venv`.
4. Выполняет `uv sync --frozen` по `pyproject.toml` и `uv.lock`.
5. Устанавливает только фактически используемые Ansible collections из `provisioning/requirements.yml` в project-local `.ansible/collections`.
6. Проверяет точные версии uv, `ansible-core`, ansible-lint и установленных collections.
7. Не подключается к VPS.

Успешный результат: controller готов выполнять playbooks воспроизводимой версией инструментов.

### 5.3. `make check-config`

Назначение: локальная проверка `.env` без подключения к VPS.

Пошагово:

1. Проверяет существование `.env`.
2. Типизированная Pydantic Settings model читает файл напрямую, не экспортируя значения через Make или process environment.
3. Проверяет заполненность обязательных переменных и подставляет документированные defaults.
4. Проверяет формат `VPS_HOST`, `VPS_PORT`, `DOMAIN`, `ACME_EMAIL`.
5. Проверяет абсолютный путь и существование приватного SSH-ключа.
6. Определяет и проверяет публичный SSH-ключ.
7. Проверяет, что публичный ключ является одной строкой поддерживаемого OpenSSH-формата.
8. Проверяет совместное заполнение `NAIVE_USER` и `NAIVE_PASSWORD`.
9. Проверяет URL репозитория и непустой `GATEWAY_REF`.
10. Не печатает секретные значения.
11. Не подключается к VPS и ничего не изменяет.

Успешный результат: `Configuration: OK`.

### 5.4. `make preflight`

Назначение: read-only проверка готовности controller, DNS и VPS.

Пошагово:

1. Выполняет `make check-config`.
2. Проверяет наличие и версии controller/Ansible dependencies.
3. Разрешает `VPS_HOST` в IP, если задан hostname.
4. Получает `A`-записи `DOMAIN` и проверяет соответствие адресу VPS.
5. Проверяет `AAAA`: неверная или недоступная IPv6-запись считается блокирующей ошибкой перед deploy.
6. Проверяет доступность SSH-порта.
7. При первом подключении принимает новый host key через `accept-new` и сохраняет его в игнорируемый Git файл `provisioning/known_hosts` с правами `0600`.
8. Изменившийся известный host key считается ошибкой и никогда не принимается автоматически.
9. Проверяет вход под `VPS_USER` по ключу.
10. Если `VPS_USER` ещё недоступен, проверяет bootstrap-вход под `VPS_BOOTSTRAP_USER`.
11. Если недоступны оба входа, завершает работу без изменений.
12. Определяет режим: `bootstrap required` или `managed host ready`.
13. Не изменяет VPS.

Успешный результат: понятный отчёт DNS/SSH и выбранного режима.

### 5.5. `make bootstrap`

Назначение: безопасно создать постоянного административного пользователя и закрыть первоначальный root/password SSH-доступ.

Пошагово:

1. Выполняет `make preflight`.
2. Если managed user уже полностью настроен, сообщает об этом и не повторяет root bootstrap.
3. Подключается к VPS как `VPS_BOOTSTRAP_USER` по SSH-ключу.
4. На минимальном образе через `ansible.builtin.raw` устанавливает Python и `sudo`, необходимые Ansible.
5. Собирает системные facts.
6. Проверяет точный allowlist поддерживаемых Ubuntu/Debian версий и архитектур.
7. Проверяет корректность времени VPS, необходимого для apt и TLS.
8. Интерактивно и без echo запрашивает новый sudo-пароль `VPS_USER`, затем просит подтверждение.
9. Не записывает plaintext sudo-пароль в `.env`, inventory, аргументы процесса или task logs.
10. Создаёт группу и пользователя `VPS_USER` с домашним каталогом и login shell.
11. Устанавливает пароль пользователя только при его первоначальном создании.
12. Добавляет пользователя в группу `sudo`.
13. Не добавляет пользователя в группу `docker`.
14. Создаёт `~/.ssh` с правами `0700`.
15. Устанавливает ровно заданный публичный ключ в `authorized_keys` с правами `0600`.
16. С controller открывает отдельное новое SSH-соединение под `VPS_USER`.
17. Через новое соединение проверяет, что введённый пароль действительно даёт `sudo`.
18. До успешных шагов 16–17 не изменяет root/password SSH-доступ.
19. Создаёт отдельный OpenSSH drop-in с `PubkeyAuthentication yes`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`.
20. Выполняет `sshd -t`; при ошибке не reload-ит SSH.
21. Reload-ит SSH без разрыва текущих соединений.
22. Повторно открывает новое SSH-соединение под `VPS_USER`.
23. Проверяет, что вход под root по ключу отклоняется.
24. Проверяет, что password/keyboard-interactive SSH-вход отклоняется.
25. Устанавливает UFW.
26. До включения UFW разрешает `VPS_PORT/tcp`, `80/tcp`, `443/tcp`.
27. Устанавливает `deny incoming`, `allow outgoing` и rate limit для SSH.
28. Включает UFW.
29. Не открывает `443/udp`.
30. До установки Docker добавляет Ansible-owned UFW after-rules для `DOCKER-USER`:
    established traffic разрешён; новые соединения к исходным host ports
    `80/tcp`/`443/tcp` разрешены; остальной ingress к Docker bridge запрещён.
31. Валидирует candidate rules через `iptables-restore --test`/`ip6tables-restore --test`
    до UFW reload; ошибочный candidate не применяется.
32. Повторно проверяет новое SSH-соединение после включения UFW.
33. Выводит итоговые состояния пользователя, SSH и UFW без секретов.

Успешный результат: root/password SSH закрыт, `VPS_USER` входит по ключу и использует sudo, SSH остаётся доступен.

### 5.6. `make deploy`

Назначение: установить или обновить Docker и Naive Gateway на уже подготовленном VPS.

Пошагово:

1. Выполняет `make preflight`.
2. Требует успешный вход под `VPS_USER`; root bootstrap не выполняет.
3. Запрашивает текущий sudo-пароль без echo.
4. Проверяет sudo до любых изменений.
5. Повторно проверяет поддерживаемую ОС и архитектуру.
6. Проверяет соответствие `DOMAIN` публичному IP VPS.
7. Проверяет отсутствие некорректной `AAAA`-записи.
8. Проверяет, что `80/tcp` и `443/tcp` не заняты посторонними host services.
9. Устанавливает диагностические пакеты, Git и Make через apt.
10. Проверяет конфликтующие Docker-пакеты; неизвестную существующую установку Docker не удаляет автоматически.
11. Устанавливает официальный Docker signing key и deb822 apt source.
12. Устанавливает Docker Engine, CLI, containerd, Buildx и Compose plugin.
13. До первого запуска daemon устанавливает `daemon.json`: Docker firewall
    включён, backend закреплён как `iptables`, direct routing выключен, а
    default bind для неявно опубликованных user-defined bridge ports равен
    `127.0.0.1`.
14. Включает и запускает Docker service только после активной host ingress policy.
15. Проверяет `docker version`, `docker compose version`, фактический firewall
    backend и наличие точного `DOCKER-USER` jump/rules без дубликатов.
16. Не даёт `VPS_USER` доступ к Docker socket; Docker API по TCP и socket mount
    в application containers запрещены.
17. Запрещает для MVP `network_mode: host`, `macvlan`, `ipvlan`, Swarm и Docker
    direct routing: эти режимы обходят принятую bridge/`DOCKER-USER` boundary.
18. Требует явного public bind только для Caddy `80/tcp` и `443/tcp`; сокращённые
    будущие `ports` остаются loopback-only по безопасному daemon default.
19. Создаёт `/opt/naive-gateway` как root-owned deployment directory.
20. Клонирует `GATEWAY_REPOSITORY` или обновляет существующий checkout.
21. Получает только заданный `GATEWAY_REF` и проверяет фактический commit.
22. Не выполняет неявный переход на `latest`.
23. Создаёт `/etc/naive-gateway` с владельцем `root:root`.
24. Если `gateway.env` существует, читает его значения без вывода и сохраняет Naive credentials.
25. Если `gateway.env` отсутствует, использует явно заданные Naive credentials либо генерирует криптографически случайные значения один раз.
26. Записывает runtime-файл атомарно с правами `0600`.
27. Проверяет Docker Compose config с `versions.env` и серверным `gateway.env`.
28. Собирает закреплённый образ Caddy.
29. До изменения запущенного контейнера выполняет `caddy validate` для новой конфигурации.
30. Запускает или обновляет Compose project.
31. Ожидает container healthcheck.
32. Ожидает публичный HTTPS с валидным сертификатом.
33. При ошибке показывает безопасный диагностический tail логов без вывода credentials.
34. Запускает `scripts/check-server.sh`.
35. Выводит endpoint и credentials только в финальном интерактивном summary.
36. Не меняет SSH, пользователя и firewall, кроме проверки их состояния.

Успешный результат: контейнер healthy, публичный сайт и авторизованный proxy работают, credentials сохранены.

### 5.7. `make provision`

Назначение: основной сценарий «чистый VPS → работающий Naive Gateway».

Пошагово:

1. Выполняет `make check-config`.
2. Выполняет `make preflight`.
3. Если требуется bootstrap, выполняет все шаги `make bootstrap`.
4. Если managed host уже готов, bootstrap пропускается.
5. Если bootstrap запросил новый sudo-пароль, controller повторно использует его только в памяти и передаёт Ansible через pipe, не спрашивая второй раз.
6. Если managed host уже существовал, один раз запрашивает его текущий sudo-пароль без echo.
7. Выполняет все шаги `make deploy`.
8. Выполняет все шаги `make verify`.
9. Выводит единый итоговый отчёт и credentials.
10. При любой ошибке останавливается на соответствующем этапе и указывает безопасную команду продолжения.

Успешный результат: `Provisioning: PASS`.

### 5.8. `make verify`

Назначение: полная read-only проверка результата без изменения VPS.

Пошагово:

1. Выполняет `make check-config`.
2. Проверяет DNS `A` и `AAAA`.
3. Проверяет SSH-вход под `VPS_USER` по ключу.
4. Проверяет эффективные `sshd -T` значения.
5. Проверяет отрицательные сценарии root и password SSH login.
6. Проверяет состояние и правила UFW.
7. Проверяет, что пользователь не входит в группу `docker`.
8. Проверяет Docker service и Compose plugin.
9. Проверяет owner/mode deployment и runtime-файлов.
10. Проверяет checkout repository/ref/commit.
11. Проверяет Compose config и отсутствие неожиданных published ports.
12. Проверяет, что контейнер запущен и healthy.
13. Проверяет публичный сайт и HTTP status `200`.
14. Проверяет публично доверенный TLS certificate и hostname.
15. Проверяет ALPN HTTP/2.
16. Проверяет probe resistance без credentials.
17. Проверяет авторизованный HTTPS CONNECT.
18. Проверяет отсутствие destination hostname в Caddy logs.
19. Ничего не изменяет и не выполняет restart/reload.

Успешный результат: `Verification: PASS` с отдельным PASS по каждому слою.

### 5.9. `make credentials`

Назначение: повторно показать действующие Naive credentials.

Пошагово:

1. Проверяет конфигурацию и SSH-доступ.
2. Запрашивает sudo-пароль.
3. Читает `/etc/naive-gateway/gateway.env` без изменения файла.
4. Не выводит sudo-пароль и внутренние task variables.
5. Выводит только endpoint, Naive user и Naive password в финальном интерактивном блоке.

Успешный результат: credentials доступны владельцу sudo-доступа; сервер не изменён.

### 5.10. Серверные эксплуатационные команды

Эти команды выполняются в `/opt/naive-gateway` через `sudo`:

- `sudo make status` — показывает Compose containers и health, ничего не изменяет;
- `sudo make logs` — показывает безопасный tail/follow Caddy logs, ничего не изменяет;
- `sudo make check` — запускает прикладной `check-server.sh`, ничего не изменяет;
- `sudo make backup` — создаёт root-only архив runtime config и deployment metadata;
- `sudo make rotate-credentials` — создаёт новые Naive credentials, пересоздаёт Caddy, проверяет proxy и откатывает credentials при ошибке;
- `sudo make restart` — явно перезапускает только Caddy;
- `sudo make validate` — валидирует Compose и Caddy config без изменения работающего сервиса.

Серверный `make update` после перехода удаляется. Обновление выполняется с controller через `make deploy`.

### 5.11. Локальные команды качества

`make lint` выполняет по шагам:

1. Проверяет frozen toolchain и поддержку `accept-new` в OpenSSH.
2. Выполняет syntax-check каждого существующего Ansible playbook.
3. Запускает ansible-lint с обязательным профилем `production`.
4. Запускает Ruff rules и отдельную проверку форматирования.
5. Запускает mypy для controller package в strict-режиме.
6. Проверяет синтаксис оставшихся shell adapters и запускает shellcheck, если он установлен.
7. Не читает `.env`, не подключается к VPS и ничего не изменяет на VPS.

`make test` выполняет по шагам:

1. Проверяет frozen toolchain.
2. Запускает pytest для config, CLI, DNS, SSH, preflight и repository contracts.
3. Проверяет, что Make передаёт controller только путь к `.env`, а не значения полей.
4. Проверяет secret/logging policies и regression fixture с plaintext Ansible password.
5. Проверяет role argument specs, version pins, static site и Docker Compose config.
6. Не выполняет сетевые DNS/SSH probes и не изменяет VPS.

`make ansible-check` — быстрый Ansible-only subset `make lint`: tooling-check, syntax-check и ansible-lint production.

## 6. Последовательный план реализации

### Этап 0. Зафиксировать baseline

Работы:

- сохранить текущую функциональность без рефакторинга;
- зафиксировать этот план;
- записать текущий список поддерживаемых ОС;
- выполнить существующие static и local smoke tests;
- сохранить результаты как baseline.

Gate 0:

- [x] `make test` проходит;
- [x] local Caddy smoke проходит;
- [x] существующие пользовательские изменения сохранены;
- [x] план принят без открытых архитектурных вопросов.

Результат Gate 0 (2026-08-20): **PASS**.

- baseline commit: `de6c37864601f128bb69b3c9bae113e5c6e7870d`;
- branch: `codex/ansible-provisioning`;
- static suite: PASS;
- local Caddy/NaiveProxy runtime smoke: PASS;
- baseline smoke исправлен так, чтобы readiness и proxy checks использовали SNI `smoke.localhost`, для которого выпускается локальный сертификат.

### Этап 1. Ввести локальный config contract

Работы:

- добавить `.env.example`;
- расширить `.gitignore` для controller/runtime artifacts;
- реализовать `make init`;
- реализовать безопасный contract загрузки `.env`; окончательное чтение без импорта в Make выполняется в этапе 3.5;
- реализовать `make check-config`;
- обновить `make help`;
- добавить тесты пустых, частичных и некорректных значений.

Gate 1:

- [x] `make help` работает без `.env`;
- [x] `make init` не перезаписывает существующий `.env`;
- [x] пустой обязательный параметр даёт точную ошибку;
- [x] секреты не печатаются;
- [x] корректный `.env` заканчивается `Configuration: OK`;
- [x] VPS не затрагивается.

Результат Gate 1 (2026-08-22): **PASS**.

- добавлен tracked-шаблон `.env.example` и project-local artifact ignores;
- `make init` создаёт config с правами `0600` и не перезаписывает его;
- `make check-config` проверяет обязательные значения, форматы, SSH key paths, repository/ref и согласованность optional credentials;
- controller variables экспортируются только в `check-config` и не перекрывают Compose `--env-file`;
- config contract tests покрывают missing, partial, malformed и insecure-mode inputs;
- `make test`: PASS;
- local Caddy/NaiveProxy runtime smoke: PASS;
- runtime smoke стабилизирован для корректного SNI и `pipefail`, а Caddy templates явно включены для фактического MIME `text/xml` metadata-файла.

### Этап 2. Создать Ansible skeleton и quality gate

Работы:

- добавить `ansible.cfg`, `requirements.yml`, playbooks и пустые роли;
- закрепить совместимые версии `ansible-core`, ansible-lint и реально используемых collections;
- не добавлять collection без используемого модуля;
- добавить `community.docker` с точной версией одновременно с первым использующим её
  модулем: test-only Docker driver в Phase 4; production roles начнут использовать
  collection только в фазе Docker;
- реализовать `make tooling`;
- добавить syntax-check, ansible-lint и secret scan;
- исключить secret output через `no_log` и callback settings.

Gate 2:

- [x] зависимости устанавливаются воспроизводимо;
- [x] `ansible-playbook --syntax-check` проходит;
- [x] ansible-lint проходит;
- [x] playbooks не содержат plaintext passwords/keys;
- [x] существующие application tests проходят.

Результат Gate 2 (2026-08-22): **PASS**.

- первый и повторный `make tooling`: PASS, project-local `.venv`, точные версии `ansible-core 2.21.2` и `ansible-lint 26.6.0`;
- полный Python dependency lock: PASS, все controller-зависимости имеют точные версии;
- syntax-check `preflight.yml`, `bootstrap.yml`, `deploy.yml`, `verify.yml`: PASS;
- ansible-lint с обязательным профилем `production`: 0 failures, 0 warnings;
- `scripts/check-ansible-secrets.sh provisioning`: PASS, regression fixture с plaintext password блокируется;
- `make test`: PASS;
- `git diff --check`: PASS.

### Этап 3. Реализовать read-only preflight

Работы:

- реализовать DNS/IP/AAAA проверки;
- реализовать SSH port и host key проверки;
- реализовать безопасное определение bootstrap/managed режима;
- реализовать `make preflight`;
- обеспечить отсутствие remote changes.

Gate 3:

- [x] корректный новый VPS определяется как `bootstrap required`;
- [x] подготовленный VPS определяется как `managed host ready`;
- [x] неверный DNS блокирует deploy;
- [x] изменившийся host key блокирует подключение;
- [x] недоступный VPS завершается понятной ошибкой;
- [x] preflight не изменяет локальную или удалённую систему, кроме записи нового host key.

Результат Gate 3 (2026-08-23): **PASS**.

- `make preflight` end-to-end contract: PASS, значения прочитаны из controller `.env`, `check-config` выполнен автоматически;
- managed-user SSH доступен: выбран `managed host ready`, bootstrap login не выполняется;
- managed-user недоступен, bootstrap-user доступен: выбран `bootstrap required`;
- неверные `A`, неверные `AAAA` и недоступный IPv6: каждый сценарий блокируется до SSH login;
- недоступный SSH port и отказ ключа для обоих пользователей: блокируются с отдельными понятными ошибками;
- существующий изменившийся host key: блокируется, bootstrap fallback не выполняется;
- новый host key записывается только в `provisioning/known_hosts` с правами `0600`;
- SSH probe выполняет на VPS только read-only команду `true`; сценарный тест блокирует любую другую remote command;
- `make ansible-check`: PASS, включая 4 syntax-check, production ansible-lint, secret scan, DNS unit tests и SSH/DNS scenario tests;
- `make test`: PASS;
- `git diff --check`: PASS.

Live VPS smoke не выполнялся: локальный `.env` отсутствует. Gate подтверждён детерминированными сценарными тестами без внешних изменений.

### Этап 3.5. Стандартизировать controller и testing stack

Работы:

- перенести локальную config/preflight orchestration из shell в типизированный Python package;
- читать `.env` через Pydantic Settings без импорта значений в Make;
- сохранить пользовательские команды `make tooling`, `make check-config` и `make preflight`;
- заменить hand-written scenario runner на pytest с unit/contract tests;
- добавить Ruff и mypy strict;
- заменить `requirements-controller.txt` на `pyproject.toml` и воспроизводимый `uv.lock`;
- добавить `meta/argument_specs.yml` для каждой Ansible role;
- оставить shell только для тонких OS/runtime adapters, для которых shell является естественным интерфейсом;
- удалить controller shell scripts и fixtures после функционального parity;
- зафиксировать Molecule + pytest-testinfra как обязательный TDD gate первой реальной role в этапе 4;
- зафиксировать disposable VM/VPS E2E как обязательный gate для sshd/UFW/systemd/Docker.

Gate 3.5:

- [x] `make tooling` воспроизводимо выполняет frozen sync по `uv.lock`;
- [x] `make check-config` читает `.env` через типизированную model и не печатает secrets;
- [x] `make preflight` использует типизированные DNS/SSH components и сохраняет read-only contract;
- [x] pytest покрывает позитивные и негативные config/DNS/SSH/preflight scenarios;
- [x] Ruff, format check и mypy strict проходят;
- [x] Ansible syntax-check и ansible-lint production проходят;
- [x] role argument specs проходят schema validation;
- [x] заменённые shell scripts, hand-written fakes и scenario runner удалены;
- [x] существующие application tests проходят;
- [x] `git diff --check` проходит.

Результат Gate 3.5 (2026-08-23): **PASS**.

- `make tooling`: PASS на чистой временной virtualenv и при повторном frozen sync; 47 locked packages;
- controller package: Pydantic Settings, typed DNS/TCP report, typed SSH outcomes и явная preflight state machine;
- Make не импортирует `.env` и передаёт controller только путь через `CONFIG_FILE`;
- Ruff rules/format: PASS; mypy strict: 9 source files, 0 errors;
- pytest: 43 tests, включая Make UX, secret-safe config, DNS/AAAA, host-key change, SSH fallback и repository policies;
- Ansible syntax-check: `bootstrap.yml`, `deploy.yml`, `verify.yml` — PASS;
- ansible-lint `production`: 0 failures, 0 warnings; role argument specs провалидированы;
- заменённые controller shell scripts, fixtures, custom runner, Ansible preflight playbook и pip requirements lock удалены;
- Docker Compose config contract: PASS внутри pytest;
- `git diff --check`: PASS.

Live DNS/SSH preflight не выполнялся: локальный `.env` отсутствует. Read-only contract подтверждён изолированными typed tests; реальный host остаётся gate перед bootstrap.

### Этап 3.6. Настроить полный CI quality pipeline

Работы:

- заменить устаревший single-job workflow на отдельные quality, Python tests и runtime smoke jobs;
- запускать CI на `push`, `pull_request` и вручную через `workflow_dispatch`;
- ограничить `GITHUB_TOKEN` правами `contents: read`;
- отменять устаревший запуск для той же ветки или pull request через concurrency group;
- закрепить все сторонние Actions полными commit SHA с комментариями release versions;
- использовать Ubuntu 24.04 и явно заданные Python versions;
- в quality job устанавливать обязательный shellcheck и выполнять `make tooling`, затем `make lint`;
- в test matrix выполнять `make tooling` и `make test` на Python 3.12, 3.13 и 3.14;
- кэшировать project-local uv cache по `uv.lock`, не кэшировать `.venv`;
- в отдельном runtime job собирать pinned Caddy image, выполнять Caddy validate, проверять наличие `forward_proxy` module и запускать `tests/smoke-local.sh`;
- использовать только фиктивные CI credentials и не обращаться к реальному VPS, DNS или SSH;
- добавить pytest contract для структуры и обязательных команд workflow.

Gate 3.6:

- [x] workflow имеет минимальные permissions, concurrency cancellation и bounded timeouts;
- [x] сторонние Actions закреплены полными SHA;
- [x] quality job выполняет весь `make lint` и требует shellcheck;
- [x] pytest проходит на Python 3.12, 3.13 и 3.14;
- [x] Docker Compose config, Caddy validate/module check и runtime smoke выполняются отдельно;
- [x] workflow не читает production `.env`, не использует repository secrets и не подключается к VPS;
- [x] локальные `make lint`, `make test` и workflow contract tests проходят;
- [x] `git diff --check` проходит.

Результат Gate 3.6 (2026-08-23): **PASS**.

- workflow: 3 независимых jobs и 5 job instances — quality, pytest для Python 3.12/3.13/3.14 и runtime smoke;
- triggers: `push`, `pull_request`, `workflow_dispatch`; permissions: только `contents: read`;
- concurrency cancellation и timeouts: PASS по pytest workflow contract;
- `actions/checkout`, `actions/setup-python` и `astral-sh/setup-uv` закреплены полными commit SHA;
- quality: Ruff, format check, mypy strict, Ansible syntax-check, ansible-lint production и обязательный ShellCheck — PASS;
- pytest: 44 теста отдельно прошли на Python 3.12.13, 3.13.14 и 3.14.6;
- Docker: Compose build, Caddy validate и наличие `http.handlers.forward_proxy` — PASS;
- runtime: локальный TLS/HTTP2, authentication boundary и authenticated proxy request — PASS;
- workflow использует только временный файл с фиктивными credentials и не запускает preflight или SSH к VPS;
- `git diff --check`: PASS.

Удалённый GitHub Actions run ещё не выполнялся: workflow начнёт работать после commit и push ветки.

Этап 4 запрещено начинать до PASS Gate 3.6.

### Этап 4. Реализовать user и SSH bootstrap

Работы:

- bootstrap Python/sudo через raw;
- проверка ОС;
- создание `VPS_USER`, пароля, sudo membership и authorized key;
- проверка отдельного managed-user connection;
- применение SSH drop-in через validate-before-reload handler;
- отрицательные root/password login tests;
- повторный запуск без изменения пароля.
- до реализации tasks добавить Molecule scenario и pytest-testinfra assertions для user/SSH role contracts;
- container-capable assertions выполнять в Molecule, а настоящий reconnect/lockout сценарий — на disposable VM/VPS.

Проверяемая последовательность Phase 4:

1. Закрепить Molecule, Docker driver и pytest-testinfra в `pyproject.toml`/`uv.lock`,
   добавить `make molecule` и scenario на закреплённом Debian 12 container image.
2. До реализации roles добавить converge/idempotence/verify contract: prerequisites,
   allowlist ОС/архитектуры, user/home/sudo, exact `authorized_keys`, SSH effective config
   и rejection ошибочного drop-in. Ожидаемый RED фиксируется как доказательство TDD boundary.
3. Реализовать только `bootstrap`: raw-установка Python/sudo, facts, allowlist
   Ubuntu 22.04/24.04/26.04 и Debian 12/13, `x86_64`/`aarch64`, проверка времени.
4. Реализовать только `user`: создание account/home/sudo membership, первоначальная
   установка пароля и exact public key; на повторном запуске password и key неизменны.
5. Реализовать controller-side `make bootstrap`: `.env` читает Python, sudo-пароль
   запрашивается дважды без echo и передаётся Ansible только через inherited pipe,
   не через inventory, process arguments, environment или task logs.
6. После user role открыть отдельное соединение под `VPS_USER` и проверить key login
   и password-backed sudo; до успеха SSH hardening не запускается.
7. Реализовать `ssh`: отдельный drop-in, атомарный template с `sshd -t` validation,
   reload только handler-ом после успешной validation.
8. После hardening открыть новое managed-user connection и выполнить отрицательные
   root/key и password/keyboard-interactive probes. Container assertions не заменяют
   reconnect/lockout-negative E2E на disposable VM/VPS.

Журнал Phase 4:

- 2026-08-23 baseline, фактический clean HEAD `1c508c4` (`main/origin/main`):
  `make lint` PASS; `make test` PASS, 44 tests на Python 3.14.6.
- 2026-08-24 test harness: pinned `molecule 26.6.0`,
  `molecule-plugins[docker] 26.7.15`, `pytest-testinfra 10.2.2`, collections и
  Debian 12 OCI digest добавлены; `make lint` PASS; `make test` PASS, 44 tests;
  `make molecule` ожидаемо RED после успешных `syntax/create` на пустом
  `bootstrap` argument contract. Scenario provisioning и teardown исправны.
- 2026-08-24 roles `bootstrap` + `user`: `make lint` PASS; `make test` PASS,
  44 tests; Molecule `converge` PASS и `idempotence` PASS. В Debian 12 container
  проверены raw-установка Python/sudo, OS/architecture/time allowlist, создание
  account/home/sudo group, sudo с введённым паролем, exact public key и сохранение
  исходного shadow hash на втором run. Ожидаемый RED теперь только в `side_effect`
  из-за ещё отсутствующего SSH drop-in.
- 2026-08-24 controller bootstrap boundary: добавлен `make bootstrap`; Python
  выполняет preflight, дважды без echo запрашивает sudo password, передаёт plaintext
  Ansible через inherited pipe `/dev/fd`, открывает отдельный managed-user play с
  password-backed sudo до SSH role и выполняет post-hardening key/root/auth-method
  probes. `make lint` PASS; `make test` PASS, 53 tests, включая отсутствие password
  в argv/environment, recovery/skip state и blocking post-checks.
- 2026-08-24 локальная/Molecule часть Phase 4: **PASS**. Production
  `bootstrap.yml` выполнен самим scenario; Molecule `converge`, `idempotence`,
  invalid-template `side_effect`, 6 pytest-testinfra assertions и teardown — PASS.
  Candidate и full config проходят `sshd -t`; effective `sshd -T` подтверждает
  public-key only, root/password/keyboard-interactive settings. Финально:
  `make lint` PASS; `make test` PASS, 54 tests на Python 3.14.6; реальный
  `ansible-playbook --syntax-check` через inherited extra-vars pipe PASS;
  `git diff --check` PASS.

Gate 4 целиком остаётся **OPEN**: локальный `.env` отсутствует, disposable VM/VPS
не предоставлен, поэтому настоящий managed-user reconnect, root/password lockout-negative
и повторный E2E bootstrap не выполнялись.

Согласованное исключение (2026-08-24): владелец production VPS отложил disposable
E2E и разрешил перейти к Phase 5. Это исключение не закрывает Gate 4, не разрешает
изменять production VPS и ограничивает следующие фазы локальными, CI и Molecule
проверками до появления отдельной disposable VM/VPS.

Gate 4:

- [ ] новый пользователь входит по ключу;
- [x] sudo принимает заданный пароль в Debian 12 Molecule instance;
- [ ] root SSH login запрещён;
- [ ] password и keyboard-interactive login запрещены;
- [x] `sshd -t` проходит для candidate и полной конфигурации в Molecule;
- [x] повторный role converge не меняет пароль и authorized key;
- [x] искусственно ошибочный SSH template не применяется и не ломает работающий sshd;
- [x] Molecule converge/idempotence/verify и pytest-testinfra проходят;
- [ ] disposable VM/VPS reconnect и lockout-negative E2E проходят.

### Этап 5. Реализовать host firewall

Работы:

- установить UFW;
- применить default policies;
- разрешить SSH до enable;
- разрешить только `80/tcp` и `443/tcp` для gateway;
- включить UFW;
- проверить SSH после включения;
- до первого Docker daemon подготовить Ansible-owned `DOCKER-USER` ingress policy;
- валидировать IPv4/IPv6 candidate rules до UFW reload и не применять ошибочные rules;
- документировать Docker/UFW boundary и опциональный provider firewall.
- выполнить destructive firewall проверки на disposable VM/VPS.

Проверяемая последовательность Phase 5:

1. Подтвердить неизменный Phase 4 baseline командами `make lint`, `make test` и
   `make molecule` без обращения к VPS.
2. Закрепить `community.general`, добавить typed role contract и до реализации
   firewall tasks расширить Molecule/pytest-testinfra проверками package, default
   policies, allowlist `22/tcp`, `80/tcp`, `443/tcp`, отсутствия `443/udp` и
   идемпотентности. Ожидаемый RED зафиксировать в журнале.
3. Реализовать role в безопасном порядке: установить UFW, задать default policies,
   разрешить текущий SSH port и gateway TCP ports, затем включить UFW.
4. Подключить role к production playbook только после managed-user SSH hardening;
   controller после playbook обязан выполнить уже существующий новый SSH probe.
5. Проверить `make lint`, `make test`, Molecule converge/idempotence/verify и
   `git diff --check`; документировать границы Docker/UFW/provider firewall.
6. Добавить TDD contract для `DOCKER-USER`: exact Ansible-owned chains, original
   host-port allowlist `80/tcp`/`443/tcp`, established traffic, default drop для
   Docker bridges, IPv4/IPv6 candidate validation и rejection ошибочного template.
7. Реализовать policy как закреплённый UFW after-rules block до Docker installation;
   не скачивать и не исполнять сторонний `ufw-docker` root script.
8. Оставить настоящий SSH reconnect, внешний port scan и destructive UFW/Docker E2E
   открытыми до disposable VM/VPS; production VPS не использовать.

Журнал Phase 5:

- 2026-08-24 baseline после согласованного переноса disposable E2E: `make lint`
  PASS; `make test` PASS, 54 tests на Python 3.14.6; существующий Phase 4
  `make molecule` PASS (converge/idempotence/side-effect/verify/destroy).
- 2026-08-24 firewall test contract: закреплена `community.general 13.3.0`,
  добавлены typed role inputs, Docker `NET_ADMIN` и pytest-testinfra assertions
  для package/default policies/active state/exact rules/no `443/udp`. `make lint`
  PASS; `make test` PASS, 54 tests; `make molecule` ожидаемо RED: обе Phase 5
  assertions падают только из-за отсутствующих package `ufw` и binary `/usr/sbin/ufw`.
- 2026-08-24 firewall role и orchestration: production `bootstrap.yml` применяет
  UFW только после managed-user sudo check и SSH hardening; controller передаёт
  фактический `VPS_PORT` и после playbook открывает новое SSH-соединение. Role
  устанавливает UFW, отказывается перезаписывать чужие rules, добавляет SSH rate
  limit и только `80/tcp`/`443/tcp` до enable, задаёт deny-in/allow-out и проверяет
  active state. `make lint` PASS; `make test` PASS, 54 tests; `make molecule` PASS:
  converge/idempotence, negative unmanaged-rule side effect, 9 testinfra assertions
  и destroy. `git diff --check` PASS; Docker/UFW/provider boundary документирован;
  production VPS не затронут.
- 2026-08-24 Docker-ingress TDD contract: до tasks добавлены exact IPv4/IPv6
  `DOCKER-USER`/`NAIVE-GATEWAY-DOCKER` assertions, проверка original destination
  `80/tcp`/`443/tcp`, bridge default-drop и side-effect с ошибочным restore
  candidate. Первый повторный запуск Molecule не дошёл до scenario из-за
  sandbox-denied доступа к OrbStack socket; после разрешения локального disposable
  Docker access тестовый цикл выполнен полностью.
- 2026-08-24 Docker-ingress implementation: candidate rules сначала рендерятся в
  памяти и проходят `iptables-restore --test`/`ip6tables-restore --test`, затем
  помещаются в root-owned UFW after-rules и активируются reload handler.
  Невалидный candidate не меняет файл или активную policy. `make lint` PASS;
  `make test` PASS, 54 tests; `make molecule` PASS: converge, idempotence,
  negative invalid-template side effect, 12 testinfra assertions и destroy;
  `git diff --check` PASS. Production VPS не затронут.

Локальная/Molecule часть Phase 5, включая host-enforced Docker ingress boundary:
**PASS**. Настоящий reconnect,
внешний port scan и destructive UFW/Docker E2E остаются только для disposable VM/VPS.

Gate 5:

- [ ] SSH остаётся доступен;
- [x] в Debian 12 Molecule разрешены ровно `22/tcp`, `80/tcp`, `443/tcp`;
- [x] `443/udp` отсутствует в UFW rules и блокируется default deny в Molecule;
- [x] Molecule idempotence проходит и exact rules не содержат дубликатов;
- [x] Ansible-owned IPv4/IPv6 `DOCKER-USER` candidate проходит restore validation;
- [x] ошибочный Docker ingress candidate не изменяет активные UFW rules;
- [ ] внешний port scan после deploy не показывает неожиданных портов.
- [ ] disposable VM/VPS подтверждает доступность SSH после фактического включения UFW.

### Этап 6. Перенести установку Docker в Ansible

Работы:

- перенести apt prerequisites;
- добавить официальный signing key и deb822 repository;
- обработать Ubuntu/Debian codename и architecture;
- обнаруживать конфликтующие/неизвестные Docker installations;
- установить Engine/CLI/containerd/Buildx/Compose;
- включить service;
- проверить версии;
- сохранить Docker firewall management включённым и закрепить backend `iptables`;
- установить безопасный default bind `127.0.0.1` для неявных user-defined bridge publications;
- проверить, что UFW загружает Ansible-owned `DOCKER-USER` policy до Docker;
- разрешить только original host ports `80/tcp`/`443/tcp`, блокируя случайные
  explicit public mappings к тем же container ports;
- запретить direct routing, host/macvlan/ipvlan networking и Swarm в MVP;
- убрать Docker installation из `install.sh` на переходном этапе.
- добавить Molecule/pytest-testinfra проверки поддерживаемой части роли и disposable VM/VPS systemd E2E.

Проверяемая последовательность Phase 6:

1. Закрепить source identity hardening-плана и подтвердить Phase 5 baseline:
   `make lint`, `make test`, `make molecule`, `git diff --check`.
2. До Docker tasks добавить typed argument contract и testinfra assertions для
   official repo/key, exact package set, `daemon.json`, enabled/active daemon,
   Compose v2, root-only socket, отсутствия `VPS_USER` в `docker` group и
   `DOCKER-USER` rule ordering. Ожидаемый RED зафиксировать.
3. До package installation обнаружить legacy/conflicting/unmanaged Docker artifacts;
   неизвестную установку или чужой `daemon.json` не менять и завершать понятной ошибкой.
4. На чистом host сначала установить минимальные apt prerequisites и management marker,
   затем валидированные UFW Docker-ingress rules и безопасный `daemon.json`; только
   после этого добавлять официальный deb822 repository и устанавливать Docker packages.
5. Запустить daemon, проверить firewall backend, direct-routing policy, default bind,
   versions/socket/group invariants и точное отсутствие unmanaged `DOCKER-USER` rules.
6. В Molecule повторить converge/idempotence, UFW reload и Docker restart; rules
   должны сохраняться без дубликатов. Ошибочный candidate и unmanaged installation
   должны отклоняться без автоматического удаления или ослабления firewall.
7. Изменить Compose: публичные Caddy binds `80/tcp`/`443/tcp` объявляются явно;
   repository contract запрещает host/macvlan/ipvlan/Swarm/direct-routing и
   application mounts Docker socket.
8. Проверить `make lint`, `make test`, `make molecule`, Compose config/runtime smoke
   и `git diff --check`; записать результаты в журнал.
9. Оставить systemd boot ordering, реальный внешний sentinel-port test, IPv4/IPv6
   port scan и reboot E2E открытыми до disposable VM/VPS; production VPS не использовать.

Журнал Phase 6:

- 2026-08-24 hardening baseline, HEAD `1c508c4`, исходный working diff
  `sha256:f68893c032ff31b404478442ce52ce59cd80832ebf16d1b04985bbb9fade2252`:
  `make lint` PASS; `make test` PASS, 54 tests; Phase 5 `make molecule` PASS;
  `git diff --check` PASS. Выбран native `DOCKER-USER` + loopback-safe defaults;
  provider firewall недоступен и больше не является обязательным предусловием.
- 2026-08-25 Phase 6 TDD contract: добавлены typed Docker role inputs,
  pytest-testinfra assertions для official deb822 repo, pinned key SHA-256 и
  fingerprint, exact package set, Compose v2, `daemon.json`, marker, privilege
  boundary, effective default bind и UFW/restart persistence. Repository tests
  требуют явные `0.0.0.0:80:80/tcp`/`0.0.0.0:443:443/tcp`, запрещают Docker
  socket и host/macvlan/ipvlan network boundary. `make test` ожидаемо RED:
  2/56 tests падали только на отсутствующих role defaults/tasks и старых Compose
  binds; Molecule ожидаемо RED после успешных syntax/converge/idempotence на
  отсутствующем `/etc/naive-gateway/docker-managed`.
- 2026-08-25 Docker role implementation: clean-host adoption, root-owned marker,
  validated fail-closed daemon policy, pinned official key, deb822 repository и
  packages `docker-ce`, CLI, containerd, Buildx и Compose v2. Неизвестные
  package/binary/repository/config artifacts не удаляются и не принимаются без
  marker; firewall также отказывает до любых UFW mutations, если находит
  unmanaged Docker. Пакетные версии намеренно следуют `state: present` в
  official stable repository, чтобы получать security updates; immutable
  identity закреплена checksum/fingerprint ключа и exact package names.
- 2026-08-25 transitional boundary: `install.sh` больше не устанавливает и не
  настраивает Docker, а требует Ansible-managed marker и Compose v2. Compose
  публикует только explicit IPv4 TCP 80/443; неявные user-defined bridge binds
  проверяются как `127.0.0.1`. `make lint` PASS; `make test` PASS, 57 tests;
  `git diff --check` PASS.
- 2026-08-25 Molecule runtime: первый nested daemon restart дал RED из-за гонки
  test harness — socket исчезал до завершения первого `dockerd`; после ожидания
  фактического PID exit полный цикл PASS: syntax, converge, idempotence,
  side-effect, 18 testinfra assertions и destroy. В privileged Debian 12
  container реально стартовал Docker, user-defined network получил loopback
  bind, UFW reload и Docker restart сохранили exact ingress chains, unmanaged
  Docker adoption/firewall reconciliation были отклонены. Production VPS не
  затронут.
- 2026-08-25 Compose/runtime checks: repository pytest выполняет Compose config
  с isolated fake env и подтверждает exact public TCP binds. `make validate`
  ожидаемо не запускался без вручную созданного пользовательского `.env`; Codex
  не создавал и не читал этот файл. Независимый `tests/smoke-local.sh` PASS:
  локальный TLS/HTTP2, сайт, authenticated CONNECT и log-redaction contract.
- 2026-08-25 final local gate после усиления marker ownership: `make lint` PASS;
  `make test` PASS, 57 tests; hardening JSON parse и `git diff --check` PASS;
  `make molecule` PASS — все 8 actions, включая converge/idempotence,
  side-effect, verify и final destroy. VPS connections не выполнялись.

Локальная/Molecule часть Phase 6 для Debian 12: **PASS**. Gate 6 остаётся
**IN PROGRESS**: systemd enable/boot ordering, остальные поддерживаемые ОС,
внешний sentinel/port scan и reboot требуют disposable VM/VPS.

Gate 6:

- [ ] Docker устанавливается на каждой поддерживаемой ОС;
- [ ] Docker service enabled и active;
- [x] Compose v2 доступен в Debian 12 Molecule;
- [x] пользователь не входит в `docker` group в Molecule;
- [x] повторный converge не переустанавливает Docker без причины;
- [x] неизвестная существующая Docker installation не удаляется автоматически.
- [x] Docker daemon candidate закрепляет backend `iptables` и выключает direct routing;
- [x] неявные user-defined bridge publications bind-ятся к `127.0.0.1` в nested Docker;
- [x] `DOCKER-USER` разрешает только original host `80/tcp`/`443/tcp` и не содержит дубликатов;
- [x] UFW reload и Docker restart не снимают Docker ingress policy в Molecule;
- [ ] explicit sentinel mapping `0.0.0.0:18080` недоступен извне;
- [ ] Molecule idempotence и disposable VM/VPS Docker service E2E проходят.

### Этап 7. Перенести Naive Gateway deployment в Ansible

Последовательность реализации (2026-09-14):

1. Baseline на `ee1c3f5`: `make lint` PASS, `make test` PASS (57 tests).
2. Добавить typed role contract и `make deploy`: controller выполняет preflight,
   требует managed SSH и передаёт текущий sudo password через существующий pipe;
   Ansible проверяет sudo до установки пакетов и изменения deployment.
3. Уточнить layout `/opt/naive-gateway`: `repository/` — root-owned Git checkout
   заданного ref, `releases/<commit>/` — неизменяемый snapshot, `current` — ссылка
   на последний успешно принятый release. Обновление checkout не меняет bind mounts
   работающего Caddy. Release-specific image tag исключает замену активного image
   при неуспешной подготовке кандидата. Старые releases пока не удаляются.
4. Credentials сначала сохраняются в private `gateway.env.pending`, затем
   Compose/build/Caddy validation проверяют candidate. Только после validation
   атомарно обновляется `gateway.env` и запускается Compose с health wait.
   Pending-файл остаётся для безопасного повтора после прерывания; существующий
   runtime env имеет приоритет. DOMAIN/ACME_EMAIL берутся из controller config.
5. Проверить fresh/repeated deploy, сохранение credentials и container ID,
   отказ invalid Caddy candidate без изменения активного контейнера/runtime env,
   восстановление после прерванной подготовки и смену source ref в Molecule.
6. Выполнить lint/pytest/Molecule/Caddy smoke и записать результаты. Public ACME,
   внешний acceptance и остающиеся Gates 4–6 проверяются только на disposable VPS.

Runtime-path support в Make/common/backup/rotation входит в Phase 7, поскольку
иначе deployment и acceptance использовали бы разные credentials. Полные
backup/restore/rotation failure gates и удаление server-side update остаются Phase 9.
`make provision`, отдельные `verify`/`credentials` и интерактивная выдача credentials
остаются Phase 8. На этом этапе deploy выводит endpoint без секретов.

Работы:

- root-owned checkout `/opt/naive-gateway`;
- checkout заданного ref/commit;
- создать `/etc/naive-gateway/gateway.env`;
- сохранить существующие credentials;
- реализовать атомарную генерацию новых credentials;
- адаптировать Compose/Make/scripts к новому runtime env path;
- build, Compose config, Caddy validate, up и health wait;
- сохранить `check-server.sh` как acceptance test;
- добавить безопасный error reporting.

Gate 7:

- [x] чистый deploy заканчивается healthy container в Debian 12 Molecule;
- [x] повторный deploy не меняет credentials в Molecule;
- [x] повторный deploy без source changes сохраняет container ID в Molecule;
- [x] неверный Caddyfile блокируется до замены работающего сервиса и runtime env;
- [x] после отказа первой candidate validation повтор сохраняет подготовленные credentials;
- [x] runtime env имеет `root:root 0600` в Molecule;
- [ ] `scripts/check-server.sh` проходит.

Результаты Phase 7 (2026-09-15):

- `make lint` с обязательным shellcheck: PASS (Ruff, format, mypy strict,
  Ansible syntax и production lint).
- `make test`: PASS, 62 tests. Добавлены managed-only deploy/secret transport/error
  tests и проверка runtime path без влияния ambient Compose environment.
- Изолированный Phase 7 playbook: PASS, 234 успешные remote tasks. Проверены
  failed-first recovery, повтор без изменений, invalid Caddy update и смена
  commit/branch с сохранением credentials. Ошибки Caddy ожидаемы и отдельно
  проверяются по failed stage; произвольная ошибка окружения не засчитывается.
- `tests/smoke-local.sh`: PASS (TLS/HTTP2, website, authenticated CONNECT,
  probe resistance, log redaction).
- Итоговый `make molecule`: PASS — полный сценарий от создания instance до
  converge/idempotence, negative side effects, gateway deployment, 21 testinfra
  tests и финального destroy. Тестовый контейнер удалён.
- `git diff --check`: PASS.

Gate 7 целиком остаётся **OPEN** до public ACME, внешнего HTTPS/proxy acceptance и
`check-server.sh` на disposable VPS. `.env` пользователя и production VPS не
использовались. Полные Gates 4–6 остаются открытыми. На 2026-09-15 этапы 8–11
ещё не были реализованы; их последующее состояние описано ниже.

### Этап 8. Реализовать полный verify и command UX

2026-10-27: владелец проекта разрешил реализовать этапы 8–11 сразу, не ожидая
gates: свободного VPS нет. Все незакрытые gates остаются открытыми, результаты
удалённой приёмки и проверок на поддерживаемых ОС не предполагаются успешными.
Отдельные проверки и gates для изменений 2026-10-27 не запускались по запросу
владельца. Результаты от 2026-09-15 относятся к прежнему состоянию файлов.
Для выдачи credentials controller использует отдельный read-only SSH/sudo вызов
с передачей sudo-пароля через stdin; секреты не передаются в argv или env.
`provision` удерживает один sudo-пароль в памяти на время вызова и не сохраняет его.

Работы:

- реализовать `make verify`;
- реализовать `make credentials`;
- собрать aggregator `make provision`;
- обеспечить ясные этапы вывода и итоговый summary;
- разделить read-only и mutating targets;
- исключить credentials из task logs.

Реализация 2026-10-27: добавлены `provision`, `verify`, `credentials`, проверка
отрицательных SSH-сценариев и read-only playbook проверки host и gateway. Добавлены
сценарии для будущей проверки sudo/SSH, повторного использования пароля и выдачи
credentials; они не запускались. Gate 8 не выполнялся; поведение на VPS и
интерактивный workflow требуют приёмки.

Gate 8:

- [ ] `make provision` на чистом VPS выполняет bootstrap, deploy и verify;
- [ ] `make provision` на готовом VPS безопасно пропускает bootstrap;
- [ ] `make verify` не показывает Ansible changes;
- [ ] каждый слой имеет отдельный PASS/FAIL;
- [ ] `make credentials` ничего не изменяет;
- [ ] при ошибке понятен этап и безопасная команда продолжения.

### Этап 9. Перенести эксплуатационные пути

Работы:

- адаптировать status/logs/check/backup/rotate/restart/validate к `/etc/naive-gateway/gateway.env`;
- перенести backups из Git checkout в root-only operational path;
- заменить server-side update на controller-side `make deploy`;
- проверить rollback ротации credentials;
- обновить Make targets и help.

Реализация 2026-10-27: команды используют server runtime env, backup сохраняется
в root-only `/var/backups/naive-gateway`, ротация восстанавливает предыдущий env
при ошибке и перезапускает Caddy, обновление выполняется с controller. Restore и
оба пути ротации ещё не проверены на VPS; Gate 9 остаётся открытым.

Gate 9:

- [ ] все документированные команды используют один runtime env;
- [ ] backup содержит необходимые файлы и имеет права `0600`;
- [ ] restore проверен на тестовом VPS;
- [ ] rotation success и rollback paths проверены;
- [ ] server-side `git pull` больше не является поддерживаемым deployment path.

### Этап 10. Удалить переходный установщик

Работы:

- составить parity checklist между `install.sh` и Ansible;
- подтвердить перенос каждой функции;
- удалить `install.sh` и `make install`;
- удалить остаточную дублирующую логику;
- убедиться, что application scripts не устанавливают OS packages/Docker.

Parity перед удалением `install.sh`:

- проверка OS/arch, user, SSH и firewall → bootstrap roles;
- DNS и доступность → controller preflight;
- диагностические пакеты и Docker → roles `naive_gateway` и `docker`;
- runtime env, credentials, build и Caddy validation → `naive_gateway`;
- HTTPS/CONNECT/health → `check-server.sh` и `verify`;
- вывод credentials → интерактивные `provision` и `credentials`;
- server-side update → controller `make deploy`.

Переходные `install.sh`, `make install`, `scripts/update-server.sh` и
`make update` удалены. Это сравнение реализации не закрывает Gate 10.

Gate 10:

- [ ] каждая функция старого `install.sh` имеет Ansible replacement или явно удалена;
- [ ] `rg 'install.sh'` не находит устаревших пользовательских инструкций;
- [ ] существует ровно один поддерживаемый provisioning path;
- [ ] полный test и verify gate проходит.

### Этап 11. Документация и end-to-end приёмка

Работы:

- переписать README quick start;
- переписать `docs/vps-setup.md` под `.env` и Make UX;
- добавить recovery/diagnostics guide;
- проверить команды копированием из документации;
- провести тесты на всех поддерживаемых ОС.

Документация quick start, эксплуатации и восстановления обновлена. Выполнение
примеров и приёмка на ОС не проводились; Gate 11 остаётся открытым.

Gate 11:

- [ ] Ubuntu 22.04 проходит fresh provision и second run;
- [ ] Ubuntu 24.04 проходит fresh provision и second run;
- [ ] Ubuntu 26.04 проходит fresh provision и second run;
- [ ] Debian 12 проходит fresh provision и second run;
- [ ] Debian 13 проходит fresh provision и second run;
- [ ] README содержит путь от `.env` до работающего proxy;
- [ ] recovery после частичного сбоя документирован и проверен;
- [ ] итоговый `make provision` требует одну пользовательскую команду после заполнения `.env`.

## 7. Финальный acceptance checklist

Provisioning считается завершённым только если одновременно выполнено следующее:

- [ ] пользователь создан с правильными owner/group/home/shell;
- [ ] sudo-пароль работает и не хранится в plaintext-конфигурации;
- [ ] публичный ключ и fingerprint корректны;
- [ ] root/password SSH login запрещены;
- [ ] повторное SSH-подключение проверено после hardening и UFW;
- [ ] host `DOCKER-USER` является обязательной Docker ingress boundary; provider
      firewall документирован как опциональный defense-in-depth слой;
- [ ] на VPS открыты только ожидаемые порты;
- [ ] Docker установлен из официального репозитория;
- [ ] пользователь не имеет доступа к Docker socket;
- [ ] repository checkout root-owned и соответствует заданному ref;
- [ ] runtime credentials не меняются на повторном запуске;
- [ ] секреты не попадают в Git и Ansible task logs;
- [ ] Compose и Caddy config валидны до запуска;
- [ ] контейнер healthy;
- [ ] HTTPS/TLS/HTTP2/probe resistance/authenticated CONNECT проверены;
- [ ] backup, restore и credential rollback проверены;
- [ ] второй `make provision` безопасен;
- [ ] `make verify` полностью read-only;
- [ ] `install.sh` и server-side update path удалены после parity;
- [ ] документация соответствует фактическим командам.

## 8. Рекомендуемый рабочий сценарий после реализации

Первичная локальная подготовка:

```bash
make init
# Заполнить .env.
make tooling
```

Новый VPS одной командой:

```bash
make provision
```

Раздельный диагностируемый запуск:

```bash
make check-config
make preflight
make bootstrap
make deploy
make verify
```

Повторное обновление:

```bash
make deploy
make verify
```

Получение действующих credentials:

```bash
make credentials
```

## 9. Условия для следующей фазы

Provider-specific OpenTofu/cloud-init слой рассматривается только после завершения этого плана. Он должен создавать VPS, provider firewall и DNS, но вызывать тот же Ansible deployment contract, а не реализовывать установку повторно.

## 10. Аудит и план исправлений

Дата аудита: **2026-10-27**. Статус всех пунктов ниже — **OPEN**. Это план
исправлений, а не свидетельство их выполнения. Этапы 8–11 нельзя считать готовыми
только за исключением VPS-gates: обнаружены ошибки реализации и проверки.

Существующее решение остаётся ориентиром: один VPS и один Caddy, локальный
controller, Ansible как слой изменений сервера, SSH по ключу и приватный runtime
env. Упрощение не должно незаметно ослабить защиту или удалить согласованные
пользовательские сценарии. Для изменений архитектуры сначала обновлять этот план.

### 10.1. Обязательные исправления

Порядок ниже — рекомендуемая последовательность: сначала сделать рабочими и
достоверными проверки, затем исправить восстановление и уточнить поддерживаемый
scope. Каждый пункт требует собственной проверки; незакрытые общие gates и VPS
приёмка остаются открытыми независимо от исправления отдельных пунктов.

#### A01. Некорректный YAML в `verify` — блокер

- **Проблема на момент аудита:** выражения с объектами `HostIp`/`HostPort` в
  `provisioning/playbooks/verify.yml` не разбирались YAML-парсером.
  `make provision` вызывает deploy до verify и может изменить VPS, прежде чем
  обнаружит ошибку. Точечный `ansible-lint` завершился ошибкой на строке 339;
  в памяти исправление обоих выражений позволило разобрать документ.
- [x] Исправить YAML обоих сравнений. 2026-10-27 локальные `make lint` с
  обязательным shellcheck и `make test` (67 tests) прошли.
- [ ] Проверить поведение сравнений и остальных выражений playbook на целевом host.
- [ ] Добавить раннюю локальную проверку синтаксиса обязательных playbooks до
  удалённых изменений, чтобы некорректный verify не обнаруживался после deploy.
- [ ] Проверить вызов `provision` с ошибочным verify без изменений VPS.

Синтаксическая часть устранена; A01 остаётся **OPEN**, пока не реализована ранняя
проверка до изменений VPS и не подтверждено поведение на целевом host.

#### A02. Ложный PASS анонимного CONNECT — безопасность проверки proxy

- **Проблема:** `scripts/check-server.sh` проверяет отсутствие характерного
  ответа `407`, но не требует отказа анонимному CONNECT. В локальном mock
  анонимный CONNECT вернул HTTP 200, а проверка завершилась `Server checks
  passed`. Это дефект проверки; открытость реального proxy не установлена.
- [ ] Проверять обе стороны: аутентифицированный CONNECT к выбранной достижимой
  цели успешен, а тот же запрос без credentials не может получить её ответ.
- [ ] Сохранить проверку probe resistance: отказ не должен раскрывать очевидные
  proxy headers/ответы. Не считать сетевую ошибку доказательством отказа proxy.
- [ ] Добавить локальные позитивные и негативные сценарии, включая ошибочно
  открытый proxy; покрыть используемый `check-server.sh`, а не только отдельный
  smoke script. Учитывать недоступность внешней цели, чтобы не объявлять
  корректный сервис сломанным из-за стороннего сайта.

#### A03. `sshd -T` без контекста не доказывает запрет root/password SSH

- **Проблема:** `provisioning/playbooks/verify.yml` читает `sshd -T` без `-C`;
  `Match` может менять настройки для конкретного пользователя/адреса. Локальный
  синтетический конфиг показал глобальное `permitrootlogin no` и одновременно
  `permitrootlogin yes` для root. Проба входа проверяет только переданный ключ:
  его отказ не исключает доступ root другим ключом. Password-method probe
  относится к managed user и сам по себе не доказывает политику для всех users.
- [ ] Проверять эффективные параметры с корректным контекстом root и managed
  user (`sshd -T -C ...`) и определить безопасную обработку `Match`-правил,
  зависящих от адреса/пользователя; не заявлять полный запрет по одной пробе.
- [ ] Проверить классификацию ошибок SSH: локальная ошибка ключа или алгоритма
  не должна трактоваться как доказательство запрета root-доступа.
- [ ] Добавить локальный сценарий с `Match User root` и негативные SSH-пробы.
  Реальный reconnect/lockout-negative остаётся обязательным VPS-gate.

#### A04. Bootstrap через non-root пользователя

- **Проблема:** первый play становится root через `VPS_BOOTSTRAP_USER`, но
  использует пароль нового managed user и не запрашивает отдельно существующий
  sudo-пароль bootstrap user. После hardening controller проверяет отказ входа
  именно bootstrap user, называя его root. Для `VPS_BOOTSTRAP_USER=ubuntu`
  разрешённый вход `ubuntu` вызывает ложную ошибку. Локальный mock воспроизвёл
  последовательность `ubuntu → managed user → ubuntu` и ошибку проверки root.
- [ ] Явно разделить bootstrap-user и root при проверках. Для non-root с
  password-backed sudo обеспечить передачу его существующего пароля отдельно от
  пароля нового пользователя, только в памяти/через защищённый канал.
- [ ] Покрыть root bootstrap, non-root с password-backed sudo и non-root с
  NOPASSWD; не считать NOPASSWD доказательством правильности нового пароля sudo.
- [ ] Если поддержка non-root bootstrap признана ненужной, сначала согласовать
  с владельцем сужение контракта и документации; не удалять её молча.

#### A05. Повтор `provision` пропускает незавершённый bootstrap

- **Проблема:** `run_provision` считает hardened SSH достаточным основанием
  пропустить bootstrap, не проверяя UFW и Docker ingress. Уже существующий
  managed user с отключённым root SSH, но без настроенного firewall, приводит к
  ошибке Docker role и требует ручного `make bootstrap`. Текущий mock-тест
  закрепляет пропуск bootstrap и не моделирует состояние firewall.
- [ ] Обеспечить безопасный повтор после частичного bootstrap и для подготовленного
  managed user без UFW: либо идемпотентно применять необходимые роли, либо явно
  проверять все предпосылки. Не удалять отдельную проверку нового SSH и sudo
  перед hardening.
- [ ] Добавить сценарии прерывания и managed SSH без firewall; одна команда
  `make provision` должна продолжать работу либо безопасно объяснять восстановление.

#### A06. Согласованность состояния при ошибке обновления

- **Проблема:** `gateway.env` заменяется до Compose up/health/public acceptance,
  а `current` переключается позже. Ошибка между этими шагами может оставить
  старый сервис, новый runtime env и старый `current` либо новый контейнер со
  старой ссылкой. При явной новой паре прежние credentials не сохраняются в
  отдельном rollback-файле; существующий тест invalid Caddyfile проверяет отказ
  только до активации. Сообщение `credentials were retained` не доказывает
  сохранность прежней пары или согласованность сервиса.
- [ ] Определить и реализовать простой контракт восстановления: сохранить
  предыдущие runtime env/release и обеспечить согласованность env, `current`,
  контейнера и фактических credentials при ошибке или повторе.
- [ ] Не обещать автоматический rollback без реализации. Если выбран ручной
  recovery вместо него, описать точные безопасные шаги и сохранять всё нужное для
  возврата; учесть первый deploy без предыдущего сервиса.
- [ ] Добавить сценарии сбоя после записи env, Compose up, health и публичной
  проверки, с изменением credentials и domain; проверить backup и повтор.
  Не удалять старые данные и credentials до подтверждения успешного состояния.

#### A07. Неопределённый IPv6-контракт и конфликт SSH-портов

- **Проблема:** `network.py` отклоняет AAAA при `VPS_HOST` в виде IPv4 literal,
  даже если IPv6 достижим. При hostname с A/AAAA он проверяет IPv6 по SSH-порту,
  но `compose.yml` публикует `80/443` только на `0.0.0.0`. Документация при этом
  допускает корректную AAAA. Локальная модель воспроизвела отказ при IPv4
  literal и достижимой AAAA.
- [ ] Согласовать один ясный MVP-контракт: рекомендовано IPv4-only и ранний отказ
  при AAAA, **если IPv6 не нужен**. Если IPv6 нужен, явно реализовать публикацию
  и проверку `80/443` по IPv6, корректное определение адресов одного VPS и
  соответствующие external gates. Не сужать scope без решения владельца.
- [ ] Отклонять `VPS_PORT=80` и `VPS_PORT=443` локально до изменений VPS: оба
  значения сейчас принимаются, но конфликтуют с портами gateway.
- [ ] Обновить `.env.example`, preflight, verify и инструкции под выбранную
  политику; добавить сценарии IPv4 literal, hostname, AAAA и резервных портов.

#### A08. Credentials внутри Git URL

- **Проблема:** `GATEWAY_REPOSITORY` допускает HTTPS URL со встроенным паролем
  или token. Ansible `git` запускает Git с URL в аргументах; `no_log` скрывает
  Ansible-вывод, но при обычных настройках `/proc` аргументы могут быть видны
  локальным пользователям. URL также сохраняется в Git config и backup.
  Принятие userinfo подтверждено на синтетическом URL.
- [ ] Запретить HTTPS userinfo, включая token в имени пользователя. Для SSH URL
  сохранить обычный непарольный username (`git@...` / `ssh://git@...`), но не
  разрешать пароль в URL. Документировать root-доступ к private repository через
  SSH deploy key или другой способ, не передающий секрет в URL/argv.
- [ ] Добавить проверки допустимых публичных/SSH URL и отклонения userinfo без
  вывода проверяемого секрета; учесть защиту уже созданных backup archives.

### 10.2. Дополнительные замечания, которые необходимо не потерять

#### A09. Восстановление credentials не должно зависеть от DNS сайта

- **Проблема:** `read_credentials` вызывает полный preflight, включая DNS domain.
  Ошибка DNS может помешать получить credentials при работающих managed SSH и
  sudo — именно во время диагностики.
- [ ] Разделить необходимые проверки: для чтения credentials проверять настройки
  соединения, host key, managed SSH и sudo; не требовать исправности DNS gateway.
  Сохранить интерактивный вывод и передачу sudo-пароля через stdin без argv/env.
- [ ] Добавить сценарий: DNS gateway недоступен, SSH работает, credentials
  доступны; при ошибке host key или sudo чтение запрещено.

#### A10. `tooling-check` принимает неработающий Git

- **Проблема:** проверяется только `shutil.which`/`command -v`. На controller
  `/usr/local/bin/git` существует, но завершается `Bad CPU type in executable`;
  `/usr/bin/git` работает. Наличие пути не доказывает работоспособность команды.
- [ ] Проверять запуск нужных бинарников и выдавать понятную ошибку при неверной
  архитектуре; не изменять системный PATH или установленный Git автоматически.
- [ ] Покрыть сценарий найденного, но не запускающегося Git; локальный обход
  через системный `/usr/bin/git` не считать исправлением проекта.

#### A11. Уже существующий managed user и другие ключи/группы

- **Проблема/граница scope:** user role использует `append: false` и
  `exclusive: true`. При bootstrap одноимённой существующей учётной записи это
  может удалить её другие группы и authorized keys. Контракт одного ключа ранее
  был зафиксирован, но автоматическое принятие произвольной существующей учётной
  записи и потеря аварийного доступа должны быть явным решением.
- [ ] Для MVP определить чистый host и безопасное поведение при существующем
  неуправляемом пользователе: предпочтительно отказаться с понятной диагностикой
  либо предусмотреть явно согласованную миграцию. Для уже управляемого user
  сохранить запрет доступа к Docker и согласованный контракт ключей.
- [ ] Добавить сценарий существующего пользователя с дополнительными ключами и
  группами; не удалять их незаметно при ошибочной автоматической adoption.

#### A12. Составная SSH-конфигурация и восстановление

- **Риск для проверки:** SSH role валидирует candidate как отдельный файл, затем
  заменяет drop-in; проверка полной конфигурации выполняется handler после
  записи. Если составная конфигурация окажется некорректной, файл уже изменён,
  хотя reload не выполняется. Практический сценарий такой ошибки ещё не
  воспроизведён и не должен объявляться подтверждённой уязвимостью.
- [ ] Проверить возможность ошибки на полной конфигурации и обеспечить проверку
  до замены либо восстановление прежнего файла при неудачной полной проверке.
- [ ] Сохранить `sshd -t` до reload и VPS-gate с новым SSH-сеансом и негативным
  lockout-сценарием; при неудаче не терять исходный доступ.

#### A13. Восстановление из backup и публикация исходников

- **Ограничение:** руководство использует сохранённый commit и URL для нового
  deploy, поэтому репозиторий и commit должны оставаться доступны. Backup также
  содержит файлы release и приватные данные, включая возможный Git URL. Restore,
  rollback ротации и доступность сохранённого commit ещё не проверены на VPS.
- [ ] Документировать зависимость recovery от доступного Git/commit и выбрать,
  нужна ли автономная restore-возможность при недоступном репозитории. Не
  создавать второй установщик без согласованного решения о scope.
- [ ] Проверить restore, права `0700`/`0600`, успешную и неуспешную ротацию и
  сохранение прежних credentials. Сохранить старый VPS/backup до приёмки нового.
- [ ] Перед первым реальным deploy опубликовать нужный код и явно выбрать
  доступный `GATEWAY_REF`: локальные незакоммиченные изменения не попадают на VPS.

### 10.3. Предложения по минимализму — решения владельца

Эти предложения не являются уже принятыми изменениями. Сначала согласовать
поддерживаемый scope и обновить контракт; не удалять единственные существующие
проверки до появления подходящей замены.

- [ ] **ОС и архитектура:** выбрать для MVP фактическую ОС и архитектуру целевого
  VPS вместо обязательства поддерживать пять релизов ОС и две архитектуры.
  Остальные платформы оставить последующим расширением и не заявлять их как
  проверенные. Сначала выяснить целевую среду у владельца.
- [ ] **IPv6:** если не требуется — IPv4-only и явная проверка отсутствия AAAA;
  если требуется — полноценная поддержка с отдельными проверками. Решение и
  связанное ограничение зафиксировать в A07 и пользовательской документации.
- [ ] **Один источник firewall-правил:** убрать дублирование точных списков
  `DOCKER-USER` между Docker role и `verify`; хранить согласованный контракт в
  одном месте. Сохранить UFW и Docker ingress policy: без provider firewall они
  защищают разные пути входящего трафика.
- [ ] **Меньше повторных probes:** сократить повторные DNS/SSH preflight внутри
  `provision`, deploy, verify и credentials. Сохранить исходный preflight,
  отдельное новое managed SSH-соединение до hardening и проверку результата.
  Для credentials применять минимально необходимые проверки из A09.
- [ ] **Тестовая инфраструктура:** пересмотреть nested Docker/Molecule сценарий
  и дублирование со smoke и будущим disposable VPS E2E. Сейчас это единственное
  доступное локальное свидетельство роли; заменять или сокращать его только
  после появления более простой проверки с теми же важными гарантиями.
- [ ] **Короткий актуальный план:** выделить текущий MVP-контракт, команды,
  открытые дефекты и gates в компактную основную часть. Хронологию и результаты
  уже выполненных этапов перенести в историю, сохранив даты, решения и evidence.
- [ ] **Хранение releases:** определить простую политику сохранения текущего и
  предыдущего успешного release/image. Очистку старых версий выполнять только
  после подтверждения успешного состояния; не удалять используемые образы,
  volumes, backups или данные для незавершённого восстановления.
- [ ] **Controller:** не переписывать Python/Ansible границу только ради меньшего
  числа строк. Сначала устранить повторение и объединить проверки, сохранив
  типизированный `.env`, безопасную передачу секретов и воспроизводимый UX.
- [ ] **Зависимости:** определить простой порядок обновления закреплённых Caddy
  version и forwardproxy commit. Учесть, что Docker base images заданы тегами,
  а apt-пакеты Docker не закреплены точными версиями; это не полная побитовая
  воспроизводимость. Актуальность и CVE в этом аудите не проверялись.

### 10.4. Evidence аудита и оставшиеся gates

- 23 целевых pytest для CLI/controller/runtime: PASS; это не полный `make test`.
- Точечные Ruff, mypy strict, ShellCheck и `git diff --check`: PASS.
- На момент аудита точечный `ansible-lint` для `verify.yml`: **FAIL**, ошибка YAML
  в A01; впоследствии синтаксис исправлен и полный локальный `make lint` прошёл.
- Локальный mock подтвердил ложный PASS при анонимном CONNECT; для запуска на
  macOS Bash 3.2 во временной копии изменялся только синтаксис приведения domain к
  нижнему регистру. Реальный proxy и сервер этим mock не проверялись.
- Локальный OpenSSH на синтетической конфигурации подтвердил расхождение
  `sshd -T` и `sshd -T -C` при `Match User root`; non-root bootstrap и сетевые
  входные значения воспроизведены без VPS, на mock/синтетических данных.
- Molecule и Caddy smoke от 2026-09-15 относятся к прежнему состоянию файлов;
  новые `verify`, `provision`, check и backup/rotation ими не подтверждены.
  Полный Molecule, полный CI и VPS-gates в этом аудите не запускались.
- Поддержка всех заявленных ОС/архитектур, public ACME, external port scan,
  IPv6, reboot, restore и реальные SSH lockout-negative остаются непроверенными.
  Актуальность и CVE зависимостей, а также формальный полный security scan не
  оценивались. Исходный VPS и пользовательский `.env` не использовались.

После исправлений выполнить согласованные локальные проверки и зафиксировать их
на конкретном состоянии кода. Реальный SSH/firewall/Docker/reboot, внешний
HTTPS/CONNECT, restore и повторный запуск проверить на disposable VM/VPS, когда
он появится. До этого не закрывать Gates 4–11 и не объявлять production-ready.
