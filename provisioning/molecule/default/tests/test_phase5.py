from __future__ import annotations

import os

import testinfra.utils.ansible_runner

testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
    os.environ["MOLECULE_INVENTORY_FILE"],
).get_hosts("all")


def test_ufw_package_and_default_policies(host: object) -> None:
    assert host.package("ufw").is_installed
    defaults = host.file("/etc/default/ufw").content_string
    assert 'DEFAULT_INPUT_POLICY="DROP"' in defaults
    assert 'DEFAULT_OUTPUT_POLICY="ACCEPT"' in defaults


def test_ufw_is_active_with_only_expected_host_ports(host: object) -> None:
    status = host.run("/usr/sbin/ufw status verbose")
    assert status.rc == 0
    assert "Status: active" in status.stdout
    assert "Default: deny (incoming), allow (outgoing)" in status.stdout

    added = host.run("/usr/sbin/ufw show added")
    assert added.rc == 0
    rules = {line.strip() for line in added.stdout.splitlines() if line.strip().startswith("ufw ")}
    assert rules == {
        "ufw limit 22/tcp",
        "ufw allow 80/tcp",
        "ufw allow 443/tcp",
    }
    assert "443/udp" not in added.stdout


def test_unmanaged_ufw_rule_was_rejected(host: object) -> None:
    assert host.file("/root/.molecule-phase4/unmanaged-ufw-rejected").is_file


def test_docker_ingress_policy_is_loaded_for_ipv4_and_ipv6(host: object) -> None:
    expected_user = (
        "-N DOCKER-USER",
        "-A DOCKER-USER -j NAIVE-GATEWAY-DOCKER",
        "-A DOCKER-USER -j RETURN",
    )
    expected_managed = (
        "-N NAIVE-GATEWAY-DOCKER",
        "-A NAIVE-GATEWAY-DOCKER -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN",
        "-A NAIVE-GATEWAY-DOCKER -o docker0 -p tcp -m conntrack --ctstate NEW --ctorigdstport 80 -j RETURN",
        "-A NAIVE-GATEWAY-DOCKER -o docker0 -p tcp -m conntrack --ctstate NEW --ctorigdstport 443 -j RETURN",
        "-A NAIVE-GATEWAY-DOCKER -o br+ -p tcp -m conntrack --ctstate NEW --ctorigdstport 80 -j RETURN",
        "-A NAIVE-GATEWAY-DOCKER -o br+ -p tcp -m conntrack --ctstate NEW --ctorigdstport 443 -j RETURN",
        "-A NAIVE-GATEWAY-DOCKER -o docker0 -j DROP",
        "-A NAIVE-GATEWAY-DOCKER -o br+ -j DROP",
        "-A NAIVE-GATEWAY-DOCKER -j RETURN",
    )
    for binary in ("iptables", "ip6tables"):
        user = host.run(f"/usr/sbin/{binary} -S DOCKER-USER")
        managed = host.run(f"/usr/sbin/{binary} -S NAIVE-GATEWAY-DOCKER")
        assert user.rc == 0
        assert managed.rc == 0
        assert tuple(user.stdout.splitlines()) == expected_user
        assert tuple(managed.stdout.splitlines()) == expected_managed


def test_docker_ingress_blocks_are_exact_and_private(host: object) -> None:
    marker = "# BEGIN ANSIBLE MANAGED NAIVE GATEWAY DOCKER INGRESS"
    for path in ("/etc/ufw/after.rules", "/etc/ufw/after6.rules"):
        rules = host.file(path)
        assert rules.is_file
        assert rules.user == "root"
        assert rules.group == "root"
        assert rules.mode == 0o640
        assert rules.content_string.count(marker) == 1
        assert "--ctorigdstport 80" in rules.content_string
        assert "--ctorigdstport 443" in rules.content_string


def test_invalid_docker_ingress_template_was_rejected(host: object) -> None:
    marker = host.file("/root/.molecule-phase4/invalid-docker-ingress-rejected")
    assert marker.is_file
