# Ansible provisioning

Фаза 3.6 содержит проверяемый каркас. `bootstrap`, `deploy` и `verify` ещё
не являются рабочими provisioning-командами; их роли заполняются в следующих
фазах плана.

## Правила секретов

- plaintext passwords и private keys запрещены в inventory, variables и tasks;
- значения передаются только через variables/templates либо Ansible Vault;
- каждая task, которая читает, генерирует, хеширует или записывает password,
  private key либо Naive credentials, обязана иметь `no_log: true`;
- `display_args_to_stdout = False` запрещает добавлять module arguments к task
  headings;
- pytest policy tests блокируют plaintext secrets и private keys до запуска
  playbook;
- ansible-lint с профилем `production` проверяет schema, включая role
  `meta/argument_specs.yml`;
- callback, пишущий task payload в файл или внешний сервис, не включается без
  отдельного security review.

## Проверки

Локально CI-контракты воспроизводятся командами:

```bash
make tooling
make lint
make test
```

GitHub Actions отдельно выполняет полный quality gate, pytest на Python
3.12–3.14 и Docker/Caddy runtime smoke. Workflow не запускает `preflight` и не
подключается к VPS.
