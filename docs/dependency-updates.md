# Обновление зависимостей

Менять pins отдельной веткой и одним проверяемым набором. Не обновлять production
на `latest`. До изменения проверить официальные release notes и security advisories
Caddy, forwardproxy, Docker, Python/Ansible и выбранных base images.

1. В `versions.env` указать точную Caddy version и полный reviewed forwardproxy
   commit. Проверить существование revision, совместимость Go и Caddy API, изменения
   authentication, CONNECT, probe resistance и logging.
   Dockerfile повторяет официальный build forwardproxy: получает оба исходника,
   применяет `caddy-sing-quic-bbrv1.patch` и `caddy-read-idle-timeout.patch` из
   закреплённого commit и передаёт локальный Caddy в xcaddy через `--replace`.
   Второй патч предоставляет API продления idle timeout для authenticated CONNECT;
   простая сборка plugin со stock Caddy для текущей пары pins не подходит.
2. Для Python/Ansible изменить pins в `pyproject.toml` и обновить `uv.lock` через
   `.venv/bin/uv lock`, не редактируя lock вручную. Tooling читает pins из pyproject;
   второй список в controller/tests не поддерживается. Версию bootstrap uv также
   согласовать в Makefile и CI: они нужны до установки environment.
   Patch Python менять в `.python-version`: этот файл читает uv и CI. Поддерживаемая
   ветка остаётся 3.14; локальный `make tooling` запускайте с этим интерпретатором.
   Для collections менять только `provisioning/requirements.yml`; tooling сверяет
   установленные versions с этим файлом. Caddy/forwardproxy берутся из `versions.env`
   для Compose build и smoke; одинаковые version literals в тесты не добавлять.
3. Выполнить `make tooling`, `make lint`, `make test`, `make molecule` и
   `./tests/smoke-local.sh`. Проверить module presence, legitimate CONNECT,
   anonymous rejection, TLS/HTTP2 и отсутствие destinations в логах.
   При изменении idle-timeout патча проверить CONNECT по HTTP/2 после паузы,
   превышающей серверный read-body idle timeout.
4. Опубликовать commit, проверить обновление и rollback на disposable Ubuntu 26.04
   amd64. На VPS перед deploy сохранить автономный backup с прежним образом.
5. После public acceptance оставить текущий и предыдущий успешный release/image.
   Не применять Docker prune: он может удалить данные для recovery и другие workloads.

Docker base images сейчас закреплены version tags, не digest; apt-пакеты Docker
не закреплены точными версиями. Frozen uv/collection pins и source commits не дают
побитовой воспроизводимости всего VPS. Принудительное обновление base digest/apt
policy требует отдельного решения и той же приёмки. Этот порядок не является CVE
проверкой текущих зависимостей; результаты такого сканирования здесь не заявляются.

## Docker и системные пакеты VPS

Ubuntu 26.04 устанавливает Python и системные библиотеки из своего apt-репозитория;
контроллер, Ansible и dev-зависимости работают на компьютере. Caddy с forwardproxy
собирается в контейнере. NaiveProxy client на роутере этот проект не устанавливает.

Docker берётся из официального stable apt-репозитория. Роль использует `state: present`:
новый VPS получает доступную версию, повторный provision не обновляет работающий daemon.
На 2026-10-29 доступны Engine/CLI 29.9.2, Compose 5.6.1, containerd.io 2.4.2 и
Buildx 0.38.1. Это проверенные upstream версии, а не утверждение о состоянии вашего VPS.

Для обслуживания **уже управляемого** VPS в SSH-сессии сначала выполните
`sudo make -C /opt/naive-gateway/current backup` и скопируйте архив на компьютер.
Затем в той же SSH-сессии выполните:

```bash
sudo apt-get update
sudo apt-get install --only-upgrade docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker version
sudo docker compose version
cd /opt/naive-gateway/current
sudo make check
```

Обновление пакетов может перезапустить Docker. После него с компьютера выполните
`make verify`. Python VPS обновляется штатными security updates Ubuntu; заменять
системный `/usr/bin/python3` отдельной сборкой CPython не нужно.

Источники: [сборка forwardproxy](https://github.com/klzgrad/forwardproxy/blob/e747854e78743dba85c039b38ed185fb11d93667/.github/workflows/build.yml),
[Docker Engine](https://docs.docker.com/engine/release-notes/29/),
[Docker для Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[Python 3.14.10](https://www.python.org/downloads/release/python-31410/).
