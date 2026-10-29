# Подготовка и сопровождение VPS

## Предварительные условия

Целевой MVP — чистый **Ubuntu 26.04 LTS amd64**. Его реальная приёмка пока не
выполнена. Нужны bootstrap SSH по ключу, matching DOMAIN A и отсутствие DOMAIN
AAAA. SSH использует IPv4; его порт не может быть 80/443. Снаружи разрешены
выбранный SSH TCP port, 80/tcp, 443/tcp. 443/udp не публикуется.

На controller нужны Python 3.14, Git, Make, OpenSSH и локальный checkout.
Provider firewall опционален: Ansible сам настраивает UFW и Docker ingress.

## Установка и обновление

```bash
make init
# Заполнить .env: VPS_HOST, SSH_PRIVATE_KEY, DOMAIN, ACME_EMAIL.
make tooling
make provision
```

Ключи задаются абсолютными путями. SSH_PUBLIC_KEY по умолчанию равен
SSH_PRIVATE_KEY + `.pub`. `.env` имеет mode 0600 и не копируется на VPS.
GATEWAY_REF должен быть опубликован до deploy: рабочее дерево controller не
передаётся на VPS. Private Git доступен root через SSH deploy key; HTTPS URL
с userinfo (включая token-only username) и SSH URL с password запрещены. Старые backup с Git
config следует считать содержащими credentials и хранить как секреты.

Bootstrap может подключаться root либо non-root. Для non-root его существующий
sudo password запрашивается отдельно (пустой только для bootstrap NOPASSWD).
Новый managed password подтверждается дважды. Он проверяется прямым sudo через
stdin после нового managed SSH, до изменения root/password доступа. Managed
NOPASSWD не считается доказательством правильного пароля. Сохраняйте исходную
сессию до проверки нового подключения.

Conditional sshd Match, включая вложенные Include, отклоняется без автоматической
миграции. Неуправляемый существующий user также отклоняется: другие ключи/группы
не удаляются. Не создавайте ownership marker вручную ради обхода ошибки. Сначала
проверьте пользователя, аварийный доступ и backup и отдельно согласуйте миграцию.
Для новых hosts проще выбрать новое имя VPS_USER. После прерывания между созданием
account и marker также требуется такая проверка; повтор не присваивает user молча.

Provision проверяет syntax всех обязательных playbooks до SSH, затем повторно
применяет host roles даже при готовом managed SSH. Самостоятельные команды:

```bash
make check-config
make preflight
make bootstrap
make deploy
make verify
make credentials
```

Credentials читаются только через managed SSH/sudo с известным host key и
выводятся только в интерактивный терминал. Исправный DNS gateway не требуется.
Preflight/deploy/verify требуют корректный DOMAIN DNS. Новые SSH host keys
запоминаются через accept-new; изменившийся ключ не принимается автоматически.
Проверьте первый fingerprint по независимому каналу.

При пустой паре NAIVE_USER/NAIVE_PASSWORD deploy сохраняет runtime credentials;
явная пара применяется при каждом deploy. После rotation очистите или обновите
оба значения на controller, иначе следующий deploy применит старую пару.

## Серверные операции

```bash
sudo make -C /opt/naive-gateway/current status
sudo make -C /opt/naive-gateway/current check
sudo make -C /opt/naive-gateway/current logs
sudo make -C /opt/naive-gateway/current validate
sudo make -C /opt/naive-gateway/current backup
sudo make -C /opt/naive-gateway/current rotate-credentials
```

Не выполняйте deploy, restore, backup и rotation параллельно. Backup имеет mode
0600 в каталоге `/var/backups/naive-gateway/` с mode 0700. Он содержит runtime env,
файлы release, точный image и оба Caddy volumes с certificate private keys. Git
config в новые backup не входит. Отдельно перенесите архив в защищённое хранилище.

## Автономное восстановление без исходного Git

Сохраните старый VPS и архив до полной проверки нового. На controller используйте
уже имеющийся checkout с этой версией restore. Подготовьте `.env` нового VPS:
DOMAIN должен совпадать с сохранённым в backup, а A-запись — указывать на новый
VPS; AAAA отсутствует. Это перенос того же endpoint и credentials. Смену domain
выполните последующим обычным deploy, когда source Git снова доступен.

```bash
chmod 600 /absolute/path/backup.tar.gz
make bootstrap
make restore BACKUP_FILE=/absolute/path/backup.tar.gz
make credentials
```

Тот же Ansible bootstrap настраивает host; restore playbook устанавливает Docker
и acceptance tools. Runtime берётся целиком из backup, без Git fetch, Docker
build или image pull. Caddy certificates/config volumes переносятся вместе с
image. Restore проверяет image identity, archive paths, domain, health и публичный
HTTPS/proxy. Загрузка apt packages/Ansible dependencies для подготовки нового
host может требовать сеть; автономность относится к исходникам и runtime образу.

Runtime acceptance после restore выполняется самим check-server.sh. Полный
`make verify` также сверяет Git checkout/origin/ref и требует source checkout.
До возвращения Git используйте `sudo make -C /opt/naive-gateway/current check`;
после восстановления Git обычный `make deploy` создаст checkout, затем доступен
полный `make verify`. Backup manifest/image identity не объявляются проверкой Git origin.

Restore отказывается перезаписывать существующие gateway containers, volumes,
env/current или незавершённый recovery. Не удаляйте их вслепую ради повторного
запуска. При отказе сохраните backup, изучите service/state; новый host остаётся
предпочтительным местом восстановления. При обычной ошибке acceptance созданный
candidate останавливается, вновь созданные volumes удаляются, архив сохраняется.
При сбое самого recovery сохраните `deployment-recovery` для диагностики.

Старые архивы без manifest/image/volumes не являются автономными backup нового
формата. Для них нужен доступный сохранённый Git commit и прежний recovery path;
не называйте такое восстановление автономным. Сохраняйте старый сервер до
создания и проверки нового backup.

## Сбои и сохранение предыдущей версии

После bootstrap failure оставьте исходный SSH-сеанс открытым. При необходимости
восстановите доступ через консоль провайдера, затем повторите `make bootstrap`.
Не отключайте root/password вручную до проверки managed SSH/sudo.

Перед изменением runtime env deploy сохраняет предыдущие env/release. Ошибка
активации вызывает восстановление прежнего container/env/current. Прерванный
процесс восстанавливается при следующем `make deploy` до подготовки кандидата.
При неудаче rollback snapshot остаётся в `/etc/naive-gateway/deployment-recovery`;
не удаляйте его и не запускайте rotation/backup до восстановления согласованного
состояния. Проверьте status/logs, Docker service, доступность прежнего release и
image, устраните причину и повторите `make deploy`. Первый неуспешный deploy
сохраняет pending credentials, но не объявляется установленным.

После успешного acceptance предыдущие credentials/release находятся в приватном
`previous-deployment`. Старые snapshots сохраняются в `deployment-history`.
Автоматического prune нет: current, предыдущий успешный image/release, volumes,
backups и незавершённый recovery нельзя удалять. Cleanup допускается только после
подтверждения здорового текущего сервиса и проверки отдельного backup.

Rotation при ошибке возвращает прежний env и перезапускает Caddy. Если перезапуск
самого rollback не удался, путь к сохранённому root-only env выводится для recovery.
Файлы `gateway.env.rotate.*` после аварийного завершения сохраняйте до проверки
актуальных credentials; затем удаляйте только подтверждённо лишние копии.

Реальные SSH/lockout, public ACME/CONNECT, external sentinel/scan, systemd/reboot,
restore и rotation на Ubuntu VPS оставлены финальными gates по решению владельца.
