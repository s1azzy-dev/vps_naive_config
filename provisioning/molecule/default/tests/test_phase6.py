from __future__ import annotations

import json
import os

import testinfra.utils.ansible_runner

testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
    os.environ["MOLECULE_INVENTORY_FILE"],
).get_hosts("all")


def test_official_docker_repository_and_key(host: object) -> None:
    key = host.file("/etc/apt/keyrings/docker.asc")
    source = host.file("/etc/apt/sources.list.d/docker.sources")
    assert key.is_file
    assert key.user == "root"
    assert key.group == "root"
    assert key.mode == 0o644
    assert source.is_file
    assert source.user == "root"
    assert source.group == "root"
    assert source.mode == 0o644
    assert "URIs: https://download.docker.com/linux/debian" in source.content_string
    assert "Suites: bookworm" in source.content_string
    assert "Components: stable" in source.content_string
    fingerprint = host.run(
        "/usr/bin/gpg --batch --show-keys --with-colons /etc/apt/keyrings/docker.asc",
    )
    assert fingerprint.rc == 0
    assert "9DC858229FC7DD38854AE2D88D81803C0EBFCD88" in fingerprint.stdout


def test_exact_docker_package_set_and_compose_v2(host: object) -> None:
    for package in (
        "docker-ce",
        "docker-ce-cli",
        "containerd.io",
        "docker-buildx-plugin",
        "docker-compose-plugin",
    ):
        assert host.package(package).is_installed
    assert host.run("/usr/bin/docker --version").rc == 0
    assert host.run("/usr/bin/docker compose version").rc == 0


def test_docker_daemon_policy_is_exact_and_private(host: object) -> None:
    daemon = host.file("/etc/docker/daemon.json")
    assert daemon.is_file
    assert daemon.user == "root"
    assert daemon.group == "root"
    assert daemon.mode == 0o644
    assert json.loads(daemon.content_string) == {
        "allow-direct-routing": False,
        "default-network-opts": {
            "bridge": {
                "com.docker.network.bridge.host_binding_ipv4": "127.0.0.1",
            },
        },
        "firewall-backend": "iptables",
        "ip6tables": True,
        "iptables": True,
    }
    validation = host.run(
        "/usr/bin/dockerd --validate --config-file=/etc/docker/daemon.json",
    )
    assert validation.rc == 0


def test_docker_management_and_privilege_boundaries(host: object) -> None:
    marker = host.file("/etc/naive-gateway/docker-managed")
    assert marker.is_file
    assert marker.user == "root"
    assert marker.group == "root"
    assert marker.mode == 0o600
    groups = host.run("/usr/bin/id -nG molecule_admin")
    assert groups.rc == 0
    assert "docker" not in groups.stdout.split()
    assert host.file("/root/.molecule-phase4/unmanaged-docker-rejected").is_file
    assert host.file(
        "/root/.molecule-phase4/unmanaged-docker-firewall-rejected",
    ).is_file
    socket = host.file("/var/run/docker.sock")
    assert socket.is_socket
    assert socket.user == "root"
    assert socket.group == "docker"
    assert socket.mode == 0o660
    assert host.run("/usr/bin/docker info").rc == 0


def test_effective_user_defined_network_bind_default(host: object) -> None:
    network = host.run(
        "/usr/bin/docker network inspect --format "
        "'{{ index .Options \"com.docker.network.bridge.host_binding_ipv4\" }}' "
        "molecule-default-bind",
    )
    assert network.rc == 0
    assert network.stdout.strip() == "127.0.0.1"


def test_docker_ingress_policy_survived_ufw_reload(host: object) -> None:
    user = host.run("/usr/sbin/iptables -S DOCKER-USER")
    assert user.rc == 0
    assert user.stdout.splitlines() == [
        "-N DOCKER-USER",
        "-A DOCKER-USER -j NAIVE-GATEWAY-DOCKER",
        "-A DOCKER-USER -j RETURN",
    ]
