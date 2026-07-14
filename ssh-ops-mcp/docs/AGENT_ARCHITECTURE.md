# Network Automation Agent — Architecture Sketch

A design for an agent that turns high-level intent ("create VLAN 40 for IoT")
into concrete, multi-system changes — IOS-XE switch config, ISC DHCP scopes, and
DNS records — with **human approval before any write**, safe rollback, and a full
audit trail. It builds on the existing read-only `ssh-ops` MCP.

## Design principles

1. **Intent in, artifacts out.** The human states *what* they want; the agent
   produces the exact configs and shows them before touching anything.
2. **Reads are free, writes are gated.** Every mutating action passes through a
   human approval queue that the agent cannot bypass or self-approve.
3. **Safe by default.** Back up first, push with an auto-rollback timer, canary
   one device, verify, then commit and save. Never save an unverified change.
4. **Single source of truth.** A built-in IPAM prevents overlapping subnets /
   duplicate VLANs and records every allocation.
5. **Everything is reversible and audited.** Each change carries its own rollback
   plan; every propose / approve / apply / verify / rollback is logged.
6. **Idempotent.** Re-running the same intent is a no-op if already in place.

## High-level architecture

```
                      ┌──────────────────────────────────────────────┐
   human intent  ───► │  AGENT (LLM + orchestration)                  │
  "new VLAN 40"       │                                              │
                      │  ┌────────┐  ┌─────────┐  ┌───────────────┐  │
                      │  │ Intent │─►│ Planner │─►│ Policy /       │  │
                      │  │ parser │  │ +render │  │ guardrails+lint│  │
                      │  └────────┘  └────┬────┘  └───────┬───────┘  │
                      └───────────────────┼───────────────┼──────────┘
                                          │ proposes      │ validates against
                                          ▼               ▼
        ┌──────────────┐          ┌───────────────┐   ┌────────────┐
        │  IPAM store  │◄────────►│ Change store  │   │  Inventory │
        │ (YAML/SQLite)│  reserve │ (pending/     │   │ hosts.yaml │
        └──────────────┘          │  approved/... │   └────────────┘
                                  └──────┬────────┘
                                         │  ┌─────────────────────────┐
                       HUMAN APPROVAL ──►│  │ Web GUI: "Pending        │
                       (Approve/Reject)  │  │ changes" — shows diffs   │
                                         │  └─────────────────────────┘
                                         ▼ (status = approved)
                      ┌──────────────────────────────────────────────┐
                      │  EXECUTOR (per-target adapters)               │
                      │   IOS-XE (netmiko)   ISC DHCP    DNS          │
                      │   backup → push →    validate →  render →     │
                      │   commit-confirmed   dhcpd -t →  reload →     │
                      │   → verify → save    reload      verify       │
                      └───────────────────┬──────────────────────────┘
                                          ▼
                                  Verify + (rollback on failure) + Audit log
```

The agent proposes; a human approves in the GUI; the executor applies with
safety nets. The agent never writes directly to a device.

## The Change lifecycle

A **Change** is the unit of work. It moves through explicit states:

```
proposed ──► approved ──► applying ──► verifying ──► applied
    │            │            │             │
    │ (reject)   │            │ (verify fail / lockout)
    ▼            ▼            ▼             ▼
 rejected     expired     rolling_back ──► rolled_back / failed
```

- **proposed** — rendered artifacts + rollback plan + risk score exist; nothing
  applied. IPAM allocations are *reserved* (not committed).
- **approved** — a human clicked Approve in the GUI. Only now can it apply.
- **applying / verifying** — executor working; auto-rollback timer armed.
- **applied** — verified good, configs saved, IPAM reservation committed.
- **rolled_back / failed** — restored to pre-change state; IPAM reservation freed.
- **expired** — approval not granted within a TTL (e.g. 24h) → auto-void.

## Walkthrough: "Create VLAN 40 (IoT), 10.40.0.0/24"

**1. Intent** (chat or structured):
> "New VLAN 40 named IoT, subnet 10.40.0.0/24, gateway .1, DHCP .50–.200,
> DNS 10.0.0.53, domain iot.lab, relay via 10.0.0.10, trunk to access switches."

**2. Plan + render.** The agent checks IPAM (VLAN 40 free? subnet non-overlapping?),
reserves the allocation, and renders per-target artifacts:

*IOS-XE (core L3 + each access switch):*
```
vlan 40
 name IoT
!
interface Vlan40                      ! core/L3 only
 description IoT gateway
 ip address 10.40.0.1 255.255.255.0
 ip helper-address 10.0.0.10
 no shutdown
!
interface range Gi1/0/48              ! uplinks/trunks only
 switchport trunk allowed vlan add 40
```

