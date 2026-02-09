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

Every `operations.add()` call now passes both org and size metadata:

```python
metadata={"org": profile, "size": str(content_size)},
```

Size is calculated before upload: `path.stat().st_size` for files,
`sum(f.stat().st_size for f in path.rglob("*") if f.is_file())` for directories.

### Migration function

`tag_pins(profile, config, dry_run=False)` for one-time migration:
- Reads all pins via `client.pins()`
- Skips pins that already have both correct org AND size
- Fetches size via IPFS gateway dag-json endpoint (see below)
- Re-pins with `meta-org=<profile>&meta-size=<bytes>`
- Idempotent — safe to re-run
- Supports `dry_run=True` for preview
- Gracefully handles unretrievable pins (tags org only, skips size)

## Pin Size Discovery

### How to get pin sizes

The IPFS Cluster API does not expose pin sizes. The IPFS API (port 5001)
is not accessible from the tailnet. The IPFS gateway (port 8080) provides
size data via dag-json format:

```
GET http://<node>:8080/ipfs/{cid}?format=dag-json
```

Returns JSON with a `Links` array, each link having a `Tsize` field
(cumulative DAG size). Summing `Tsize` across links gives total pin size.

### Performance

- ~50ms per pin (gateway lookup)
- 3512 pins: ~250s dry-run, ~325s live (with re-pin overhead)
- Size range: 65 MB to 1.08 GB per commit-level pin

### Implementation

```python
def _get_dag_size(gateway_host: str, cid: str) -> int | None:
    resp = requests.get(
        f"http://{gateway_host}:8080/ipfs/{cid}?format=dag-json",
        timeout=10,
    )
    data = resp.json()
    return sum(link.get("Tsize", 0) for link in data.get("Links", []))
```

Returns `None` on any error (timeout, unretrievable CID, etc.).

## Size Migration Performance

Tagged 3512 existing pins with `meta-org=hrdag&meta-size=<bytes>`:

| Pass | Pins Tagged | Time | Rate |
|------|------------|------|------|
| 1st | 3512 | 323s | 10.9 pins/sec |
| 2nd | 2 | 5s | (CRDT stragglers) |
| 3rd | 1 | 5s | (CRDT straggler) |
| 4th | 0 | 2.5s | (verified) |

One pin (`QmYxsvAMjht8...`) could not be sized — gateway timeout due to
`pin_error` on the serving node. It was tagged with org only (no size).
This pin was later recovered with `ccs repair`.

## Repair: Recovering Broken Pins

The `ccs repair` command detects pins with `pin_error` status and triggers
cluster-native recovery via `POST /pins/{cid}/recover`. This endpoint
retries using existing allocations — no re-pin needed, so allocations,
name, and metadata are all preserved automatically.

```bash
ccs repair --dry-run    # preview
ccs repair              # trigger recovery
ccs repair --json       # machine-readable output
```

Exit codes: 0=clean, 1=broken pins recovered, 2=lost pins (no node has data).

## Open Questions

1. **Multi-org tagging**: When other orgs join, their pins will need
   separate `tag_pins` runs with their profile name. Current code only
   tags pins that have NO org metadata — it won't re-tag pins already
   claimed by another org.

2. **Metadata on re-pin**: `ensure_pins` does not yet preserve metadata
   when re-pinning to fix allocations. The `ccs repair` command avoids
   this issue by using the recover endpoint (which preserves everything),
   but `ensure_pins` and the future `rebalance` command need
   read-merge-write to preserve metadata.
