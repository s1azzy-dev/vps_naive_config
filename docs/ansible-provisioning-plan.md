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
- SSH host key VPS в стандартном `known_hosts`.

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
- `.env` загружается Make только по явному whitelist переменных;
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
provisioning/
  ansible.cfg
  requirements.yml
  playbooks/
    preflight.yml
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
  templates/
    ssh-hardening.conf.j2
    gateway.env.j2

scripts/
  check-server.sh
  backup.sh
  rotate-credentials.sh

.env.example
Makefile
```

Допускается небольшой controller-side wrapper для выбора bootstrap/deploy path. Он не должен содержать provisioning-логику: вся изменяющая VPS логика находится в Ansible.

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

1. Проверяет наличие поддерживаемой версии `ansible-playbook`.
2. Проверяет наличие `ssh`, `ssh-keygen`, `make` и Git.
3. Устанавливает закреплённые Ansible collections из `provisioning/requirements.yml` в project-local path.
4. Проверяет версии установленных collections.
5. Не подключается к VPS.

Успешный результат: controller готов выполнять playbooks воспроизводимой версией инструментов.

### 5.3. `make check-config`

Назначение: локальная проверка `.env` без подключения к VPS.

Пошагово:

1. Проверяет существование `.env`.
2. Проверяет заполненность обязательных переменных.
3. Подставляет документированные defaults для необязательных переменных.
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
2. Проверяет наличие и версии Ansible dependencies.
3. Разрешает `VPS_HOST` в IP, если задан hostname.
4. Получает `A`-записи `DOMAIN` и проверяет соответствие адресу VPS.
5. Проверяет `AAAA`: неверная или недоступная IPv6-запись считается блокирующей ошибкой перед deploy.
6. Проверяет доступность SSH-порта.
7. При первом подключении принимает новый host key через `accept-new` и сохраняет его в `known_hosts`.
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

## 6. Последовательный план реализации

### Этап 0. Зафиксировать baseline

Работы:

- сохранить текущую функциональность без рефакторинга;
- зафиксировать этот план;
- записать текущий список поддерживаемых ОС;
- выполнить существующие static и local smoke tests;
- сохранить результаты как baseline.

Gate 0:

- [ ] `make test` проходит;
- [ ] local Caddy smoke проходит;
- [ ] существующие пользовательские изменения сохранены;
- [ ] план принят без открытых архитектурных вопросов.

### Этап 1. Ввести локальный config contract

Работы:

- добавить `.env.example`;
- расширить `.gitignore` для controller/runtime artifacts;
- реализовать `make init`;
- реализовать whitelist загрузки `.env`;
- реализовать `make check-config`;
- обновить `make help`;
- добавить тесты пустых, частичных и некорректных значений.

Gate 1:

- [ ] `make help` работает без `.env`;
- [ ] `make init` не перезаписывает существующий `.env`;
- [ ] пустой обязательный параметр даёт точную ошибку;
- [ ] секреты не печатаются;
- [ ] корректный `.env` заканчивается `Configuration: OK`;
- [ ] VPS не затрагивается.

### Этап 2. Создать Ansible skeleton и quality gate

Работы:

- добавить `ansible.cfg`, `requirements.yml`, playbooks и пустые роли;
- закрепить совместимые версии `ansible-core`, `community.docker` и других реально используемых collections;
- не добавлять collection без используемого модуля;
- реализовать `make tooling`;
- добавить syntax-check, ansible-lint и secret scan;
- исключить secret output через `no_log` и callback settings.

Gate 2:

- [ ] зависимости устанавливаются воспроизводимо;
- [ ] `ansible-playbook --syntax-check` проходит;
- [ ] ansible-lint проходит;
- [ ] playbooks не содержат plaintext passwords/keys;
- [ ] существующие application tests проходят.

### Этап 3. Реализовать read-only preflight

Работы:

- реализовать DNS/IP/AAAA проверки;
- реализовать SSH port и host key проверки;
- реализовать безопасное определение bootstrap/managed режима;
- реализовать `make preflight`;
- обеспечить отсутствие remote changes.

Gate 3:

- [ ] корректный новый VPS определяется как `bootstrap required`;
- [ ] подготовленный VPS определяется как `managed host ready`;
- [ ] неверный DNS блокирует deploy;
- [ ] изменившийся host key блокирует подключение;
- [ ] недоступный VPS завершается понятной ошибкой;
- [ ] preflight не изменяет локальную или удалённую систему, кроме записи нового host key.

### Этап 4. Реализовать user и SSH bootstrap

Работы:

- bootstrap Python/sudo через raw;
- проверка ОС;
- создание `VPS_USER`, пароля, sudo membership и authorized key;
- проверка отдельного managed-user connection;
- применение SSH drop-in через validate-before-reload handler;
- отрицательные root/password login tests;
- повторный запуск без изменения пароля.

Gate 4:

- [ ] новый пользователь входит по ключу;
- [ ] sudo принимает заданный пароль;
- [ ] root SSH login запрещён;
- [ ] password и keyboard-interactive login запрещены;
- [ ] `sshd -t` проходит;
- [ ] повторный bootstrap не меняет пароль и authorized key;
- [ ] искусственно ошибочный SSH template не применяется и не вызывает lockout.

### Этап 5. Реализовать host firewall

Работы:

- установить UFW;
- применить default policies;
- разрешить SSH до enable;
- разрешить только `80/tcp` и `443/tcp` для gateway;
- включить UFW;
- проверить SSH после включения;
- документировать Docker/UFW boundary и обязательность provider firewall.

Gate 5:

- [ ] SSH остаётся доступен;
- [ ] разрешены ровно ожидаемые host ports;
- [ ] `443/udp` закрыт;
- [ ] повторный запуск не создаёт дубликаты правил;
- [ ] внешний port scan после deploy не показывает неожиданных портов.

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

Gate 6:

- [ ] Docker устанавливается на каждой поддерживаемой ОС;
- [ ] Docker service enabled и active;
- [ ] Compose v2 доступен;
- [ ] пользователь не входит в `docker` group;
- [ ] повторный запуск не переустанавливает Docker без причины;
- [ ] неизвестная существующая Docker installation не удаляется автоматически.

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
