# Security Hardening Review: Docker ingress on the VPS

## Evidence Basis

We inspected the current Compose publication, Phase 5 UFW role and Docker's
documented packet path. The repository does not currently publish an unexpected
port, but UFW alone cannot preserve that invariant once Docker bridge port
publishing is enabled. The detailed evidence map is in [context.md](context.md).

## Constraints

- The VPS provider supplies no external firewall.
- Enforcement must therefore be complete inside the VPS.
- Docker bridge isolation, client source addresses and the existing Caddy data
  path must be preserved.
- All VPS mutations remain owned by Ansible; no downloaded root script is run.
- Production is not a test target. Reconnect, reboot and external negative scans
  require a disposable VM/VPS.

## Opportunity Portfolio

| Opportunity | Evidence | Options | Recommendation | Proposal |
| --- | --- | --- | --- | --- |
| Make Docker ingress fail closed on the host | Docker/UFW bypass and current public Compose mappings (`E001`–`E007`) | UFW only; third-party ufw-docker; localhost proxy; native Ansible-owned `DOCKER-USER` | Native `DOCKER-USER` plus loopback-safe publication defaults | [Docker ingress enforcement](proposals/docker-ingress-enforcement.md) |

## Recommendation Summary

We selected the native policy because it preserves the current bridge network and
client IPs while moving the missing authorization check to Docker's supported
pre-forwarding hook. UFW continues to own host INPUT. Ansible owns an exact
`DOCKER-USER` policy that permits established flows and only original host TCP
ports 80/443 to Docker bridges, then drops other ingress. Docker keeps its own
firewall enabled, uses the iptables backend, disables direct routing and defaults
unqualified publications to loopback.

This does not claim the boundary is accepted on a real kernel yet. Local static and
Molecule evidence must be followed by disposable external sentinel-port tests,
Docker/UFW restarts and reboot.

## Next Decisions

The design is selected. The ordered implementation, rollback and acceptance
criteria are in [implementation/native-docker-user.md](implementation/native-docker-user.md).
