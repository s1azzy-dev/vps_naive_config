# Security Hardening Proposal: Enforce Docker ingress inside the VPS

## Decision

Selected: **Option 4, native Ansible-owned `DOCKER-USER` policy with loopback-safe
Docker publication defaults**.

## Executive Recommendation

We considered four materially different choices: **Option 1, keep UFW-only**;
**Option 2, install `ufw-docker`**; **Option 3, publish only to localhost behind a
host TCP proxy**; and **Option 4, own a minimal native `DOCKER-USER` policy**.

I recommend and the owner selected Option 4. It adds the missing enforcement at
the forwarding boundary Docker documents for user policy, keeps Docker's network
management enabled, preserves Caddy's client addresses and does not introduce a
second proxy or a downloaded privileged script. We combine it with a loopback
default so an abbreviated future `ports` declaration is non-public even before
the forwarding allowlist is considered.

## Evidence

I inspected the current repository and the upstream packet-filtering contracts.
The decisive evidence is not an observed unexpected open port; it is the structural
gap between the UFW INPUT owner and Docker's FORWARD/NAT owner.

| Evidence | Finding or document | What it establishes |
| --- | --- | --- |
| `E001` | Current `compose.yml` | Only Caddy TCP 80/443 is intentionally published today. |
| `E002` | Current firewall role | UFW has an exact host allowlist but no Docker forwarding policy. |
| `E003` | Docker and UFW documentation | Docker-published traffic is diverted before UFW INPUT/OUTPUT processing. |
| `E004` | Docker iptables documentation | `DOCKER-USER` runs before Docker accept rules; original ports require conntrack after DNAT. |
| `E005` | Docker publishing documentation | Missing host IP publishes broadly; bridge defaults can make it loopback-only. |
| `E006` | Docker nftables documentation | The inspected nftables backend is experimental and has no `DOCKER-USER`. |
| `E007` | `ufw-docker` design | UFW after-rules can populate `DOCKER-USER`, but its generic policy and installer exceed this host's needs. |

## Current Design And Failure Mode

Observed: `compose.yml` maps only `80:80/tcp` and `443:443/tcp`. UFW allows the
same host ports and SSH. The managed user is intentionally excluded from the
`docker` group.

Inferred: those controls reduce today's attack surface but do not make the port
allowlist system-wide. A later root-owned Compose file can publish another port,
and Docker can accept it in FORWARD after DNAT without traversing UFW INPUT. The
same drift can occur accidentally through a shorthand mapping or a new container.
Without a provider firewall, no independent outer policy catches that mistake.

The current trust boundary is shown in
[the before diagram](../diagrams/docker-ingress-enforcement-before.mmd). UFW and
Docker each behave as designed; the missing property is a shared deny-by-default
decision for traffic forwarded into Docker bridges.

## Desired Invariants

- Untrusted ingress can reach host SSH only on configured `VPS_PORT/tcp`.
- Untrusted ingress can reach Docker bridges only when the original host
  destination is `80/tcp` or `443/tcp`.
- A mapping such as `0.0.0.0:18080:443` remains externally blocked even though
  its post-DNAT container port is 443.
- Established return traffic and new container egress continue to work.
- Unqualified future Docker publications bind to loopback.
- Docker keeps its firewall/NAT management enabled.
- IPv6 is either covered by an equivalent policy or not publicly published.
- `network_mode: host`, macvlan, ipvlan, Swarm, direct routing and application
  Docker-socket mounts cannot silently bypass the reviewed boundary.
- Candidate firewall syntax is validated before reload; second converge, UFW
  reload, Docker restart and reboot do not duplicate or remove enforcement.

## Constraints And Non-Goals

The VPS provider offers no external firewall. This design cannot defend against
an attacker who already controls host root or the Docker daemon; both can rewrite
the same kernel policy. We are preventing deployment drift and containment loss,
not replacing host compromise recovery.

We preserve bridge networking and the direct Caddy TCP path. We do not introduce
Swarm, Kubernetes, a host reverse proxy, dynamic per-container policy or a general
multi-tenant firewall manager.

## Before Architecture

[Before architecture](../diagrams/docker-ingress-enforcement-before.mmd) shows
two policy paths: host sockets traverse UFW INPUT, while Docker-published traffic
is DNATed and accepted through Docker-owned forwarding rules. The cost is low,
but a future publication becomes public by declaration rather than by an
independent allowlist decision.

