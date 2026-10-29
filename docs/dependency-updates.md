# Обновление зависимостей

Менять pins отдельной веткой и одним проверяемым набором. Не обновлять production
на `latest`. До изменения проверить официальные release notes и security advisories
Caddy, forwardproxy, Docker, Python/Ansible и выбранных base images.

1. В `versions.env` указать точную Caddy version и полный reviewed forwardproxy
   commit. Проверить существование revision, совместимость Go и Caddy API, изменения
   authentication, CONNECT, probe resistance и logging.
2. Для Python/Ansible изменить точные pins в `pyproject.toml` и соответствующие
   EXPECTED_VERSIONS в controller; обновить `uv.lock`, не редактируя lock вручную.
   Для collections синхронно изменить `provisioning/requirements.yml` и contract tests.
3. Выполнить `make tooling`, `make lint`, `make test`, `make molecule` и
   `./tests/smoke-local.sh`. Проверить module presence, legitimate CONNECT,
   anonymous rejection, TLS/HTTP2 и отсутствие destinations в логах.
4. Опубликовать commit, проверить обновление и rollback на disposable Ubuntu 26.04
   amd64. На VPS перед deploy сохранить автономный backup с прежним образом.
5. После public acceptance оставить текущий и предыдущий успешный release/image.
   Не применять Docker prune: он может удалить данные для recovery и другие workloads.

Docker base images сейчас закреплены version tags, не digest; apt-пакеты Docker
не закреплены точными версиями. Frozen uv/collection pins и source commits не дают
побитовой воспроизводимости всего VPS. Принудительное обновление base digest/apt
policy требует отдельного решения и тех же gates. Этот порядок не является CVE
проверкой текущих зависимостей; результаты такого сканирования здесь не заявляются.
