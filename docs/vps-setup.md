# Восстановление и диагностика

Установка, конфигурация и обычное сопровождение описаны в
[README](../README.md). Здесь — действия при сбоях и переносе runtime.
Не запускайте deploy, restore, backup и rotation параллельно.

## Сохранить backup вне VPS

На VPS выполните `sudo make -C /opt/naive-gateway/current backup` и возьмите
напечатанный путь архива. Архив содержит release, credentials, точный image и
certificate private keys; права архива `0600`, каталога `0700`. Git config не входит.

Чтобы скачать root-only архив через managed user, на VPS создайте приватную копию
для него (замените `ARCHIVE.tar.gz` на фактическое имя):

```bash
sudo install -m 600 -o "$USER" -g "$(id -gn)" \
  /var/backups/naive-gateway/ARCHIVE.tar.gz "$HOME/gateway-backup.tar.gz"
```

На компьютере, в каталоге проекта:

```bash
scp -P 22 -i ~/.ssh/naive_vps slazzy@203.0.113.10:gateway-backup.tar.gz backups/
chmod 600 backups/gateway-backup.tar.gz
```

Порт/ключ/user/IP замените своими. Убедитесь, что копия скачана полностью;
храните её как секрет. Старый VPS и архив сохраняйте до успешного восстановления.

## Автономное восстановление без исходного Git

Сохраните старый VPS и архив до полной проверки нового. На controller используйте
уже имеющийся checkout с этой версией restore. Подготовьте `.env` нового VPS:
DOMAIN и ACME_EMAIL должны совпадать с сохранёнными в backup. A-запись должна указывать на новый
VPS; AAAA отсутствует. Явную пару NAIVE_USER/NAIVE_PASSWORD очистите либо согласуйте
с backup. Это перенос того же endpoint и credentials. Смену domain
выполните последующим обычным deploy, когда source Git снова доступен.

```bash
chmod 600 /absolute/path/backup.tar.gz
make bootstrap
make restore BACKUP_FILE=/absolute/path/backup.tar.gz
make verify
make credentials
```

Тот же Ansible bootstrap настраивает host; restore playbook устанавливает Docker
и acceptance tools. Runtime берётся целиком из backup, без Git fetch, Docker
build или image pull. Caddy certificates/config volumes переносятся вместе с
image. Restore проверяет image identity, archive paths, domain, health и публичный
HTTPS/proxy. Загрузка apt packages/Ansible dependencies для подготовки нового
host может требовать сеть; автономность относится к исходникам и runtime образу.

Runtime acceptance после restore выполняет `check-server.sh`. После него
можно сразу запустить `make verify`: source checkout на новом VPS и доступ к
Git origin не нужны. Проверяются marker/current/image и фактический сервис.
При явном GATEWAY_REF как commit он должен совпадать с backup; branch/tag не
проверяются через origin. Backup manifest и marker не доказывают происхождение Git.

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

## Отказы доступа и конфигурации

| Отказ | Что проверить / как продолжить |
| --- | --- |
| Tooling: command cannot run | Проверить `command -v git` и `git --version` (аналогично для указанной команды), архитектуру executable и PATH; выбрать рабочий binary в PATH запуска Make |
| Host key changed | Сверить новый fingerprint через консоль провайдера. Только после подтверждения удалить старую запись из `provisioning/known_hosts` и повторить preflight |
| Managed sudo failed | Использовать действующий пароль, проверить sudo rules; NOPASSWD не заменяет password proof |
| Existing account / Docker / UFW not managed | Не создавать marker вручную и не стирать чужие данные. Проверить аварийный доступ и принадлежность ресурсов; для чистого VPS выбрать новое имя account или пересоздать VPS |
| Account создан, marker ещё нет | Рассматривать как существующий неуправляемый account, проверить его отдельно; retry не присваивает его молча |
| SSH Match / nested Include rejected | Произвольная conditional policy не мигрируется. Изучить полную SSH config и доступ через консоль до ручной миграции |
| Port conflict | Через `sudo ss -ltnp` и `sudo docker ps` найти владельца TCP 80/443; затем устранить конфликт и повторить deploy |
| DNS / HTTPS / proxy acceptance | Проверить DOMAIN A/AAAA, порты, сертификат, Caddy logs и доступность внешних test targets; transport error не доказывает отказ anonymous proxy |

Новое доверие SSH после пересоздания VPS устанавливается отдельно от переноса
приложения. Например, удалить **проверенную устаревшую** запись стандартного порта:

```bash
ssh-keygen -R 203.0.113.10 -f provisioning/known_hosts
make preflight
```

Для нестандартного порта используйте `[203.0.113.10]:2222` вместо IP.
Credentials можно прочитать через `make credentials`, даже если DNS gateway
неисправен: нужны managed SSH, sudo и уже известный host key.

Реальные SSH/lockout, public ACME/CONNECT, external scan, systemd/reboot и
restore/rotation на Ubuntu VPS пока не проверены; [приёмка](ansible-provisioning-plan.md)
остаётся открытой.
