# Docker ingress hardening evidence context

Analysis date: 2026-08-24

Source root: `/Users/a.tselovalnikov/projects/vps_naive_config`

Source identity:

- Git HEAD: `1c508c4c532cc395c054349611af1c2d6d30118a`
- Pre-hardening working diff SHA-256:
  `f68893c032ff31b404478442ce52ce59cd80832ebf16d1b04985bbb9fade2252`
- Drift: present and expected. The working tree contains the uncommitted Phase 4–5
  implementation; it is the selected implementation baseline and must not be reverted.

Evidence inventory:

| Evidence | Source | What it establishes |
| --- | --- | --- |
| `E001` | `compose.yml` | Caddy is the only application container and publishes host TCP ports 80 and 443. |
| `E002` | `provisioning/roles/firewall/tasks/main.yml` | UFW currently owns host INPUT policy but has no Docker FORWARD enforcement. |
| `E003` | Docker packet-filtering documentation | Docker DNAT diverts published traffic before the UFW INPUT/OUTPUT chains. |
| `E004` | Docker iptables documentation | `DOCKER-USER` is the supported pre-Docker-rules enforcement hook; original host ports require conntrack matching after DNAT. |
| `E005` | Docker port-publishing documentation | Unqualified published ports bind to all host addresses; user-defined bridges can default to loopback. |
| `E006` | Docker nftables documentation | The nftables backend has no `DOCKER-USER` chain and remains experimental in the inspected documentation. |
| `E007` | `chaifeng/ufw-docker` README | A UFW after-rules integration is viable, but the generic third-party policy contains broader behavior than this single-service host needs. |

Primary external sources were inspected read-only on 2026-08-24:

- <https://docs.docker.com/engine/network/packet-filtering-firewalls/>
- <https://docs.docker.com/engine/network/firewall-iptables/>
- <https://docs.docker.com/engine/network/port-publishing/>
- <https://docs.docker.com/engine/network/firewall-nftables/>
- <https://github.com/chaifeng/ufw-docker>

No Codex Security scan or vulnerability finding is attached. This analysis is bound
to the repository snapshot and the documented upstream behavior above.
