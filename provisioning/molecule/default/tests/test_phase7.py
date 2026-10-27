from __future__ import annotations

import os

import testinfra.utils.ansible_runner

testinfra_hosts = testinfra.utils.ansible_runner.AnsibleRunner(
    os.environ["MOLECULE_INVENTORY_FILE"],
).get_hosts("all")


def test_gateway_runtime_is_private_and_release_is_pinned(host: object) -> None:
    runtime = host.file("/etc/naive-gateway/gateway.env")
    assert runtime.is_file
    assert runtime.user == "root"
    assert runtime.group == "root"
    assert runtime.mode == 0o600
    commit = host.file("/root/.molecule-phase4/gateway-deployment-verified").content_string.strip()
    current = host.file("/opt/naive-gateway/current")
    assert current.is_symlink
    assert current.linked_to == f"/opt/naive-gateway/releases/{commit}"
    assert host.file(f"{current.linked_to}/.release-complete").content_string.strip() == commit


def test_gateway_container_is_healthy_and_uses_immutable_mounts(host: object) -> None:
    container = host.check_output(
        "docker ps -q --filter label=com.docker.compose.project=naive-gateway",
    )
    assert container
    assert (
        host.check_output("docker inspect --format '{{.State.Health.Status}}' %s", container)
        == "healthy"
    )
    mounts = host.check_output("docker inspect --format '{{json .Mounts}}' %s", container)
    assert "/opt/naive-gateway/releases/" in mounts
    assert "/repository/" not in mounts
    assert "/docker.sock" not in mounts


def test_release_operational_commands_resolve_the_active_env(host: object) -> None:
    result = host.run("cd /opt/naive-gateway/current && make status")
    assert result.rc == 0
    assert "healthy" in result.stdout
    assert "NAIVE_PASSWORD=" not in result.stdout
