# Implementation Plan: Native Docker ingress policy

## Selected Design And Constraints

The selected design uses UFW for host INPUT and an Ansible-owned `DOCKER-USER`
policy for Docker bridge FORWARD traffic. Docker retains NAT/firewall management,
uses its iptables backend, disables direct routing and defaults unqualified
user-defined bridge publications to `127.0.0.1`. Only Caddy's original host TCP
ports 80 and 443 are explicit public exceptions.

The provider has no external firewall. The implementation must therefore fail
closed on the VPS and must not depend on external policy. Production remains out
of scope for destructive validation.

## Source Revision And Drift Check

- Baseline HEAD: `1c508c4c532cc395c054349611af1c2d6d30118a`.
- Selected pre-hardening working diff:
  `sha256:f68893c032ff31b404478442ce52ce59cd80832ebf16d1b04985bbb9fade2252`.
- Drift status: expected uncommitted Phase 4–5 changes are present. Preserve them;
  stop and refresh this plan if HEAD or the Docker/UFW/Compose boundary changes.

## Affected Components

- `docs/ansible-provisioning-plan.md`
- `provisioning/roles/firewall/`
- `provisioning/roles/docker/`
- `provisioning/playbooks/deploy.yml`
- `provisioning/molecule/default/`
- `compose.yml`
- `tests/test_repository.py`
- provisioning and VPS documentation

## Ordered Work Packages

1. Record the architecture and provider-firewall constraint before code.
2. Add firewall templates and testinfra assertions before implementation:
   candidate restore validation, exact IPv4/IPv6 named chains, original host-port
   matches, default Docker-bridge drop and invalid-template rejection.
3. Implement the firewall block so validation precedes the UFW file mutation and
   reload; reject unmanaged overlapping blocks or chains.
4. Add the Docker role contract before tasks: supported OS/architecture mapping,
   official repository/key, exact packages, daemon policy, service/socket/version
   checks and unmanaged-install refusal.
5. Write the management marker, validated firewall policy and `daemon.json` before
   Docker package installation can start the daemon.
6. Install Docker from its official deb822 repository, enable/start it, verify the
   effective backend/default bind/direct-routing state and exact policy persistence.
7. Make Caddy's 80/443 public mappings explicit and reject prohibited networking,
   unexpected published ports and Docker socket mounts through repository tests.
8. Exercise converge/idempotence, invalid candidates, UFW reload and Docker restart;
   document every local PASS/RED transition in the main plan.
9. Run final lint, pytest, Molecule, Compose config, runtime smoke and diff-check.
10. Leave external sentinel, reboot, systemd ordering and IPv4/IPv6 port-scan E2E
    open until a disposable VM/VPS exists.

## Local Implementation Status

Completed on 2026-08-25:

- exact IPv4/IPv6 UFW after-rules validate before file mutation;
- invalid candidates preserve the prior file and active chain;
- Docker clean-host adoption refuses unmarked packages, binaries, sources and
  daemon configuration without deleting them;
- official signing key SHA-256
  `1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570`
  and fingerprint `9DC858229FC7DD38854AE2D88D81803C0EBFCD88` are pinned;
- daemon configuration fixes iptables backend, disables direct routing and makes
  unqualified user-defined bridge publications loopback-only;
- Compose declares only explicit public IPv4 TCP 80/443;
- privileged Debian 12 Molecule starts nested Docker and verifies actual default
  bind, UFW reload, Docker restart, exact chains, idempotence and rejection paths.

Intentionally open: systemd boot evidence, Debian 13 and Ubuntu matrix, external
sentinel/port scans, enabled public IPv6 and reboot. Those require a disposable
VM/VPS and are not inferred from container tests.

## Compatibility And Migration

Supported targets remain Debian 12/13 and Ubuntu 22.04/24.04/26.04 on amd64/arm64.
The role may adopt only a clean host or its own management marker. A pre-existing
Docker binary/package, foreign apt source, foreign daemon configuration or unmanaged
`DOCKER-USER` rules causes a read-only diagnostic failure; nothing is removed.

The selected iptables backend includes distributions whose `iptables` command is
implemented by the nft compatibility layer. Native Docker nftables backend is not
enabled by this plan and requires a new design because it has no `DOCKER-USER` hook.

## Tactical Protections During Migration

- Keep the current UFW deny-in policy and SSH-first enable ordering.
- Keep the managed user outside the `docker` group.
- Do not install Docker until the candidate forwarding policy and daemon file pass
  validation.
- Do not start a public Compose project until effective Docker policy checks pass.
- Preserve only TCP 80/443 mappings; never restore UDP 443.
- Reject rather than normalize unknown host firewall or Docker state.

## Tests And Security Validation

Local/static acceptance:

- `make lint`, `make test`, `git diff --check`;
- Compose config has exactly public TCP 80/443 and no UDP/host/macvlan/ipvlan mode;
- Docker daemon JSON parses and expresses the selected backend/defaults;
- role argument specs and no-secret policies pass.

Molecule/testinfra acceptance:

- candidate IPv4/IPv6 restore syntax validates before the UFW file changes;
- invalid candidate leaves the last valid file and active rules intact;
- Docker official packages, Compose v2 and root-owned socket exist;
- managed user is not in `docker`;
- `DOCKER-USER` jumps once to the managed chain;
- managed chain order is established return, original 80/443 return, Docker-bridge
  drop, final return;
- second converge, UFW reload and Docker restart retain exact rules without changes.

Disposable acceptance:

- external SSH remains available;
- public 80/443 stay reachable and existing runtime smoke passes;
- explicit sentinel `0.0.0.0:18080:443` is locally reachable and externally closed;
- container egress works;
- IPv6 repeats the same assertions when enabled;
- all assertions survive reboot.

## Performance And Resource Benchmarks

No measured overhead is claimed. The only packet-path addition is a short kernel
chain and conntrack original-port match for new Docker ingress. On the disposable
host, compare existing authenticated CONNECT smoke latency and sustained transfer
throughput before/after. Investigate if median latency changes beyond test noise or
throughput drops materially; do not waive the original-port match merely to improve
an unconfirmed benchmark.

## Rollout And Rollback

Rollout is ordered firewall candidate → UFW reload → daemon config → Docker install
or restart → effective verification → Compose. Each step stops on failure.

Rollback requires stopping the Compose project first. Then remove only the managed
UFW blocks, reload UFW, restore the reviewed daemon configuration and restart Docker.
Verify no public container listener remains before removing the managed forwarding
policy. Never roll back the policy while public Docker mappings are active.

## Acceptance Criteria

- Every local/static and Molecule assertion above passes.
- No secret, key or credential appears in Git, argv, environment or task logs.
- The production VPS was not contacted during local implementation.
- Gates 5–6 remain open until disposable external/reboot evidence exists.
- No commit, push or PR occurs without separate authorization.

## Resolved And Open Decisions

- The official signing-key checksum and fingerprint are pinned above. Docker deb
  package names are exact, but versions intentionally use `state: present` from
  Docker's signed stable repository so security updates are not frozen; installed
  versions must be captured in disposable deployment evidence.
- IPv6 remains not explicitly published by Compose. The disposable OS/network
  matrix determines whether public IPv6 can be accepted later.
