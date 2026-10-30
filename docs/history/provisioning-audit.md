# История аудита и упрощения provisioning

Снимок принятого контракта и результатов до упрощения, commit `1094963`.
Ниже исторические формулировки; текущая приёмка и результаты находятся в
[актуальном плане](../ansible-provisioning-plan.md).

Уточнение покрытия: прежняя parametrization env/compose/health/public в pytest
фактически проверяла два состояния, а не четыре независимых отказа. Историческая
запись сохранена; в текущих тестах parametrization отражает эти два состояния.

# План Ansible provisioning и исправлений аудита

Статус: локальная реализация аудита и все локальные gates завершены;
production acceptance ещё не выполнен.
Дата аудита: 2026-10-27. Локальная реализация и проверки: 2026-10-28–29.

## 1. Правила

Выполнять A01–A13 по порядку, проверяя каждое исправление. Архитектурные решения
вносить в план до кода. Сохранять незаконченные пользовательские изменения.
Владелец явно отложил все VPS-gates до финала: VPS пока отсутствует.
Локальные и контейнерные результаты не закрывают эти gates.

## 2. Согласованный MVP

- Целевая среда: **Ubuntu 26.04 LTS, amd64**. Её реальная приёмка ещё впереди.
- **Только IPv4**: matching DOMAIN A, отсутствие DOMAIN AAAA; SSH использует IPv4.
- Один VPS, один Caddy, без provider API/DNS automation.
- Локальный Python 3.14 controller читает приватный `.env`; Make его не экспортирует.
- Ansible управляет пользователем, SSH, UFW, DOCKER-USER, Docker и deployment.
- Постоянный non-root user, один выбранный ключ, пароль только для sudo,
  запрет root/password/keyboard-interactive SSH и членства в Docker group.
- SSH порт не может быть 80 или 443. Gateway публикует только IPv4 TCP 80/443.
- Conditional sshd Match, включая рекурсивные Include, требует явной миграции;
  автоматическая правка произвольной существующей SSH policy запрещена.
- Существующий неуправляемый user отклоняется до изменения групп/ключей.
  Повтор разрешён только с root-owned 0600 ownership marker.

## 3. Конфигурация

`make init` создаёт `.env` с mode 0600. Обязательны VPS_HOST, SSH_PRIVATE_KEY,
DOMAIN, ACME_EMAIL. Полная схема — в `.env.example`. SSH key paths абсолютные;
SSH_PUBLIC_KEY по умолчанию равен SSH_PRIVATE_KEY + `.pub`. Sudo passwords не
хранятся в файле. VPS_BOOTSTRAP_USER может быть root или non-root с sudo:
его существующий пароль передаётся отдельно от пароля managed user через pipe.
Для bootstrap NOPASSWD допускается пустой ответ; managed sudo требует пароль.

GATEWAY_REPOSITORY допускает public HTTPS без userinfo или SSH username/deploy key
без пароля в URL. GATEWAY_REF должен быть опубликован перед deployment.
NAIVE_USER/NAIVE_PASSWORD задаются вместе либо остаются пустыми. Повторный deploy
с пустой парой сохраняет runtime credentials.

## 4. Состояние и восстановление

Root-owned source checkout находится в `/opt/naive-gateway/repository`, immutable
releases — в `releases/<commit>`, принятый release — в `current`. Runtime env:
`/etc/naive-gateway/gateway.env`, root:root 0600. Локальный `.env` не копируется.

До изменений provision разбирает все обязательные playbooks локально, затем
выполняет один исходный preflight. Bootstrap всегда идемпотентно завершает host
roles: готовый SSH сам по себе не доказывает готовность UFW. Отдельный managed
вход и прямой password-backed sudo проверяются до hardening; после него — reconnect.
Verify проверяет эффективные root/managed контексты настоящего SSH-соединения.

Перед активацией сохраняются прежние runtime env/release в приватном
`deployment-recovery`. Ошибка возвращает предыдущий service/env/current; первый
непринятый deploy останавливается, pending credentials сохраняются для retry.
Новый запуск сначала восстанавливает незавершённую транзакцию. Если recovery
не удался, snapshot сохраняется, успех не объявляется. После acceptance snapshot
переходит в `previous-deployment`. Сохраняются текущий/предыдущий release и image;
автоматического prune нет. Не запускать deployment/restore/rotation параллельно.

Backup включает release, runtime env, точный Docker image и оба Caddy volume
с сертификатами. Git config в новые backup не входит. Архив 0600, каталог 0700.
Restore без Git/build/registry разрешён только на подготовленном пустом runtime;
существующие gateway containers/volumes/env не перезаписываются. Host OS, ключи и
firewall восстанавливает тот же Ansible bootstrap; второго установщика нет.

