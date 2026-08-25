# Подготовка и запуск на чистом VPS

Инструкция рассчитана на Ubuntu 22.04/24.04/26.04 или Debian 12/13. Постоянная работа по SSH выполняется пользователем `slazzy`; прямой вход под `root` используется только для первичной настройки.

Не закрывайте первоначальную SSH-сессию, пока вход под `slazzy` и `sudo` не проверены в отдельном терминале.

## 1. Создайте SSH-ключ на своём компьютере

Если отдельного ключа для VPS ещё нет:

```bash
ssh-keygen -t ed25519 -a 100 -f ~/.ssh/slazzy_vps -C "slazzy@vps"
```

Задайте ключу passphrase. Будут созданы два файла:

- `~/.ssh/slazzy_vps` — приватный ключ, его нельзя никому передавать или загружать на сервер;
- `~/.ssh/slazzy_vps.pub` — публичный ключ, именно его нужно добавить на VPS.

Проверьте публичный ключ:

```bash
cat ~/.ssh/slazzy_vps.pub
```

Строка должна начинаться с `ssh-ed25519`. Если вы видите `-----BEGIN OPENSSH PRIVATE KEY-----`, это приватный ключ — остановитесь и не копируйте его.

Скопируйте публичный ключ в буфер обмена на macOS:

```bash
pbcopy < ~/.ssh/slazzy_vps.pub
```

Убедитесь, что в буфере именно публичный ключ:

```bash
pbpaste
```

Для Linux вместо `pbcopy` используйте `wl-copy < ~/.ssh/slazzy_vps.pub` в Wayland или `xclip -selection clipboard < ~/.ssh/slazzy_vps.pub` в X11.

Если VPS-провайдер позволяет выбрать SSH-ключ при создании сервера, вставьте скопированную строку в поле SSH key панели провайдера. Это предпочтительнее первоначального входа по паролю.

## 2. Создайте пользователя `slazzy`

Один раз подключитесь под `root` с созданным ключом:

```bash
ssh -i ~/.ssh/slazzy_vps root@VPS_IP
```

Если провайдер выдал только пароль `root`, используйте его лишь для этой первичной настройки.

На VPS выполните:

```bash
apt-get update
apt-get install -y sudo
adduser slazzy
usermod -aG sudo slazzy
id slazzy
```

`adduser` попросит задать пароль пользователя. Он будет использоваться для `sudo`, но после отключения парольного SSH-входа на шаге 4 не будет приниматься для удалённого подключения.

Теперь создайте каталог для ключа:

```bash
install -d -m 700 -o slazzy -g slazzy /home/slazzy/.ssh
```

Запустите ввод файла:

```bash
cat > /home/slazzy/.ssh/authorized_keys
```

Команда будет ждать ввод. Вставьте публичный ключ из буфера сочетанием `Cmd+V`. Он должен занимать одну строку и начинаться с `ssh-ed25519`. Затем нажмите `Enter` и `Ctrl+D`, чтобы сохранить файл и вернуться в shell.

Установите правильного владельца и права:

```bash
chown slazzy:slazzy /home/slazzy/.ssh/authorized_keys
chmod 600 /home/slazzy/.ssh/authorized_keys
```

Проверьте сохранённый ключ на VPS:

```bash
cat /home/slazzy/.ssh/authorized_keys
ssh-keygen -lf /home/slazzy/.ssh/authorized_keys
```

На своём компьютере получите fingerprint исходного публичного ключа:

```bash
ssh-keygen -lf ~/.ssh/slazzy_vps.pub
```

Fingerprint в двух выводах должен совпасть.

## 3. Проверьте вход под `slazzy`

Не закрывая root-сессию, откройте второй локальный терминал:

```bash
ssh -i ~/.ssh/slazzy_vps slazzy@VPS_IP
sudo -v
whoami
```

Ожидаемый результат `whoami` — `slazzy`, а `sudo -v` должен принять заданный на предыдущем шаге пароль.

Если вход не работает, исправьте ключ и права через оставшуюся root-сессию. К следующему шагу переходите только после успешной проверки.

## 4. Запретите root-вход и SSH-пароли

В проверенной сессии `slazzy` создайте отдельный конфигурационный фрагмент OpenSSH:

```bash
sudo tee /etc/ssh/sshd_config.d/00-slazzy-hardening.conf >/dev/null <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF

sudo sshd -t
sudo systemctl reload ssh
```

Команда `sshd -t` не должна выводить ошибок. Проверьте применённые значения:

```bash
sudo sshd -T | grep -E \
  '^(pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '
```

Ожидается:

```text
permitrootlogin no
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication no
```

