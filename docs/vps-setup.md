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

В firewall панели VPS-провайдера разрешите входящие подключения:

- `22/tcp` — SSH;
- `80/tcp` — выпуск и обновление TLS-сертификата;
- `443/tcp` — HTTPS и Naive;
- `443/udp` — необязательно, только для HTTP/3 публичного сайта.

Если у вас постоянный внешний IP, ограничьте `22/tcp` этим адресом в панели провайдера.

Затем в сессии `slazzy` настройте UFW:

```bash
sudo apt-get update
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw limit 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
sudo ufw status verbose
```

Установщик firewall не изменяет.

## 7. Установите Naive Gateway

Все следующие команды выполняйте в SSH-сессии пользователя `slazzy`:

```bash
cd ~
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/s1azzy-dev/vps_naive_config.git
cd vps_naive_config
sudo DOMAIN=proxy.example.com ACME_EMAIL=admin@example.com ./install.sh
```

Замените домен и email своими значениями. Установщик:

1. установит диагностические утилиты и Docker Engine с Compose;
2. сверит публичный IPv4 VPS с `A`-записью;
3. создаст `.env` со случайными учётными данными;
4. соберёт закреплённый образ Caddy с модулем `forwardproxy`;
5. проверит конфигурацию, запустит контейнер и дождётся публичного TLS;
6. проверит сайт, HTTP/2, защиту от простого обнаружения proxy и авторизованный CONNECT.

Сохраните выведенные endpoint, имя пользователя и пароль. Они также находятся в root-доступном файле `.env` с правами `600`.

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

Частые причины: DNS ещё не обновился, `80/tcp` или `443/tcp` закрыт у провайдера, эти порты заняты другим сервисом, либо существует неверная `AAAA`-запись.

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

Для переноса на другой VPS повторите шаги 1–7, восстановите `.env` из защищённой копии, переключите DNS и запустите `sudo ./install.sh`. Старый VPS выключайте только после успешного `sudo make check` на новом адресе.

## Справочная документация

- [Настройка OpenSSH в Ubuntu](https://documentation.ubuntu.com/server/how-to/security/openssh-server/)
- [Управление пользователями Ubuntu Server](https://documentation.ubuntu.com/server/how-to/security/user-management/)
- [Почему группа Docker предоставляет root-права](https://docs.docker.com/engine/install/linux-postinstall/)