## Options

### Option 1: Keep UFW-only enforcement

This option preserves all current code and operations. It is attractive only if
Docker is never installed or port publication is treated as a sufficient security
decision by itself. That premise conflicts with the requested fail-closed posture.

[UFW-only architecture](../diagrams/docker-ingress-enforcement-ufw-only-after.mmd)
still leaves Docker forwarding outside the host allowlist. Performance, memory and
reliability are unchanged, but recurrence risk remains entirely procedural.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Docker forwarding policy | None | None | Unexpected published ports remain public | None |
| Safe publication default | Broad bind | Broad bind | Shorthand mappings remain externally reachable | None |

### Option 2: Install third-party `ufw-docker`

`ufw-docker` demonstrates a workable integration: it adds UFW forwarding hooks to
`DOCKER-USER` while leaving Docker iptables enabled. It is a reasonable choice for
operators who want its per-container CLI and accept an additional privileged tool.

[The ufw-docker architecture](../diagrams/docker-ingress-enforcement-ufw-docker-after.mmd)
would solve the main bypass, but it brings generic RFC1918/subnet behavior,
container-IP lifecycle handling and a root script that must be separately pinned,
audited and upgraded. For one fixed public container, that is avoidable policy
surface. Rollback also depends on its installer conventions.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Forward enforcement | None | Third-party UFW integration | Docker ingress becomes policy-controlled | New privileged dependency |
| Policy ownership | Repository | External project plus repository | Faster adoption, more supply-chain and drift surface | Pinning, audit and upgrade work |

### Option 3: Localhost publication behind a host TCP proxy

This option moves public termination back to host sockets: a systemd-managed TCP
proxy listens on 80/443 and forwards bytes to loopback-only Docker mappings. UFW
INPUT then becomes authoritative without Docker forwarding policy.

[The localhost-proxy architecture](../diagrams/docker-ingress-enforcement-localhost-proxy-after.mmd)
has a clean firewall story and becomes preferable if Docker firewall hooks cannot
be supported on a future backend. What gives us pause is the extra availability
dependency and loss of original client addresses unless we introduce and configure
PROXY protocol support. It also creates another component on the TLS/CONNECT data
path and a separate health/restart contract.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Public listener | Docker publication | Host proxy | UFW INPUT owns all public ingress | Extra process and unit |
| Client address | Preserved | Usually becomes host address | Reduces logging and future source-aware controls | Protocol/config redesign to preserve it |

### Option 4: Native Ansible-owned `DOCKER-USER` policy

This option keeps UFW responsible for host INPUT and adds an exact repository-owned
forward policy before Docker's accept rules. Ansible templates the IPv4/IPv6
candidate blocks, validates them with restore test mode, and lets UFW load them
before Docker starts. The policy returns established flows, returns new flows only
when conntrack reports original host TCP port 80 or 443 and the egress interface is
a Docker bridge, drops other Docker-bridge ingress, then returns non-Docker traffic.

[The selected architecture](../diagrams/docker-ingress-enforcement-native-docker-user-after.mmd)
preserves the packet path and client IP. Matching original ports adds conntrack
work to new connections, not an additional userspace hop; the actual throughput
effect is unmeasured and must be checked against the runtime smoke workload. The
policy deliberately owns its named chains and rejects unmanaged overlap rather
than silently deleting another operator's rules.

Docker remains responsible for NAT and bridge isolation. Before its first start,
Ansible configures the iptables firewall backend, disables direct routing and sets
the default bind for user-defined bridge publications to `127.0.0.1`. Caddy's
80/443 mappings become explicit public exceptions. This gives us two independent
guards against an accidental new mapping.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Docker ingress decision | Docker publication alone | Exact pre-Docker allowlist | Unexpected public mappings fail closed | Managed restore rules and tests |
| Original port identity | Lost after DNAT | Checked with conntrack | `18080:443` cannot inherit the 443 exception | Small unmeasured new-flow lookup cost |
| Publication default | All host addresses | Loopback | Shorthand mappings are non-public | Intended services require explicit bind |
| Backend scope | Implicit Docker default | Pinned iptables backend | Stable `DOCKER-USER` hook | Future nftables migration requires redesign |

