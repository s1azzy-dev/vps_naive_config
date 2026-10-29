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

Подробная эксплуатация: [vps-setup.md](vps-setup.md).

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
[архиве плана](history/ansible-provisioning-original-design.md).
Порядок обновления pins и ограничения воспроизводимости:
[dependency-updates.md](dependency-updates.md).

## 10. Аудит и план исправлений

Исходные формулировки и evidence аудита 2026-10-27 сохранены в
[архиве](history/ansible-provisioning-original-design.md#10-аудит-и-план-исправлений).
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