## 5. Команды

| Действие | Команда |
| --- | --- |
| Локальная подготовка | `make init`, заполнить `.env`, `make tooling` |
| Полный цикл | `make provision` |
| Диагностика | `make check-config`, `make preflight`, `make verify` |
| Host / deploy | `make bootstrap`, `make deploy` |
| Credentials без DNS gateway | `make credentials` (только интерактивный терминал) |
| Автономный restore | `make bootstrap`, `make restore BACKUP_FILE=/absolute/backup.tar.gz` |
| Качество | `make lint`, `make test`, `make molecule` |
| VPS runtime | `sudo make -C /opt/naive-gateway/current status/check/logs/validate/backup/rotate-credentials` (одна цель за вызов) |

Подробная эксплуатация: [vps-setup.md](../vps-setup.md).

## 6. Последовательность выполнения

1. A01–A05: достоверные проверки, safe bootstrap/retry.
2. A06–A08: recovery, IPv4 и Git URL boundary.
3. A09–A13: диагностика credentials, tooling, ownership, SSH recovery, backup/restore.
4. Решения 10.3, полный локальный lint/test/Molecule/runtime smoke.
5. Опубликованный ref и финальные VPS-gates на disposable Ubuntu 26.04 amd64.

## 7. Открытые финальные gates (4–11)

- [ ] Fresh provision и second run на Ubuntu 26.04 amd64, без ротации credentials.
- [ ] Настоящий SSH reconnect, sudo и root/password/keyboard-interactive negatives.
- [ ] Эффективные verify-выражения, permissions, source ref и actual published ports.
- [ ] External scan и sentinel 0.0.0.0:18080 недоступен извне при доступных 80/443.
- [ ] UFW reload, Docker restart, systemd ordering и reboot сохраняют policy.
- [ ] Public ACME/TLS/HTTP2, authenticated CONNECT и anonymous rejection.
- [ ] Fault injection после env/up/health/public acceptance и повтор восстановления.
- [ ] Restore автономного backup и обе ветки credential rotation на VPS.
- [ ] Код опубликован, выбран доступный GATEWAY_REF, проверены примеры документации.

## 8. Тестовая инфраструктура

Debian 12 privileged Molecule остаётся локальным fixture для реальных sshd/UFW,
nested Docker, idempotence и негативных сценариев. Это не поддержка Debian в MVP
и не доказательство systemd/reboot/public ingress Ubuntu. Удалять его нельзя до
появления более простой проверки с теми же гарантиями. Runtime smoke отдельно
проверяет настоящий production Caddy с local issuer; pytest покрывает offline
controller, transaction/retry и backup/restore без внешней сети.

## 9. История и сопровождение

Даты, первоначальные решения, этапы 0–11 и прежние результаты сохранены в
[архиве плана](ansible-provisioning-original-design.md).
Порядок обновления pins и ограничения воспроизводимости:
[dependency-updates.md](../dependency-updates.md).

## 10. Аудит и план исправлений

