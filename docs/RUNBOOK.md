Author: PB and Claude
Date: 2026-02-09
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/RUNBOOK.md

# CCS Cluster Runbook

Operational log for the CCS cluster. Entries in reverse chronological order.
For diagnostic procedures and architecture details, see [REFERENCE.md](REFERENCE.md).

## ENTRY-0002: pihost disk replacement — IronWolf Pro 24TB (2026-02-09)

**Type:** maintenance
**Nodes:** pihost
**Status:** ongoing

Replacing the full 8TB disk on pihost with a Seagate IronWolf Pro 24TB.
Follow the disk replacement procedure in REFERENCE.md. After swap, verify
cluster rejoins and pins are intact with `uv run ccs peers` and
`uv run ccs status`.

## ENTRY-0001: pihost disk full + ipfs1 offline (2026-02-08)

**Type:** incident
**Nodes:** pihost, ipfs1
**Status:** resolved

### pihost (100.64.0.2)
- Machine up (ping OK), port 9094 connection refused
- Container `ccs-cluster` in restart loop: **disk quota exceeded**
- `/mnt/sda1` at 99% (7.2T/7.3T) — only 1TB is CCS, rest is other data
- Not in any peer's `cluster_peers` list
- **Fix**: free space on /mnt/sda1, container will auto-restart

### ipfs1 (100.64.0.51)
- Machine offline (Tailscale ping fails, port 9094 timeout)
- Cluster remembers peer ID `12D3KooWEa7paY...` at this IP
- Config has different peer_id `12D3KooWFdQri2...` (stale — container was recreated)
- **Fix**: power on machine, update peer_id in config after verifying actual ID
