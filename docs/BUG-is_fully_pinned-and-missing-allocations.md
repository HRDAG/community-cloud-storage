# Author: PB and Claude
# Date: 2026-01-15
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# community-cloud-storage/docs/BUG-is_fully_pinned-and-missing-allocations.md

# Bug Report: `is_fully_pinned()` Returns True When Nothing is Pinned

## Summary

Two related issues discovered during ntx verification testing:

1. **`PinStatus.is_fully_pinned()` returns True when `allocations` is empty** - a logic bug
2. **Content added via `add()` has empty allocations and never gets pinned**

## Environment

- community-cloud-storage: latest main branch
- IPFS Cluster: 5 nodes (nas, meerkat, chll, pihost, ipfs1)
- Profile: hrdag (primary=nas)
- Tested: 2026-01-15

## Bug 1: `is_fully_pinned()` Logic Error

### Current Behavior

```python
def is_fully_pinned(self) -> bool:
    """True if all allocated peers have status 'pinned'."""
    for peer_id in self.allocations:
        if peer_id not in self.peer_map:
            return False
        if self.peer_map[peer_id].status != "pinned":
            return False
    return True
```

When `self.allocations = []`, the for loop never executes and the method returns `True`.

### Reproduction

```python
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import status as ccs_status

cfg = load_config()
cid = "QmPwnBVeBCo3kRWNp36aLZHd4A92yPXBUDg5UTKLvDSHF3"  # any uploaded CID
result = ccs_status(cid, cfg)

print(f"allocations: {result.allocations}")      # []
print(f"pinned_count: {result.pinned_count()}")  # 0
print(f"is_fully_pinned: {result.is_fully_pinned()}")  # True  <-- BUG
```

### Actual Output

```
PinStatus(
    cid='QmPwnBVeBCo3kRWNp36aLZHd4A92yPXBUDg5UTKLvDSHF3',
    allocations=[],
    peer_map={
        '12D3KooWEAMhQTa1...': PeerPinStatus(peername='pihost', status='unpinned'),
        '12D3KooWFCXpnVGG...': PeerPinStatus(peername='meerkat', status='unpinned'),
        '12D3KooWFdQri2MC...': PeerPinStatus(peername='ipfs1', status='unpinned'),
        '12D3KooWMJJ4ZVwH...': PeerPinStatus(peername='chll', status='unpinned'),
        '12D3KooWRwzo72Zs...': PeerPinStatus(peername='nas', status='unpinned'),
    },
    ...
)
is_fully_pinned: True   # WRONG - should be False
pinned_count: 0         # Correct
```

### Expected Behavior

`is_fully_pinned()` should return `False` when:
- `allocations` is empty, OR
- `pinned_count() == 0`

### Suggested Fix

```python
def is_fully_pinned(self) -> bool:
    """True if all allocated peers have status 'pinned'."""
    if not self.allocations:
        return False  # Nothing allocated = not pinned
    for peer_id in self.allocations:
        if peer_id not in self.peer_map:
            return False
        if self.peer_map[peer_id].status != "pinned":
            return False
    return True
```

Or more defensively:

```python
def is_fully_pinned(self) -> bool:
    """True if all allocated peers have status 'pinned'."""
    if not self.allocations:
        return False
    if self.pinned_count() == 0:
        return False
    for peer_id in self.allocations:
        if peer_id not in self.peer_map:
            return False
        if self.peer_map[peer_id].status != "pinned":
            return False
    return True
```

## Bug 2: `add()` Content Not Getting Allocated/Pinned

### Current Behavior

After calling `add()` with a profile that has a primary node, the content:
1. Gets added to IPFS (CIDs are returned)
2. Is NOT allocated to any peers (`allocations=[]`)
3. Shows `status='unpinned'` on all nodes

### Reproduction

```python
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add, status

cfg = load_config()
result = add(Path("/path/to/test/dir"), profile="hrdag", config=cfg)

# Check a returned CID
cid = result.entries[0].cid
pin_status = status(cid, cfg)

print(f"allocations: {pin_status.allocations}")  # [] - should have peer IDs
print(f"pinned_count: {pin_status.pinned_count()}")  # 0 - should be > 0
```

### Expected Behavior

According to docstring in `operations.py:add()`:

> The content is added to IPFS and pinned to:
> 1. The profile's primary node
> 2. The backup node
> 3. Additional replicas chosen by the cluster allocator

The `allocations` list should contain at least the primary and backup node peer IDs, and those nodes should show `status='pinned'` or `status='pinning'`.

### Investigation

The allocations ARE being computed correctly in Python:

```python
>>> from community_cloud_storage.config import load_config
>>> from community_cloud_storage.operations import _get_allocations
>>> cfg = load_config()
>>> _get_allocations('hrdag', cfg)
['12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ',  # nas
 '12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj']  # chll (backup)
```

These are passed to `client.add()` which builds them into the query string:
```python
# cluster_api.py:_build_add_params()
params.append(f"allocations={','.join(allocations)}")
```

### Possible Causes

1. **URL encoding issue** - Are peer IDs being URL-encoded correctly?
2. **Cluster ignoring allocations** - Does the cluster require specific config to honor allocation requests?
3. **Cluster version mismatch** - Has the allocations API changed?
4. **Pin vs Add semantics** - Does `/add` automatically pin, or is a separate `/pins` call needed?

### Next Steps to Debug

1. Enable HTTP debug logging to see actual request being sent
2. Check cluster logs for allocation handling
3. Test with `ipfs-cluster-ctl add --allocations=...` directly
4. Verify cluster replication settings (`replication_factor_min`, `replication_factor_max`)

## Impact

- **ntx verification** reports files as "verified" when they're actually not pinned anywhere
- **Data durability** is at risk - content may exist only in local IPFS cache
- **False confidence** in backup status

## Workaround (ntx)

In ntx we work around Bug 1 by checking `pinned_count() > 0` instead of `is_fully_pinned()`:

```python
def _check_pin_status(cid, ccs_config):
    pin_status = ccs_status(cid, ccs_config)
    count = pin_status.pinned_count()
    # Don't trust is_fully_pinned() - ccs bug returns True with 0 pins
    pinned = count > 0
    return pinned, count, None
```

## Files Affected

- `src/community_cloud_storage/types.py:291` - `is_fully_pinned()` method
- `src/community_cloud_storage/operations.py:86` - `add()` function (potentially)
- `src/community_cloud_storage/cluster_api.py` - (underlying API calls, needs investigation)
