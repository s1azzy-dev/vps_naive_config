# Подготовка и сопровождение VPS

## Предварительные условия

- Чистый Ubuntu 22.04/24.04/26.04 или Debian 12/13, архитектура x86_64 либо arm64.
- Bootstrap SSH-доступ по ключу, домен с `A`-записью на публичный IPv4 и
  корректная доступная `AAAA`, если она существует.
- Входящий SSH-порт и `80/tcp`, `443/tcp`; `443/udp` не требуется.
- Локальные Python 3.14, Git, Make, OpenSSH и доступ к исходному репозиторию.

Публичный ключ добавляется VPS-провайдером при создании сервера. Приватный ключ
остаётся на controller. Если используется firewall провайдера, разрешите те же
входящие TCP-порты. Обязательная защита host и Docker ingress настраивается
Ansible через UFW и `DOCKER-USER`.

## Первое развёртывание

```bash
make init
# Заполните .env вручную: VPS_HOST, SSH_PRIVATE_KEY, DOMAIN, ACME_EMAIL.
make tooling
make provision
```

В `.env` указывайте абсолютный путь к приватному ключу. `SSH_PUBLIC_KEY` по
умолчанию равен пути приватного ключа с добавленным `.pub`. Пароль sudo не
хранится в `.env`: новый пароль запрашивается дважды, существующий — один раз.
Все значения передаются через `.env`, без `HOST=...` и других CLI-параметров.

`GATEWAY_REPOSITORY` должен быть доступен root на VPS, а `GATEWAY_REF` должен
ссылаться на опубликованный commit или ветку этой версии. Controller не копирует
рабочее дерево на VPS. При первом запуске новый SSH host key записывается в
`provisioning/known_hosts`; изменившийся известный ключ отклоняется. Проверьте
его fingerprint по независимому каналу до первого подключения.

Bootstrap создаёт пользователя, проверяет отдельный вход и sudo до изменения
sshd, валидирует конфигурацию SSH и затем настраивает UFW. Не закрывайте
существующую bootstrap-сессию до проверки нового подключения. Пользователь не
добавляется в группу `docker`. Операционная приёмка этого процесса на disposable
VPS ещё не проведена.

## Отдельные команды

```bash
make check-config
make preflight
make bootstrap
make deploy
make verify
make credentials
```

`verify` выполняет read-only проверки конфигурации SSH, firewall, Docker,
release и работающего HTTPS/proxy. `credentials` выводит секреты только в
интерактивный терминал. `make deploy` обновляет проверенный ref; повторный
deploy сохраняет credentials, если оба поля credentials в `.env` пусты. Явная
пара из `.env` применяется при каждом deploy. После ротации обновите или очистите
оба поля на controller, иначе следующий deploy снова применит старую пару.

На VPS команды запускаются через sudo из принятого release:

```bash
sudo make -C /opt/naive-gateway/current status
sudo make -C /opt/naive-gateway/current check
sudo make -C /opt/naive-gateway/current logs
sudo make -C /opt/naive-gateway/current validate
sudo make -C /opt/naive-gateway/current backup
sudo make -C /opt/naive-gateway/current rotate-credentials
sudo make -C /opt/naive-gateway/current restart
```

Архив в `/var/backups/naive-gateway/` содержит runtime env с секретами, commit,
Git-конфигурацию источника и файлы активного release. Git URL также может
содержать данные доступа. Доступ к каталогу — `0700`, к архиву — `0600`.
Передайте архив в защищённое хранилище отдельно от VPS. Docker volumes с ACME
сертификатами не входят в архив: новый сервер получит сертификат после
настройки DNS и доступности портов.

## Восстановление и диагностика

Для переноса подготовьте новый VPS и controller `.env`. Из защищённого архива
возьмите `NAIVE_USER` и `NAIVE_PASSWORD` из `gateway.env` и укажите оба в новом
`.env`; значение `.release-complete` можно использовать как `GATEWAY_REF`, а
origin URL в `.git/config` — как `GATEWAY_REPOSITORY`.
Например, извлеките эти файлы в приватный временный каталог на controller:

```bash
umask 077
restore_dir=$(mktemp -d)
tar -xzf /absolute/path/to/backup.tar.gz -C "$restore_dir" gateway.env .release-complete .git/config
```

Откройте файлы в редакторе, перенесите нужные значения в `.env` и после этого
удалите временную копию с секретами. Не добавляйте её в Git.

Укажите новый `VPS_HOST`, при необходимости обновите DNS, затем выполните
`make provision`. Старый VPS сохраняйте до проверки нового. При переносе DNS
публичный сертификат нового VPS не появится до разрешения домена на новый адрес.

После ошибки bootstrap сохраните существующее SSH-подключение, восстановите
доступ через консоль провайдера и повторите `make bootstrap`. Не отключайте
root/password access вручную до проверки нового SSH-входа и sudo.
После ошибки deploy исправьте указанную причину и повторите `make deploy`;
подготовленные credentials сохраняются. Автоматический rollback всего release
не предусмотрен. Ротация credentials восстанавливает прежний runtime env при
ошибке запуска или проверки Caddy; если перезапуск после rollback не удался,
проверьте `status` и `logs` на VPS. После аварийного завершения процесса могут
остаться root-only файлы `gateway.env.rotate.*`: сохраните их до восстановления
доступа и удалите после проверки актуальной пары credentials.

Если `make verify` завершился с ошибкой, используйте название неуспешного слоя,
`make preflight` и серверные `status`/`logs`. Проверьте DNS и доступность портов;
изменившийся host key требует отдельного подтверждения у провайдера.

Реальные reconnect/lockout-negative, external port scan, systemd/reboot, restore
и fresh/second-run сценарии для всех поддерживаемых ОС остаются открытыми до
приёмки на disposable VM/VPS; результаты в контейнере не заменяют эту приёмку.