## Comparison

| Option | Security | Performance | Memory | Reliability | Operability | Migration |
| --- | --- | --- | --- | --- | --- | --- |
| 1. UFW only | No structural improvement | Neutral | Neutral | Neutral | Simplest | None |
| 2. ufw-docker | Improves; generic policy remains | Near-neutral, unmeasured | Neutral | Adds external lifecycle | New privileged dependency | Moderate |
| 3. Localhost proxy | Strong single INPUT boundary | Extra TCP hop | Extra process/buffers | New data-path dependency | More services and health checks | High |
| 4. Native `DOCKER-USER` | Strong fixed allowlist and safe defaults | New-flow conntrack lookup, unmeasured | Neutral | Kernel path preserved; backend-coupled | Repository-owned rules and verification | Moderate |

The table does not assign a synthetic score. Option 4 is proportionate because
it closes the exact boundary without changing the application data path. Option 3
would win if preserving `DOCKER-USER` compatibility became less reliable than
operating a host proxy.

## Recommendation

We will implement Option 4. We keep the UFW host rules already tested in Phase 5,
add the Docker forwarding block before Phase 6 installs Docker, and make Docker
startup contingent on that prepared policy. We retain the existing tactical
restriction that the managed user is not in `docker` and add repository contracts
against host/macvlan/ipvlan/direct-routing/Swarm/socket-mount bypasses.

## Evidence Coverage And Residual Risk

| Evidence | Effect | Tactical protection still required |
| --- | --- | --- |
| `E001` — Current public mappings | Addresses future mapping drift while preserving 80/443 | Compose exact-port contract |
| `E002` — UFW lacks FORWARD ownership | Addresses with `DOCKER-USER` policy | Existing UFW INPUT role remains |
| `E003` — Docker bypasses UFW INPUT | Addresses at the FORWARD hook | External E2E required |
| `E004` — Supported Docker hook/original-port semantics | Uses documented hook and conntrack identity | Pin and verify backend |
| `E005` — Broad bind default | Mitigates with loopback default | Explicit Caddy binds and Compose audit |
| `E006` — nftables backend divergence | Defers by pinning iptables backend | Future migration design review |
| `E007` — Third-party integration | Avoids dependency while retaining proven mechanism | Maintain our narrower templates/tests |

Residual risk remains if host root is compromised, a prohibited network mode is
introduced outside the controlled deployment, or an upstream Docker/iptables
change invalidates ordering. A provider firewall would add independent containment
but is unavailable and therefore cannot be an acceptance dependency.

## Migration And Rollout

On a clean host we install UFW and load the validated Docker ingress block before
Docker packages. Docker daemon configuration is written before package post-install
can start the service. On an existing unknown Docker installation or unmanaged
`daemon.json`/`DOCKER-USER` state, Ansible stops without deleting or weakening it.

Rollback is fail-safe only while public containers are stopped. We stop Compose,
remove the managed after-rules blocks, reload UFW, remove the managed daemon keys
or restore the reviewed prior file, and restart Docker. Removing the forwarding
policy while public mappings run is explicitly not a safe rollback.

## Validation Plan

- Static: argument specs, Ansible syntax/lint, exact Compose and daemon contracts.
- Molecule: candidate validation, chain contents/order, idempotence, invalid-template
  rejection, UFW reload, Docker restart where container capabilities permit.
- Runtime smoke: existing TLS/HTTP2/authenticated CONNECT behavior and latency
  compared with the current local baseline; no fixed threshold is claimed yet.
- Disposable E2E: explicit `0.0.0.0:18080` sentinel is reachable locally but not
  externally; 80/443 remain reachable; repeat after reload/restart/reboot for
  IPv4 and enabled IPv6; container egress and SSH stay available.

## Implementation Work Packages

The selected ordered work, rollback and acceptance contract is maintained in
[implementation/native-docker-user.md](../implementation/native-docker-user.md).

## Open Questions

- Whether every supported provider image exposes Docker bridges through the same
  iptables-nft behavior must be answered by the OS E2E matrix.
- Public IPv6 must be tested explicitly when a valid AAAA record is configured;
  otherwise deployment must not publish an unverified IPv6 listener.
