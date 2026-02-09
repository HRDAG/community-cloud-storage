Author: PB and Claude
Date: 2026-02-09
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/RUNBOOK.md

# CCS Cluster Runbook

Operational log for the CCS cluster. Entries in reverse chronological order.
For diagnostic procedures and architecture details, see [REFERENCE.md](REFERENCE.md).

## ENTRY-0004: Broken pin recovery (2026-02-09)

**Type:** maintenance
**Nodes:** all
**Status:** resolved

Pin `QmYxsvAMjht8hoKgVbpkm3t8G1qC2ht1992vatGUJm3BEY` (`commit_2026-01-15T22:33:33Z`)
had `pin_error: "context canceled"` on chll, `pin_queued` on pihost/ipfs1, `remote`
on nas/meerkat. Gateway size lookup timed out because no allocated node had it pinned.

Used new `ccs repair` command which calls `POST /pins/{cid}/recover`. After recovery,
chll status changed to `pinning` (attempt_count=61), and subsequent `ccs repair`
showed 0 broken pins.

## ENTRY-0003: Org and size metadata migration (2026-02-09)

**Type:** migration
**Nodes:** all
**Status:** resolved

Tagged all 3513 hrdag pins with `meta-org=hrdag` and `meta-size=<bytes>` using
`tag_pins()`. Org tagging: 3510 pins in 109s (~32 pins/sec), 3 CRDT convergence
passes needed. Size tagging: 3512 pins in 323s (~10.9 pins/sec, limited by
gateway dag-json lookups at ~50ms each). One pin could not be sized due to
`pin_error` (recovered in ENTRY-0004). New `add()` operations automatically
include both org and size metadata.

## ENTRY-0002: pihost disk replacement — IronWolf Pro 24TB (2026-02-09)

**Type:** maintenance
**Nodes:** pihost
**Status:** resolved

Replaced full 8TB disk with Seagate IronWolf Pro 24TB. Node rejoined cluster
with new peer ID `12D3KooWPmLpuSUXTB7v2dn8zwGUYx5ftBsY6GQuHXo2RrTKA4ow`
(new IPFS peer ID `12D3KooWG3YEXiawSW9vFybcXmzrcEBTa5DXTzABGUUHz9Sb73Yb`).
Now reporting 18.19 TB free. Config updated in `/etc/tfc/ccs.toml`.
16 orphaned pins remain allocated to old pihost peer ID — to be cleaned up
during rebalance.

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
