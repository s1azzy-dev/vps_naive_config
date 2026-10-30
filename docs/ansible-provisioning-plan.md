# Состояние проекта и приёмка

2026-10-29. Ветка: `codex/simplify-gateway`. Все 70 пунктов
локального упрощения выполнены: lint, 137 pytest tests, полный Molecule
(21 testinfra test) и Caddy smoke прошли. Реальная приёмка Ubuntu VPS ещё не выполнена.

## Принятый контракт

- Личный gateway: один VPS, один Caddy, Ubuntu 26.04 LTS amd64, IPv4;
  matching DOMAIN A без AAAA. SSH-порт уже настроен, не 80/443.
- Make запускает команды; Python 3.14 на компьютере читает приватный `.env`,
  проверяет входы и организует запуск; Ansible меняет сервер; Compose запускает Caddy.
- Постоянный non-root user с одним ключом, password-backed sudo, без Docker group.
  Managed SSH/sudo проверяются до запрета root/password/keyboard-interactive SSH.
- UFW защищает host, DOCKER-USER — Docker ingress; только SSH TCP и TCP 80/443.
  Правила обеих address families сохраняются, несмотря на IPv4-only endpoint.
- Секреты не коммитятся и не печатаются в diagnostic logs; sudo password идёт
  через pipe/stdin. Runtime env хранится root:root 0600, credentials сохраняются при retry.
- Deployment проверяет source ref, Compose и Caddy до активации; отдельный release
  сохраняет active bind mounts. Rollback/retry восстанавливает env/current/container.
- Verify сверяет установленный marker/current/image, runtime и реальный сервис
  без Git checkout/origin. Явный commit в GATEWAY_REF должен совпадать с установленным.
- Backup автономный: release, env, точный image, certificate/config volumes;
  архив 0600, каталог 0700, без Git config. Restore — на подготовленный пустой runtime.
- Пути `/opt/naive-gateway` и `/etc/naive-gateway` фиксированы. Автоматической
  миграции чужих user/Docker/UFW/SSH Match, второго installer и автоматического prune нет.
  Deploy/restore/backup/rotation выполняются последовательно.

## Чеклист локальных изменений

- [x] README объясняет схему, все 12 полей, команды, последовательность и результат.
- [x] Recovery, Ansible internals и обновление зависимостей вынесены в профильные документы без повторной инструкции установки.
- [x] Тестовые артефакты именуются по назначению; прежние решения и evidence сохранены в истории.
- [x] Удалены мёртвые bootstrap/IPv6 ветки, неработающие настройки путей и неиспользуемые SSH handlers.
- [x] Verify проверяет установленный gateway без source Git; восемь реальных scoped Ansible regression scenarios прошли.
- [x] Удалены дубли key fingerprint/pins, daemon template и проверки структуры репозитория; сохранены полезные границы проверок.
- [x] Исправлены формальная parametrization recovery и ложноположительные негативные Molecule-сценарии.
- [x] Lint с обязательным ShellCheck, pytest и собранный актуальный Caddy smoke прошли.
- [x] Полный Molecule завершён успешно, disposable instance удалён.
- [x] Итоговая сверка документации, diff и полного checklist завершена.

Полный [checklist из 70 пунктов](history/provisioning-audit.md#11-чеклист-упрощения-и-учебной-документации)
сохранён с исходным аудитом и [результатами проверок](history/provisioning-audit.md#результаты-локального-упрощения).
Все его пункты отмечены; незакрытая VPS-приёмка перечислена ниже.

## Почему оставлены отдельные проверки

Проверка кандидата до замены сервиса, проверка реально запущенных ports/image
и восстановление после прерывания охватывают разные сбои. Их объединение в одну
проверку уменьшило бы гарантии. Ownership markers предотвращают стирание чужих
ключей/групп и firewall state; они не заменяются автоматической миграцией.

Debian nested Docker/Molecule проверяет реальные sshd/UFW/Docker роли и recovery;
Caddy smoke отдельно проверяет production runtime с local issuer; pytest — controller
и изолированные отказы. Замена fixture платформы и объединение CI jobs не нужны
для этого упрощения. Короткий повтор bootstrap uv в Makefile/CI оставлен: эти
entry points работают до установки Python environment. Остальные direct Python
pins читаются из pyproject/lock, collections — requirements.yml, Caddy — versions.env.

## Открытая приёмка на disposable Ubuntu VPS

Эти пункты сохранены открытыми; локальные и контейнерные результаты их не закрывают.

- [ ] Fresh provision и second run на Ubuntu 26.04 amd64, без ротации credentials.
- [ ] Настоящий SSH reconnect, sudo и root/password/keyboard-interactive negatives.
- [ ] Эффективные verify-выражения, permissions, installed commit и actual published ports.
- [ ] External scan и sentinel 0.0.0.0:18080 недоступен извне при доступных 80/443.
- [ ] UFW reload, Docker restart, systemd ordering и reboot сохраняют policy.
- [ ] Public ACME/TLS/HTTP2, authenticated CONNECT и anonymous rejection.
- [ ] Fault injection после env/up/health/public acceptance и повтор восстановления.
- [ ] Restore автономного backup и обе ветки credential rotation на VPS.
- [ ] Код опубликован, выбран доступный GATEWAY_REF, проверены примеры документации.

## Навигация и история

- [README](../README.md) — установка, конфигурация, схема и обычное сопровождение.
- [Recovery](vps-setup.md) — backup transfer, restore и диагностика отказов.
- [Provisioning](../provisioning/README.md) — роли, тесты и CI.
- [Зависимости](dependency-updates.md) — порядок обновления pins.
- [Аудит и полный checklist](history/provisioning-audit.md) — предыдущие выводы, результаты и проверяемые изменения.
- [Первоначальный дизайн](history/ansible-provisioning-original-design.md) — ранняя история проекта.
- [История Docker ingress](security/docker-ingress-hardening/hardening.md) — рассмотренные альтернативы; рабочая схема использует native DOCKER-USER.