Откройте ещё один терминал и повторно проверьте вход:

```bash
ssh -i ~/.ssh/slazzy_vps slazzy@VPS_IP
```

Только после этого можно закрыть первоначальную root-сессию.

## 5. Подготовьте домен

Создайте `A`-запись, например `proxy.example.com`, указывающую на публичный IPv4 VPS. Дождитесь обновления DNS и проверьте со своего компьютера:

```bash
dig +short A proxy.example.com
```

Если у VPS нет рабочего публичного IPv6, удалите `AAAA`-запись домена. Иначе часть подключений может уходить на неверный адрес.

## 6. Настройте firewall

Если панель VPS-провайдера умеет фильтровать ingress, зеркально разрешите только:

- `22/tcp` — SSH;
- `80/tcp` — выпуск и обновление TLS-сертификата;
- `443/tcp` — HTTPS и Naive.

`443/udp` не открывайте: текущая конфигурация использует только HTTP/1.1 и HTTP/2.

Если такой панели нет, это не блокирует выбранную архитектуру: обязательная
граница находится внутри VPS и управляется Ansible. UFW защищает host INPUT, а
Ansible-owned `DOCKER-USER` policy отдельно защищает Docker FORWARD. Она сверяет
original host port до Docker accept rules, поэтому случайный mapping вроде
`0.0.0.0:18080:443` не получает разрешение порта 443.

Не собирайте эти rules вручную. На controller заполните `.env` вручную, не
передавая значения через CLI, затем выполните локальные проверки:

```bash
cp .env.example .env
chmod 600 .env
# заполните .env в редакторе
make tooling
make check-config
make preflight
```

`make bootstrap` изменяет VPS и поэтому запускается только когда вы готовы к
provisioning. Он создаёт пользователя и sudo, проверяет новое SSH-соединение,
hardens SSH, затем применяет UFW и валидированную Docker ingress policy. Не
закрывайте исходную root-сессию до отдельного reconnect. Полный lockout/firewall
gate сначала должен пройти на disposable VM/VPS.

## 7. Установите Naive Gateway

На текущем этапе автоматизация production deployment ещё не завершена: локально
реализованы bootstrap/firewall/Docker roles, а gateway role и controller command
будут закончены в фазах 7–8. Не запускайте эту ветку на настроенном production VPS.

Переходный `install.sh` больше не устанавливает Docker и отказывается работать
без `/etc/naive-gateway/docker-managed`. Он оставлен только для миграционного
периода после Ansible-подготовки clean/disposable host. Все значения `.env`
заполняются пользователем вручную; передача секретов через CLI не требуется.

Не добавляйте `slazzy` в группу `docker`: доступ к Docker socket фактически равен root-доступу. Не настраивайте `NOPASSWD` для `sudo`; запускайте административные команды явно через `sudo`.

## 8. Проверьте сервер

```bash
sudo make status
sudo make check
curl -I https://proxy.example.com/
```

Ожидаемый результат: контейнер `caddy` имеет состояние `healthy`, сайт отвечает `200`, а `make check` заканчивается строкой `Server checks passed.`

Если проверка не проходит:

```bash
sudo make logs
sudo docker compose --env-file versions.env --env-file .env ps
sudo ss -lntup | grep -E ':80|:443'
dig +short A proxy.example.com
```

Частые причины: DNS ещё не обновился, `80/tcp` или `443/tcp` блокируется внешней
сетью/host policy, эти порты заняты другим сервисом либо существует неверная
`AAAA`-запись.

## 9. Обслуживайте установку

Создать резервную копию конфигурации:

```bash
sudo make backup
```

Архив появляется в `backups/` и содержит действующие секреты. Не публикуйте его и перенесите в защищённое хранилище.

Сменить учётные данные:

```bash
sudo make rotate-credentials
```

Получить проверенные обновления репозитория, пересобрать образ и проверить сервер:

```bash
sudo make update
```

Перед обновлением рабочее дерево должно быть без локальных изменений. Версии зависимостей меняются только явным коммитом в `versions.env`.

Для переноса на другой VPS используйте disposable-first Ansible workflow из
актуального provisioning-плана, восстановите `.env` из защищённой копии и только
после external acceptance переключайте DNS. Старый VPS выключайте после
успешного `make check` на новом адресе.

## Справочная документация

- [Настройка OpenSSH в Ubuntu](https://documentation.ubuntu.com/server/how-to/security/openssh-server/)
- [Управление пользователями Ubuntu Server](https://documentation.ubuntu.com/server/how-to/security/user-management/)
- [Почему группа Docker предоставляет root-права](https://docs.docker.com/engine/install/linux-postinstall/)
