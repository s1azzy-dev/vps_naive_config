# План перехода на Ansible provisioning

Статус: **Proposed**  
Область: чистый Ubuntu/Debian VPS с доступом по SSH-ключу → работающий Naive Gateway  
Цель: одна основная команда `make provision`, при необходимости — раздельные проверяемые команды для каждого этапа.

## 1. Правила выполнения плана

1. Этапы выполняются строго по порядку.
2. Следующий этап начинается только после прохождения gate предыдущего этапа.
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
- Docker Engine и Docker Compose plugin из официального apt-репозитория;
- root-owned checkout в `/opt/naive-gateway`;
- runtime-конфигурация `/etc/naive-gateway/gateway.env` с правами `0600`;
- контейнер Caddy и Docker volumes с сертификатами;
- серверные команды проверки, backup и ротации credentials.

`443/udp` в MVP не открывается: текущая конфигурация публикует только TCP и разрешает HTTP/1.1 и HTTP/2.

### 2.3. Что остаётся вне provider-neutral MVP

Ansible не создаёт и не изменяет:

- сам VPS через API провайдера;
- firewall в панели VPS-провайдера;
- DNS-записи через API DNS-провайдера;
- локальный приватный SSH-ключ;
- клиентскую конфигурацию NaiveProxy.

До `make provision` должны существовать VPS, root/bootstrap SSH-доступ, корректная `A`-запись и provider firewall для `22/tcp`, `80/tcp`, `443/tcp`.

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
4. `ansible-test` не используется, пока проект не оформлен как Ansible collection; при таком переходе решение пересматривается.

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
30. Повторно проверяет новое SSH-соединение после включения UFW.
31. Выводит итоговые состояния пользователя, SSH и UFW без секретов.

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
13. Включает и запускает Docker service.
14. Проверяет `docker version` и `docker compose version`.
15. Не даёт `VPS_USER` доступ к Docker socket.
16. Создаёт `/opt/naive-gateway` как root-owned deployment directory.
17. Клонирует `GATEWAY_REPOSITORY` или обновляет существующий checkout.
18. Получает только заданный `GATEWAY_REF` и проверяет фактический commit.
19. Не выполняет неявный переход на `latest`.
20. Создаёт `/etc/naive-gateway` с владельцем `root:root`.
21. Если `gateway.env` существует, читает его значения без вывода и сохраняет Naive credentials.
22. Если `gateway.env` отсутствует, использует явно заданные Naive credentials либо генерирует криптографически случайные значения один раз.
23. Записывает runtime-файл атомарно с правами `0600`.
24. Проверяет Docker Compose config с `versions.env` и серверным `gateway.env`.
25. Собирает закреплённый образ Caddy.
26. До изменения запущенного контейнера выполняет `caddy validate` для новой конфигурации.
27. Запускает или обновляет Compose project.
28. Ожидает container healthcheck.
29. Ожидает публичный HTTPS с валидным сертификатом.
30. При ошибке показывает безопасный диагностический tail логов без вывода credentials.
31. Запускает `scripts/check-server.sh`.
32. Выводит endpoint и credentials только в финальном интерактивном summary.
33. Не меняет SSH, пользователя и firewall, кроме проверки их состояния.

Успешный результат: контейнер healthy, публичный сайт и авторизованный proxy работают, credentials сохранены.

### 5.7. `make provision`

Назначение: основной сценарий «чистый VPS → работающий Naive Gateway».

Пошагово:

1. Выполняет `make check-config`.
2. Выполняет `make preflight`.
3. Если требуется bootstrap, выполняет все шаги `make bootstrap`.
4. Если managed host уже готов, bootstrap пропускается.
5. Если bootstrap запросил новый sudo-пароль, повторно использует его только в памяти текущего Ansible process и не спрашивает второй раз.
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
- добавить `community.docker` с точной версией в фазе Docker одновременно с первым использующим её модулем;
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

Gate 4:

- [ ] новый пользователь входит по ключу;
- [ ] sudo принимает заданный пароль;
- [ ] root SSH login запрещён;
- [ ] password и keyboard-interactive login запрещены;
- [ ] `sshd -t` проходит;
- [ ] повторный bootstrap не меняет пароль и authorized key;
- [ ] искусственно ошибочный SSH template не применяется и не вызывает lockout.
- [ ] Molecule converge/idempotence/verify и pytest-testinfra проходят;
- [ ] disposable VM/VPS reconnect и lockout-negative E2E проходят.

### Этап 5. Реализовать host firewall

Работы:

- установить UFW;
- применить default policies;
- разрешить SSH до enable;
- разрешить только `80/tcp` и `443/tcp` для gateway;
- включить UFW;
- проверить SSH после включения;
- документировать Docker/UFW boundary и обязательность provider firewall.
- выполнить destructive firewall проверки на disposable VM/VPS.

Gate 5:

- [ ] SSH остаётся доступен;
- [ ] разрешены ровно ожидаемые host ports;
- [ ] `443/udp` закрыт;
- [ ] повторный запуск не создаёт дубликаты правил;
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
- убрать Docker installation из `install.sh` на переходном этапе.
- добавить Molecule/pytest-testinfra проверки поддерживаемой части роли и disposable VM/VPS systemd E2E.

Gate 6:

- [ ] Docker устанавливается на каждой поддерживаемой ОС;
- [ ] Docker service enabled и active;
- [ ] Compose v2 доступен;
- [ ] пользователь не входит в `docker` group;
- [ ] повторный запуск не переустанавливает Docker без причины;
- [ ] неизвестная существующая Docker installation не удаляется автоматически.
- [ ] Molecule idempotence и disposable VM/VPS Docker service E2E проходят.

### Этап 7. Перенести Naive Gateway deployment в Ansible

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

- [ ] чистый deploy заканчивается healthy container;
- [ ] повторный deploy не меняет credentials;
- [ ] повторный deploy без source changes не пересоздаёт сервис без причины;
- [ ] неверный Caddyfile блокируется до замены работающего сервиса;
- [ ] прерванный deploy можно безопасно повторить;
- [ ] runtime env имеет `root:root 0600`;
- [ ] `scripts/check-server.sh` проходит.

### Этап 8. Реализовать полный verify и command UX

Работы:

- реализовать `make verify`;
- реализовать `make credentials`;
- собрать aggregator `make provision`;
- обеспечить ясные этапы вывода и итоговый summary;
- разделить read-only и mutating targets;
- исключить credentials из task logs.

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
- [ ] provider firewall документирован как обязательный внешний boundary;
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
