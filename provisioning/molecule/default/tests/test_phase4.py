from __future__ import annotations

import os

import testinfra.utils.ansible_runner

MANAGED_USER = "molecule_admin"
PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOZGc3eD7DMtNLskGutOfXw7ZmiK4B9Hl0+7wYs2qIib "
    "molecule-phase4"
)
DROP_IN = "/etc/ssh/sshd_config.d/00-naive-gateway-hardening.conf"

testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
    os.environ["MOLECULE_INVENTORY_FILE"],
).get_hosts("all")


def test_bootstrap_prerequisites(host: object) -> None:
    assert host.package("python3").is_installed
    assert host.package("sudo").is_installed
    assert host.file("/etc/debian_version").exists


def test_managed_user_contract(host: object) -> None:
    user = host.user(MANAGED_USER)
    assert user.exists
    assert user.home == f"/home/{MANAGED_USER}"
    assert user.shell == "/bin/bash"
    assert "sudo" in user.groups
    assert "docker" not in user.groups


def test_authorized_key_is_exact_and_private(host: object) -> None:
    ssh_directory = host.file(f"/home/{MANAGED_USER}/.ssh")
    authorized_keys = host.file(f"/home/{MANAGED_USER}/.ssh/authorized_keys")
    assert ssh_directory.is_directory
    assert ssh_directory.user == MANAGED_USER
    assert ssh_directory.mode == 0o700
    assert authorized_keys.is_file
    assert authorized_keys.user == MANAGED_USER
    assert authorized_keys.mode == 0o600
    assert authorized_keys.content_string == f"{PUBLIC_KEY}\n"


def test_second_run_preserves_password_hash(host: object) -> None:
    initial = host.file("/root/.molecule-phase4/initial-password-hash").content_string.strip()
    current = host.run(f"getent shadow {MANAGED_USER}").stdout.split(":", maxsplit=2)[1]
    assert initial.startswith("$")
    assert current == initial


def test_ssh_hardening_is_valid_and_effective(host: object) -> None:
    drop_in = host.file(DROP_IN)
    assert drop_in.is_file
    assert drop_in.user == "root"
    assert drop_in.group == "root"
    assert drop_in.mode == 0o600
    assert host.run("/usr/sbin/sshd -t").rc == 0
    effective = host.run(
        f"/usr/sbin/sshd -T -C user={MANAGED_USER},host=localhost,addr=127.0.0.1",
    ).stdout
    for expected in (
        "pubkeyauthentication yes",
        "passwordauthentication no",
        "kbdinteractiveauthentication no",
        "permitrootlogin no",
    ):
        assert expected in effective.splitlines()


def test_invalid_ssh_template_was_rejected(host: object) -> None:
    assert host.file("/root/.molecule-phase4/invalid-ssh-rejected").is_file
    assert host.run("/usr/sbin/sshd -t").rc == 0