Исходные формулировки и evidence аудита 2026-10-27 сохранены в
[архиве](ansible-provisioning-original-design.md#10-аудит-и-план-исправлений).
Ниже текущий checklist. Отметка реализации означает локальное исправление;
реальная VPS-приёмка явно отделена и отложена владельцем на финал.

### 10.1. Обязательные исправления

#### A01. Ранняя проверка обязательных playbooks

- [x] YAML verify исправлен; bootstrap/deploy/verify/restore проходят настоящий
  syntax check до preflight, password prompt и изменений VPS.
- [x] CLI regression: повреждённый verify, любой обязательный playbook или
  статический import останавливает provision; parser output с секретом скрыт.
- [ ] Проверить выполнение всех verify-выражений на целевом VPS (финальный gate).

#### A02. Анонимный CONNECT и probe resistance

- [x] Сначала выбирается достижимая authenticated цель, затем та же цель
  проверяется без credentials. CONNECT 2xx запрещён; transport/TLS failures
  не считаются доказательством отказа. Сбой всех внешних целей — inconclusive.
- [x] Отказ должен быть наблюдаемым HTTP 3xx/4xx без 407/Proxy-Authenticate/
  forward-proxy disclosure. Настоящий pinned Caddy маскирует отказ через 308.
- [x] Проверен production check-server.sh: closed/open/redirect, TLS/transport,
  disclosure, недоступные цели и fallback; настоящий Caddy runtime smoke прошёл.
- [ ] Внешний HTTPS/CONNECT acceptance на VPS — финальный gate.

#### A03. Эффективная SSH policy

- [x] Shared ssh_policy читает sshd -T -C для root и managed user с actual
  SSH_CONNECTION. Активные Match в главном файле и транзитивных Include
  отклоняются: две выборочные пробы не объявляются доказательством всех адресов.
- [x] Ошибки private key/passphrase/signature/алгоритма классифицируются как
  local_error, даже рядом с Permission denied; они не доказывают root denial.
- [x] Локальные tests и Molecule проверяют Match User root, вложенные Include,
  безопасную глобальную policy и негативную классификацию.
- [ ] Настоящий reconnect/lockout-negative — финальный gate.

#### A04. Non-root bootstrap и sudo

- [x] Bootstrap-user и literal root разделены; sudo passwords bootstrap и
  managed user передаются отдельными переменными через inherited pipe.
- [x] Поддержаны root, non-root password sudo и bootstrap NOPASSWD (empty
  password). Managed password доказывается прямым sudo -S -k true через stdin
  до hardening. NOPASSWD и sudo shell не считаются проверкой пароля.
- [x] Controller scenarios проверяют отдельные passwords/users; Molecule
  выполняет реальный password-backed managed sudo.
- [ ] Все варианты через настоящие SSH-сеансы — финальный gate.

#### A05. Повтор после частичного bootstrap

- [x] Provision всегда идемпотентно применяет host roles, в том числе UFW и
  Docker ingress; готовый SSH не приводит к пропуску firewall.
- [x] Исходный preflight переиспользуется, но новые managed SSH/sudo перед
  hardening и reconnect после него сохранены. Controller regression и
  Molecule idempotence прошли.
- [ ] Прерывание bootstrap и повтор на VPS — финальный gate.

#### A06. Согласованность deployment и recovery

- [x] До env activation сохраняются previous env/release и candidate metadata
  в private durable snapshot. Env writes/current switch атомарны.
- [x] Ошибка activation возвращает прежние env/current/healthy container.
  Первый failed deploy останавливается без удаления pending credentials.
  Interrupted transaction восстанавливается перед новым source/credentials.
- [x] Recovery failure сохраняет прежние секреты и snapshot; успех не заявляется.
  Accepted snapshot сохраняется как previous-deployment; старые данные не prune-ятся.
- [x] Локально проверены env/compose/health/public failure boundaries, повтор из
  нового controller instance, changed domain/credentials, first deploy, failed
  recovery и commit с сохранением предыдущих данных. Molecule проверяет
  настоящую deployment idempotence и invalid candidate/retry.
- [ ] Network fault injection и recovery на VPS — финальный gate.

#### A07. IPv4 и конфликты портов

- [x] Владелец выбрал IPv4-only: DOMAIN AAAA отклоняется до соединений; SSH -4,
  VPS_HOST должен иметь IPv4. Не заявляется IPv6 acceptance.
- [x] VPS_PORT 80/443 отклоняются локально и в firewall role.
- [x] Обновлены config/network tests, .env.example и инструкции; покрыты
  IPv4 literal/hostname и AAAA даже при достижимом IPv6.

#### A08. Credentials внутри Git URL

- [x] Shared repository validator запрещает HTTPS userinfo (включая token-only),
  SSH password и encoded userinfo; сохраняет public HTTPS и SSH deploy-key URLs.
- [x] Проверка применяется controller и непосредственно role до Git invocation;
  URL передаётся validator через stdin, ошибки не печатают секрет.
- [x] Tests допустимых/опасных форм прошли. Новые backup не содержат .git/config;
  старые архивы документированы как секреты с возможными историческими URL.

### 10.2. Дополнительные исправления

#### A09. Credentials без зависимости от DNS gateway

- [x] Полный preflight исключён: strict known host, managed SSH и прямой sudo
  чтения достаточны. Секрет только stdin, вывод только интерактивный.
- [x] Tests запрещают DNS preflight при чтении; SSH/host-key/sudo errors
  блокируют выдачу и не раскрывают captured runtime/error output.

#### A10. Работоспособность tooling binaries

- [x] Проверяется запуск ssh/ssh-keygen/make/git, timeout и exit status;
  неверная архитектура даёт понятную ошибку. Системный PATH/Git не изменяется.
- [x] Regression для найденного, но не запускающегося Git прошёл.
  Локальные gates используют /usr/bin в process PATH из-за сломанного
  /usr/local/bin/git; это осознанный локальный выбор, не скрытый auto-fallback.

#### A11. Existing user adoption

- [x] До изменения групп/ключей проверяется root:root 0600 marker, связанный с
  username. Guard действует и для managed bootstrap/deploy/verify/restore.
- [x] Неуправляемый user отклоняется без стирания access/groups. Legacy/partial
  account без marker требует явной миграции; это описано в recovery guide.
- [x] Molecule подтвердил отказ реального user role и сохранность дополнительной
  группы и существующего authorized_keys. Для управляемого user сохраняются
  один выбранный ключ, отсутствие Docker group и прежний password hash.

#### A12. Полная SSH-конфигурация и rollback

- [x] Standalone candidate validation дополнен немедленным полным sshd -t и
  effective policy до reload. Block/rescue восстанавливает прежние bytes/mode
  либо удаляет первый непринятый drop-in; validate-before-reload сохранён.
- [x] Molecule воспроизвёл реальный composed failure: standalone-valid
  Subsystem конфликтует с основным файлом. Полный check отклонил его,
  прежний drop-in восстановлен и сверён побайтно.
- [ ] Настоящий новый SSH и lockout-negative — финальный gate.

#### A13. Автономный backup и restore

- [x] По решению владельца backup автономный: manifest/commit, release, runtime,
  точный image и certificate/config volumes; Git config исключён.
- [x] make restore использует тот же Ansible host/Docker contract, не второй
  installer. Проверяются archive safety, image identity, DNS domain, пустой
  runtime, health и настоящий check-server. Acceptance prerequisites установлены.
- [x] Локальные tests проверяют image/credentials/certificates, private modes,
  traversal rejection и recovery при failed acceptance, без Git/build/registry.
- [x] В disposable Docker выполнены реальный backup/restore при отключённом
  source Git и удалённом image tag, сохранность сертификатов, успешная rotation,
  принудительный acceptance failure и подтверждение прежних credentials после rollback.
  Rotation и rollback ожидают health до проверки endpoint. Финальный полный
  Molecule со всеми этими сценариями прошёл 2026-10-29.
- [ ] Restore/rotation на VPS — финальный gate; старый VPS/backup сохранить.
- [ ] Перед первым VPS deploy опубликовать code и выбрать доступный GATEWAY_REF.

### 10.3. Минимализм — принятые решения и выполненные изменения

- [x] ОС/архитектура: владелец выбрал Ubuntu 26.04 LTS amd64; production
  allowlist сужен, Debian 12 разрешён только явно отмеченному test fixture.
- [x] IPv6: выбран IPv4-only, ранний отказ при DOMAIN AAAA.
- [x] Один firewall contract: provisioning/vars/docker_ingress.yml используется
  UFW templates, Docker role и verify; UFW и DOCKER-USER сохранены.
- [x] Повторные probes: один DNS/SSH preflight в provision; необходимые новые
  managed/root/auth probes сохранены; credentials не требуют DNS gateway.
- [x] Тестовая инфраструктура пересмотрена: nested Docker/Molecule сохранён
  до равнозначной замены; его граница с Caddy smoke/VPS E2E описана явно.
- [x] План сокращён: текущий MVP, команды, дефекты и gates здесь; прежние
  этапы/даты/решения/evidence перенесены в историю без удаления.
- [x] Releases: сохранять current и previous successful image/release; автоматический
  prune выключен. Старые snapshots/backup/recovery не удаляются до приёмки.
- [x] Controller: Python/Ansible boundary сохранена; объединены policy validators,
  firewall contract и preflight reuse, без замены typed config/secret pipe UX.
- [x] Pins: описан отдельный reviewed update workflow с full local/VPS gates.
  Tag-based base images и незакреплённый apt не названы bit-reproducible;
  актуальность/CVE не объявлены проверенными.

### 10.4. Evidence и оставшиеся gates

- Полный lint (Ruff/format, mypy strict, production ansible-lint/syntax,
  bash syntax и обязательный ShellCheck): PASS, 0 failures/warnings.
- Полный pytest: PASS, **139 tests**.
- Точечный Ansible audit play на реальном disposable instance: PASS,
  37 tasks, 0 failed; включает scoped NOPASSWD shell + wrong-password rejection,
  SSH Match/composed rollback и сохранение unowned account groups/keys.
- Финальный полный Molecule 2026-10-29: PASS — все 8 действий,
  0 failures, converge/idempotence/side_effect/testinfra/destroy, включая реальный
  автономный backup/restore без source Git/image registry и обе ветки rotation.
  Disposable instance удалён; отдельные точечные сценарии также прошли.
- При интеграции обнаружены и исправлены Python 3.11.2 tar API compatibility
  и readiness wait в rotation. Watchdog nested daemon увеличен с 30 минут до
  2 часов для локальной диагностики; обычный destroy и CI timeout сохранены.
- Настоящий pinned Caddy runtime smoke прошёл TLS/HTTP2/site, authenticated
  CONNECT и anonymous camouflage rejection HTTP 308, log suppression.
- Независимый candidate review нашёл два дефекта: missing curl при restore и
  shell-based sudo password proof; оба исправлены (prerequisites + direct sudo stdin).
- Gate 4–11 и весь checklist раздела 7 остаются открытыми: Ubuntu VPS нет,
  owner отложил SSH/firewall/reboot/public ACME/restore/rotation E2E на финал.
  Full hosted CI не запускался; platform/CVE/production readiness не заявляются.

Команды финального локального gate: `make lint` с REQUIRE_SHELLCHECK=1,
`make test`, `make molecule`, `./tests/smoke-local.sh`, `git diff --check`.
На этом controller использован process PATH с `/usr/bin` перед `/usr/local/bin`
(A10), а для Molecule — явный DOCKER_HOST сокета OrbStack. Системные настройки
PATH/Git не менялись; реальные VPS credentials/configuration не использовались.

## 11. Чеклист упрощения и учебной документации

Дата: 2026-10-29. Основание: аудит простоты, понятности и достаточности тестов.
Все 70 пунктов выполнены локально. Разделы 1–10 выше сохраняют прежние
решения, результаты и незакрытую VPS-приёмку; её пункты не закрываются этим checklist.

### 11.1. Границы изменений

- [x] Зафиксировать назначение: личный gateway для одного владельца, одного VPS
  и одного Caddy; Ubuntu 26.04 LTS amd64, IPv4, controller Python 3.14.
- [x] Сохранить разделение ответственности: Make запускает команды, Python
  читает конфигурацию и организует запуск, Ansible меняет сервер, Compose запускает Caddy.
- [x] Сохранить необходимые гарантии: проверку managed SSH/sudo до hardening,
  host keys, UFW и Docker ingress, приватные секреты и передачу sudo password
  через pipe, validate-before-activation, rollback/retry, автономный backup/restore.
- [x] Не добавлять платформы, миграцию чужих установок, второй installer,
  универсальный framework, новые слои конфигурации и автоматический prune.
- [x] Перед каждым удалением отличать повтор проверки от проверки другого
  состояния: candidate config, фактически работающий сервис и восстановление
  после сбоя могут требовать разных проверок. Спорный механизм удалять только
  при сохранении его полезного поведения; иначе кратко объяснить его назначение.

### 11.2. README как последовательное учебное руководство

- [x] Кратко объяснить Naive Gateway: что работает на VPS, зачем нужен Caddy
  с forwardproxy и какую роль играет обычный сайт; клиентская установка вне проекта.
- [x] Добавить одну схему: компьютер владельца → SSH/Ansible → VPS → Docker/Caddy;
  показать публичные SSH TCP, 80/tcp и 443/tcp без UDP/443.
- [x] Объяснить необходимые термины при первом использовании: controller,
  inventory, playbook, role, task, handler, идемпотентность, release и rollback.
  Не пересказывать общий учебник Ansible.
- [x] Описать подготовку: инструменты на компьютере, получение checkout,
  SSH-ключ и проверка fingerprint, чистый VPS, домен/DNS A без AAAA,
  разрешённые порты и исходный SSH-доступ.
- [x] Дать полную таблицу всех полей `.env.example`: назначение, обязательность,
  значение по умолчанию и безопасный пример. Объяснить абсолютные пути к ключам,
  пару NAIVE_USER/NAIVE_PASSWORD и отличие локального `.env` от серверного runtime env.
- [x] Для `make init`, заполнения `.env`, `make tooling` и `make provision`
  описать: где запускать, что вызывается, что меняется, зачем, признак успеха.
- [x] Показать фактический порядок `provision`: проверка конфигурации и синтаксиса,
  DNS/SSH preflight, пароли, bootstrap, deploy, verify, вывод credentials.
  Уточнить, что host roles применяются и при уже готовом managed SSH.
- [x] Раскрыть bootstrap по шагам: prerequisites, создание пользователя/ключа,
  ownership, новый managed SSH/sudo, SSH hardening, firewall, reconnect.
  Объяснить root/non-root bootstrap и назначение двух sudo passwords без ветвистых инструкций.
- [x] Раскрыть deploy по шагам: Docker, опубликованный source ref, snapshot release,
  credentials, Compose/Caddy validation, activation/health, HTTPS/proxy acceptance,
  переключение current; показать, что происходит при ошибке и повторе.
- [x] Показать назначение каталогов repository/releases/current, runtime env,
  pending credentials, recovery/previous/history, Docker volumes и backup.
  Отдельно пояснить, какие данные содержат секреты.
- [x] Добавить таблицу отдельных controller-команд и серверных команд Make:
  место запуска, назначение, изменения состояния и ожидаемый результат.
  Объяснить отличие `check-config`, `preflight`, `verify`, `check` и `validate`.
- [x] Описать штатное обновление, получение/rotation credentials и работу с backup;
  дать ссылки на полные процедуры восстановления и диагностики.
- [x] Ясно обозначить ограничения: опубликованный GATEWAY_REF, доступ VPS к source,
  отсутствие копирования локальных незакоммиченных изменений, запрет параллельных
  deploy/restore/backup/rotation и сохранение исходного SSH-сеанса до reconnect.

### 11.3. Документация без повторов и истории в рабочем маршруте

- [x] Сделать README основным маршрутом установки и сопровождения;
  `docs/vps-setup.md` оставить для подробного recovery и диагностики,
  `provisioning/README.md` — для устройства Ansible и интеграционных тестов.
- [x] Убрать повторяющиеся инструкции, заменить их точными ссылками; сохранить
  полноту процедур non-root bootstrap, partial failure, credentials rotation,
  backup transfer и автономного restore на пустом runtime.
- [x] Обновить `docs/dependency-updates.md` под итоговый порядок обновления pins.
- [x] Перенести закрытую историю A01–A13 и прежние архитектурные альтернативы
  в историю с сохранением evidence. В актуальном плане оставить краткие принятые
  решения, активный checklist и единый список незакрытых приёмочных проверок.
- [x] Убрать фазовые Gate 4–11 и Axx из действующих инструкций/комментариев,
  заменить на названия проверяемого поведения. Проверить входящие ссылки и anchors;
  исторические ссылки должны вести на архив, а не теряться.
- [x] Устаревшие security proposals оставить справочной историей, не включать
  альтернативные схемы в основной учебный маршрут и не удалять прежние выводы аудита.

### 11.4. Семантические названия вместо фаз

- [x] Переименовать Molecule-тесты `test_phase4.py`–`test_phase7.py` в
  `test_bootstrap.py`, `test_firewall.py`, `test_docker.py`, `test_deployment.py`.
- [x] Переименовать `phase7.yml` в `deployment.yml`, обновить imports и ссылки.
- [x] Переименовать fixture host `phase5-debian12`, каталоги `.molecule-phase4`,
  `phase7-source`, image archives, register-переменные и test markers по назначению.
- [x] Обновить имена pytest-функций, task headings, фиктивные SSH-key comments,
  тестовые HTML markers и сообщение tooling о «current phase».
- [x] Выполнить согласованное переименование всех references без изменения
  сценариев тестирования; старые реальные runtime paths при этом не менять.
- [x] Проверить поиск `phase`, `фаза` и нумерованных development gates в активном
  коде, CI, тестах и документации. Не считать совпадения внутри digest фазовыми хвостами.

### 11.5. Мёртвый код и избыточная настраиваемость

- [x] Удалить `BootstrapOutcome.SKIPPED`, недостижимую CLI-ветку и тест,
  который искусственно возвращает этот результат. Если enum больше не нужен,
  удалить его целиком; успешный bootstrap сообщает об успешно выполненном согласовании.
- [x] Удалить `unreachable_domain_ipv6` и недостижимое вычисление из network report,
  убрать это поле из fixtures/tests. Сохранить ранний отказ при DOMAIN AAAA.
- [x] Проверить оставшиеся поля/ветки IPv6; оставить необходимую проверку запрета
  и firewall boundary, не обслуживать неиспользуемый dual-stack workflow.
- [x] Зафиксировать `/opt/naive-gateway` и `/etc/naive-gateway` как пути личного
  deployment. Убрать из роли видимость поддержки альтернативных путей, которую
  verify/restore playbooks сейчас не обеспечивают; согласовать defaults/specs/call sites.
  Внутренние аргументы путей для изолированных тестов не объявлять пользовательским API.
- [x] Пересмотреть прочие параметры: оставить настройки владельца и необходимые
  test fixture hooks; не превращать константы в настройки ради переиспользования ролей.

### 11.6. Verify проверяет установленный gateway

- [x] Удалить из `verify.yml` `git ls-remote` и требование соответствовать
  текущей вершине удалённой ветки. Новый commit в main не делает установленный release неисправным.
- [x] Убрать обязательное наличие source checkout/origin на VPS для verify:
  автономно восстановленный gateway должен проверяться той же командой.
- [x] Брать commit установленного release из `.release-complete`; проверять формат,
  соответствие каталогу/current, конфигурации release и фактически запущенному образу.
- [x] При явно заданном GATEWAY_REF как commit сохранить проверку соответствия
  установленному commit; branch/tag разрешать в deployment, не через сеть в verify.
- [x] Сохранить проверки SSH/sudo, ownership/permissions, UFW/Docker ingress,
  настроек runtime, реальных published ports, health и публичного HTTPS/CONNECT.
- [x] Не считать release marker доказательством происхождения исходников;
  получение нужного repository/ref и проверка разрешённого commit остаются в deploy.
- [x] Проверить поведение при недоступном origin, продвинувшемся main и отсутствии
  checkout после restore; неверный marker/image/явный commit должны давать отказ.
- [x] Обновить controller variables, restore-инструкции и сообщения; убрать
  прежнее указание сначала выполнять deploy ради полноценного verify после restore.

### 11.7. Достаточные проверки и источники версий

- [x] Удалить повторную GPG fingerprint-проверку Docker signing key после
  проверки точного SHA-256; убрать связанный параметр, argument spec и assertions.
  Сохранить checksum и привязку apt repository через signed_by.
- [x] Удалить установку gnupg, если после предыдущего пункта у неё нет другого
  потребителя в проекте; не менять остальные apt prerequisites без основания.
- [x] Убрать вручную дублируемый EXPECTED_VERSIONS для Python dependencies;
  использовать `pyproject.toml`/`uv.lock` как декларацию и lock. Сохранить понятную
  диагностику отсутствующих/несогласованных инструментов и неработающих executable.
- [x] Оставить `provisioning/requirements.yml` источником collection pins;
  убрать копию точного списка версий из тестов, сохранить проверку установки.
- [x] Сделать `versions.env` источником Caddy/forwardproxy versions для build,
  Compose и runtime smoke; убрать ненужные literal defaults, включая SMOKE_IMAGE.
  Сохранить возможность явно выбрать тестовый image.
- [x] Согласовать bootstrap uv в Makefile, pyproject и CI. Не создавать отдельный
  генератор или конфигурационный слой ради устранения короткого необходимого повтора.
- [x] Пересмотреть повторяющиеся asserts в controller/roles/verify: удалить
  проверки собственных констант и одинаковые проверки в одной границе выполнения.
  Сохранить полезную защиту перед remote mutation, проверку кандидата и реального
  состояния. Для оставленного повтора должно быть понятно, какой иной сбой он ловит.

### 11.8. Тесты проверяют поведение и реальные отказы

- [x] Удалить тесты отсутствия давно удалённых install/update/controller-файлов.
- [x] Убрать assertions точных task names, short_description, старых digest/version
  literals и точной структуры CI: числа jobs, их имён, runner, текста steps и cache lines.
  Не удалять вместе с ними полезные проверки секретов, source validation и publications.
  В негативных интеграционных сценариях сохранить доказательство нужной причины
  отказа и отсутствия mutations; не считать произвольный failure успехом теста.
- [x] Удалить повторный shell syntax/ShellCheck запуск из pytest, оставить его
  в `make lint`. Реальную проверку syntax-before-SSH и отказа до mutations сохранить.
- [x] Исправить parametrization env/compose/health/public в `test_runtime_state.py`:
  оставить действительно различные состояния; не выдавать одинаковые mocked-вызовы
  за четыре разных отказа. Согласовать формулировки evidence в плане с реальным покрытием.
- [x] Сохранить минимальную матрицу поведения: config/secret redaction, pipe/stdin,
  SSH error classification, safe bootstrap/retry, credentials preservation,
  deployment rollback/failed recovery, backup/restore и archive safety.
- [x] Сохранить настоящий Caddy smoke для site/TLS/HTTP2, authenticated CONNECT,
  anonymous rejection и log suppression; реальные role tests — в Molecule.
- [x] Проверить пересечения pytest/Molecule/smoke. Убирать одинаковые сценарии,
  но сохранять различие между unit-моделью и настоящим сервисом. Не задавать
  искусственную цель по количеству тестов/проценту сокращения.
- [x] Новые regression tests писать только для изменившегося существенного
  поведения, прежде всего verify. Для переименований и текста отдельные тесты не нужны.

### 11.9. Прямолинейный workflow и достаточная CI

- [x] Согласовать `make help`, CLI messages и README с фактическими действиями:
  первая установка, повторный provision, update, verify и recovery должны иметь ясный маршрут.
- [x] Сохранить отдельные команды для диагностики, но не требовать ручного
  выполнения всех промежуточных команд для обычной установки.
- [x] Проверить повтор setup/build/test в CI и Molecule; убрать только повтор,
  который не покрывает другую границу. Не объединять jobs и не вводить reusable
  workflows ради самого рефакторинга; не терять Caddy smoke и role integration.
- [x] Сохранить Debian nested Docker как test fixture и его необходимые switches;
  не менять тестовую платформу в рамках косметического упрощения и не расширять
  production support. Ясно описать, что он не доказывает Ubuntu boot/reboot/внешний ingress.

### 11.10. Порядок работы и проверка результата

Выполнять небольшими проверяемыми изменениями без повторного деления продукта
на «фазы». Документацию окончательно сверять с уже изменённым кодом.

1. Уточнить контракт и структуру руководства (11.1–11.3); сохранить прежнюю историю.
2. Согласованно переименовать фазовые артефакты (11.4).
3. Удалить мёртвый код/ложные настройки и упростить verify (11.5–11.6).
4. Убрать дубли проверок/pins/тестов и проверить workflow (11.7–11.9).
5. Завершить README и связанные инструкции, затем выполнить итоговую проверку.

- [x] Перед кодом проверить рабочее дерево, обновить main и создать отдельную
  ветку упрощения, сохранив этот согласованный checklist и чужие изменения.
- [x] После каждого изменения запускать относящиеся к нему проверки; полный
  набор повторять после сборки итогового изменения, а не после каждой правки текста.
- [x] Выполнить `REQUIRE_SHELLCHECK=1 make lint`, `make test`, полный `make molecule`,
  runtime smoke на собранном актуальном image и `git diff --check`.
- [x] Проверить Markdown-ссылки/anchors и согласованность команд, defaults,
  путей, схемы и описаний ошибок с кодом. Убедиться, что секреты не попали в примеры.
- [x] Убедиться, что актуальные код/тесты/инструкции не требуют знания development
  phases, Axx или истории аудита; архивная история при этом сохранена.
- [x] Проверить учебный маршрут с точки зрения новичка: для каждого шага ясны
  место запуска, входные данные, действие, причина, результат и действие при отказе.
- [x] Зафиксировать итоговый diff, удалённые механизмы, сохранённые гарантии и
  реально выполненные проверки; не объявлять сокращение строк самостоятельным результатом.
- [x] Оставить незакрытой реальную VPS-приёмку до её выполнения. Не выдавать
  результаты предыдущего commit или локальных контейнеров за свежую hosted CI/VPS-проверку.

Связь с требованиями владельца: простота и отсутствие мнимых защит — 11.1,
11.5–11.7; прямолинейность — 11.5–11.6 и 11.9; наглядность и обучение — 11.2–11.3;
отсутствие фазовых хвостов — 11.3–11.4; достаточность тестов — 11.8;
не делать лишнего и личное использование — 11.1, 11.5, 11.7 и 11.9.


## Результаты локального упрощения

- Ветка `codex/simplify-gateway` создана после fetch; main уже совпадал с origin/main.
  Исходный пользовательский checklist сохранён, остальные файлы до изменений были чистыми.
- Полный lint с REQUIRE_SHELLCHECK=1: PASS, production ansible-lint — 0 failures/warnings,
  Ruff/format, mypy strict, shell syntax/ShellCheck пройдены.
- Pytest: **137 passed**, 20.57 s; включает 8 настоящих scoped Ansible release checks
  с временными файлами и Docker/Git заглушками. Это не полный host verify на Ubuntu.
- Полный Molecule: PASS; converge, idempotence (97 ok, 0 changed), side_effect,
  **21 testinfra passed**, destroy. Проверены реальный Caddy deployment, invalid
  candidate/retry, SSH rollback/Match, unmanaged account/UFW/Docker refusal,
  firewall persistence, автономный backup/restore и successful/failed rotation.
  Disposable gateway-debian12 удалён.
- Caddy runtime smoke: PASS на обычном version-tag image и на свежем
  naive-gateway-molecule-caddy из текущего Dockerfile через SMOKE_IMAGE.
- Сверены все 12 полей конфигурации, локальные ссылки/anchors, команды и paths;
  активные source/tests/инструкции больше не содержат development phase references.
- Неиспользуемый daemon template заменён обычным JSON file; dockerd --validate
  и проверки фактического daemon/ingress сохранены. Docker signing key по-прежнему
  проверяется по SHA-256, apt использует signed_by. Python pins читаются из pyproject;
  bootstrap uv в Makefile/CI оставлен без дополнительной системы конфигурации.
- Исправлены false positives негативных Molecule-сценариев: synthetic «unexpectedly
  passed» или посторонняя ошибка не выдаётся за ожидаемый отказ. Общий SSH parser
  сообщает причину в stderr; assertions проверяют её и сохранность конфигурации.
- Старые claims о четырёх env/compose/health/public failure tests уточнены в начале
  архива: unit tests проверяют два разных состояния, реальные отказы — в integration.
- Production/VPS и hosted CI не запускались. Весь список реальной приёмки остаётся
  открытым в актуальном плане. Commit/push/PR в этот запуск не выполнялись.
