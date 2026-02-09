Author: PB and Claude
Date: 2026-02-09
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/ipfs-cluster-metadata.md

# IPFS Cluster Pin Metadata: Lessons Learned

## Context

We need per-org ownership of pins in a multi-org IPFS cluster (5 orgs
sharing 5 nodes). The cluster API supports arbitrary key-value metadata
on pins, but the format is poorly documented.

## API Format Discovery

Tested against IPFS Cluster v1.1.5 (CRDT consensus) on 2026-02-09.

### Formats that DON'T work

| Attempt | Query/Body | Result |
|---------|-----------|--------|
| URL-encoded JSON | `?metadata={"org":"hrdag"}` | `metadata: null` |
| Key=value string | `?metadata=org=hrdag` | `metadata: {}` |
| JSON body POST | `-d '{"metadata":{"org":"hrdag"}}'` | **Wiped name and allocations!** |
| Hyphen prefix | `?metadata-org=hrdag` | `metadata: {}` |

### Format that WORKS

```
?meta-org=hrdag
```

Each metadata key is a separate query parameter with `meta-` prefix:
- `?meta-org=hrdag` → `{"metadata": {"org": "hrdag"}}`
- `?meta-org=hrdag&meta-env=prod` → `{"metadata": {"org": "hrdag", "env": "prod"}}`

This format works on both `/add` and `/pins/{cid}` endpoints.

### Danger: JSON body POST wipes pin state

Sending a JSON body to `POST /pins/{cid}` **replaces** the entire pin
configuration. If you only send `{"metadata": {"org": "hrdag"}}`, the
cluster interprets the missing `name` and `allocations` fields as empty,
effectively wiping them. Always use query parameters.

## Metadata Persistence

- Metadata persists across cluster restarts (stored in CRDT datastore)
- Visible in `/pins` NDJSON listing and `/allocations` endpoint
- Preserved through re-pins (if passed again via query params)
- NOT preserved automatically — a `POST /pins/{cid}` without `meta-`
  params will clear existing metadata

## Migration Performance

Tagged 3512 existing pins with `meta-org=hrdag`:

| Pass | Pins Tagged | Time | Rate |
|------|------------|------|------|
| 1st | 3510 | 109s | 32 pins/sec |
| 2nd | 127 | 6.7s | 19 pins/sec |
| 3rd | 0 | 2.5s | (verification only) |

### CRDT Convergence Lag

The cluster uses CRDT consensus (not Raft). After rapid re-pinning:
- Immediate read showed only 2749/3512 tagged (22% lag)
- After ~10s: 3139/3512 tagged
- After ~20s + 2nd pass: 3385/3512
- After ~30s + 3rd pass: 3512/3512 (fully converged)

**Lesson**: When bulk-modifying pins, run multiple passes with short
delays rather than assuming a single pass is sufficient. The `tag_pins()`
function is idempotent — re-running is safe and catches stragglers.

## Implementation

### Query parameter construction

```python
# In _build_add_params() and pin():
if metadata:
    for key, value in metadata.items():
        params[f"meta-{key}"] = value
```

Uses `urllib.parse.urlencode()` which handles special characters correctly.

### Automatic tagging on add

Every `operations.add()` call now passes `metadata={"org": profile}`:

```python
entries_raw = client.add(
    path,
    name=path.name,
    allocations=allocations,
    metadata={"org": profile},
)
```

### Migration function

`tag_pins(profile, config, dry_run=False)` for one-time migration:
- Reads all pins via `client.pins()`
- Skips pins already tagged with correct org
- Re-pins untagged pins with `meta-org=<profile>`
- Idempotent — safe to re-run
- Supports `dry_run=True` for preview

## Open Questions

1. **Multi-org tagging**: When other orgs join, their pins will need
   separate `tag_pins` runs with their profile name. Current code only
   tags pins that have NO org metadata — it won't re-tag pins already
   claimed by another org.

2. **Metadata on re-pin**: When `ensure_pins` or future `rebalance`
   re-pins a CID to fix allocations, it must pass the existing metadata
   through, or it will be lost. This is not yet implemented in
   `ensure_pins`.