*ISC DHCP — `/etc/dhcp/dhcpd.d/vlan40.conf`:*
```
subnet 10.40.0.0 netmask 255.255.255.0 {
  option routers            10.40.0.1;
  option domain-name-servers 10.0.0.53;
  option domain-name        "iot.lab";
  range 10.40.0.50 10.40.0.200;
  default-lease-time 3600; max-lease-time 86400;
}
```

*DNS — forward `iot.lab` + reverse `40.10.in-addr.arpa`:* gateway A/PTR, zone
serial bump.

Each artifact ships with its **rollback** (e.g. `no vlan 40`, delete the include
file, revert the zone serial).

**3. Guardrails/lint.** Subnet-overlap check (IPAM), VLAN in allowed range, naming
convention, protected-interface check (won't touch uplinks not in scope), offline
CLI lint, `dhcpd -t` on a rendered candidate, DNS zone syntax check. Risk scored
(multi-device + L3 change ⇒ *medium*).

**4. Approval.** Change appears on the GUI **Pending changes** page with the full
rendered diff per target and the rollback plan. Human reviews and clicks
**Approve** (or Reject with a note). Status → approved. *The agent cannot do this
step.*

**5. Apply (canary + commit-confirmed).**
- **Backup** running-config of each switch; copy of dhcpd.d + zone files.
- **Canary:** apply to one access switch first. Push with an auto-rollback timer
  (`reload in 5` deadman, or `configure replace` rollback point). Verify
  reachability + `show vlan brief | include 40`. If good, cancel the timer.
- **Fan out** to remaining switches; then DHCP (write include → `dhcpd -t` →
  `systemctl reload isc-dhcp-server`) → DNS (render → `named-checkzone` →
  `rndc reload`).

**6. Verify.** `show vlan brief`, `show ip interface brief | include Vlan40`, ping
the SVI, `systemctl is-active isc-dhcp-server`, optional DHCP test lease, `dig`
the new record. All green ⇒ `write memory` on switches, commit IPAM.

**7. On any failure** ⇒ auto-rollback everything applied so far, free the IPAM
reservation, mark failed, surface logs. Nothing half-applied is left saved.

## Components

### Inventory & IPAM (built-in, YAML → SQLite)
Reuses `hosts.yaml` for device inventory. Adds an IPAM store — start as YAML,
migrate to SQLite when concurrency/locking matters:
```yaml
vlans:
  40: { name: IoT, subnet: 10.40.0.0/24, gateway: 10.40.0.1, domain: iot.lab,
        dhcp_range: [10.40.0.50, 10.40.0.200], status: active, change_id: chg-0007 }
allocations:
  10.40.0.10: { host: printer-iot-1, type: static }
```
Responsibilities: allocate/reserve/free VLAN IDs and subnets, detect overlaps,
answer "what's free," and hold the authoritative post-change state.

### Intent parser
Turns NL or a form into a structured `ChangeSpec` (vlan id, name, subnet, gw,
dhcp range, dns, targets). Ambiguity ⇒ ask the human. Deterministic schema so the
planner is testable.

### Planner + renderers (per system)
One renderer per target type, each pure (spec → artifact + rollback), so they're
unit-testable offline with golden files:
- `render_iosxe(spec, device_role)` → CLI config-set + rollback set.
- `render_iscdhcp(spec)` → include-file content + rollback.
- `render_dns(spec)` → zone records (fwd + reverse) + rollback.
Templates (Jinja) keyed by device role (core vs access) and platform.

### Policy / guardrails
Declarative rules evaluated before approval: allowed VLAN/subnet ranges, naming
regex, protected devices/interfaces (never modify), max blast radius per change,
change-freeze windows, and required syntax/lint passes. A failing rule blocks the
proposal from ever reaching the queue.

### Approval queue (extends the existing Flask GUI)
New **Pending changes** page: lists proposed changes with rendered diffs, risk,
and rollback preview; Approve / Reject buttons write the decision (who/when/why)
into the change store. Approval is the *only* path to `approved`, enforced server
-side — the MCP `apply` tool refuses anything not in `approved` state. Optional
tiering: low-risk auto-eligible for chat approval, high-risk GUI-only.

### Executor (per-target adapters, safety-first)
- **IOS-XE:** netmiko `send_config_set`; backup via `show run` / `archive`;
  safety net = `reload in N` deadman **or** `configure replace` rollback point;
  `write memory` only after verification. Canary-first ordering.
- **ISC DHCP:** write a per-VLAN include (clean diffs), `dhcpd -t` before reload,
  graceful `systemctl reload`; respect DHCP failover peers.
- **DNS:** render zone delta, `named-checkzone` / equivalent, bump serial, reload.
Each adapter exposes `backup()`, `apply()`, `verify()`, `rollback()`.

### Verification & rollback
Verification is explicit per target (show commands, service state, ping/dig, test
lease). Rollback replays each artifact's stored inverse in reverse order. IOS-XE
deadman guarantees recovery even if a push severs management.

### Audit
Append-only log (extends the current audit log): every propose/approve/apply/
verify/rollback with actor, timestamp, change id, and artifact hashes.

## MCP tool surface

Extends the current read-only tools. Writes are two-phase and approval-gated.

*Read (exists):* `list_hosts`, `run_command` (show/diagnostic), `check_health`, …

*IPAM (read):* `ipam_lookup(vlan|subnet)`, `ipam_next_free(kind)`.

*Propose (no side effects):*
`propose_change(intent)` → renders artifacts + rollback + risk, reserves IPAM,
writes a `proposed` Change, returns `change_id` + diffs. **This is as far as the
agent gets on its own.**

*Approval (human, via GUI — not an agent tool):* Approve/Reject in the browser.
Optionally `get_change(change_id)` so the agent can poll status.

*Apply (gated):* `apply_change(change_id)` → refuses unless status == `approved`;
runs backup → canary → fan-out → verify → save, or rolls back. Returns a result
report. `rollback_change(change_id)` for manual revert of an applied change.

This split is the crux: the agent can *propose* freely, but `apply_change` is
inert until a human flips the state in the GUI.

## Change data model

```yaml
id: chg-0007
intent: "New VLAN 40 IoT 10.40.0.0/24 ..."
spec: { vlan: 40, name: IoT, subnet: 10.40.0.0/24, gateway: 10.40.0.1, ... }
risk: medium
status: proposed          # proposed|approved|rejected|applying|applied|failed|rolled_back|expired
created_by: agent
created_at: 2026-06-30T22:10:00Z
approvals: []             # [{user, decision, note, ts}]
targets:
  - name: sw-access-1
    type: cisco_ios
    role: access
    apply:    ["vlan 40", " name IoT", "interface Gi1/0/48", "  switchport trunk allowed vlan add 40"]
    rollback: ["no vlan 40", "interface Gi1/0/48", "  switchport trunk allowed vlan remove 40"]
    verify:   ["show vlan brief | include 40"]
  - name: dhcp-1
    type: linux
    apply:    { file: /etc/dhcp/dhcpd.d/vlan40.conf, content: "subnet 10.40.0.0 ..." }
    rollback: { delete: /etc/dhcp/dhcpd.d/vlan40.conf }
    validate: "dhcpd -t"
    reload:   "systemctl reload isc-dhcp-server"
    verify:   "systemctl is-active isc-dhcp-server"
  - name: dns-1
    type: linux
    apply:    { zone_fwd: iot.lab, zone_rev: 40.10.in-addr.arpa, records: [...] }
    rollback: { restore_serial: 2026063001 }
    validate: "named-checkzone iot.lab /etc/bind/db.iot.lab"
    reload:   "rndc reload"
```

## Safety model (summary)

| Layer | Mechanism |
|-------|-----------|
| Pre-flight | IPAM overlap check, policy rules, offline lint, `dhcpd -t`, `named-checkzone` |
| Human gate | GUI approval queue; `apply` refuses non-approved changes |
| Push | Backup first; canary one device; `reload in` deadman / `configure replace` |
| Post | Explicit verification before `write memory`; auto-rollback on failure |
| After | Append-only audit; IPAM reflects only committed, verified state |

## Phased roadmap

- **Phase 0 — Foundation (done/near):** read-only `ssh-ops` MCP for Linux +
  IOS-XE, encrypted creds, GUI, hot-reload.
- **Phase 1 — Propose only (dry-run):** intent parser + renderers + IPAM +
  guardrails; `propose_change` shows diffs; **no apply**. Build confidence by
  reviewing generated configs against reality.
- **Phase 2 — Approved single-device writes:** GUI approval queue; `apply_change`
  for one target with backup + verify + rollback. Start with DHCP/DNS (easiest to
  revert), then IOS-XE with the deadman timer.
- **Phase 3 — Orchestrated multi-device:** canary + fan-out ordering, cross-system
  transaction (all-or-nothing with compensating rollback), full VLAN workflow.
- **Phase 4 — Scale & polish:** SQLite IPAM, change-freeze windows, richer risk
  scoring, optional NetBox sync, more workflows (decommission VLAN, move port,
  add static reservation).

## Open decisions

1. **DNS server**: BIND, Unbound, dnsmasq, or Windows DNS? Renderer + validate/
   reload commands differ. (v1 assumes BIND-style `named-checkzone`/`rndc`.)
2. **IOS-XE rollback method**: `reload in` deadman vs `configure replace` vs
   `commit confirmed` (config-transaction mode) — depends on your IOS-XE version;
   worth confirming what your C9300s support.
3. **DHCP failover**: single server or failover pair? Affects reload/ordering.
4. **Change TTL** and whether low-risk changes may use chat approval vs GUI-only.
5. **Who runs the agent** — the same Linux host as the MCP, and how it's triggered
   (chat, cron, webhook, ticket).
```
