# Ansible provisioning

Фаза 2 содержит только проверяемый каркас. `bootstrap`, `deploy` и `verify` ещё
не являются рабочими provisioning-командами; их роли заполняются в следующих
фазах плана.

## Правила секретов

- plaintext passwords и private keys запрещены в inventory, variables и tasks;
- значения передаются только через variables/templates либо Ansible Vault;
- каждая task, которая читает, генерирует, хеширует или записывает password,
  private key либо Naive credentials, обязана иметь `no_log: true`;
- `display_args_to_stdout = False` запрещает добавлять module arguments к task
  headings;
- `scripts/check-ansible-secrets.sh` блокирует plaintext secrets до запуска
  playbook;
- callback, пишущий task payload в файл или внешний сервис, не включается без
  отдельного security review.
