<!--
Author: PB and Claude
Date: 2026-01-29
License: (c) HRDAG, 2026, GPL-2 or newer

---
community-cloud-storage/BUG-add-returns-empty-entries.md
-->

# Bug: operations.add() returns empty entries despite success

## Problem

The `add()` operation in `operations.py` returns `RC_SUCCESS` but with empty `entries` list and no `root_cid`, making it impossible to verify or retrieve uploaded content.

## Reproduction

```python
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add
from community_cloud_storage.types import RC_SUCCESS

# Create test directory
test_dir = Path("/tmp/ccs-test")
test_dir.mkdir(exist_ok=True)
(test_dir / "file1.txt").write_text("Test content 1")
(test_dir / "file2.txt").write_text("Test content 2")

# Load config and upload
cfg = load_config()  # Requires ~/.ccs/config.yml
result = add(test_dir, profile="hrdag", config=cfg, recursive=True)

# BUG: This shows the problem
print(f"returncode: {result.returncode}")  # 0 (RC_SUCCESS)
print(f"root_cid: '{result.root_cid}'")     # '' (empty!)
print(f"entries: {len(result.entries)}")    # 0 (empty!)
print(f"allocations: {result.allocations}") # ['12D3Koo...', '12D3Koo...'] (correct)
```

## Expected Behavior

When `add()` returns `RC_SUCCESS`, it should include:
- `root_cid`: The IPFS CID of the uploaded directory/file
- `entries`: List of `CIDEntry` objects for each uploaded file
- At least one entry with `is_root=True`

Example expected output:
```
returncode: 0
root_cid: 'QmXxxx...'
entries: 3
  - file1.txt: QmYyyy... (root=False, size=14)
  - file2.txt: QmZzzz... (root=False, size=14)
  - ccs-test: QmXxxx... (root=True, size=28)
allocations: ['12D3KooWRwzo...', '12D3KooWMJJ...']
```

## Actual Behavior

```
returncode: 0
root_cid: ''
entries: 0
allocations: ['12D3KooWRwzo...', '12D3KooWMJJ...']
error: None
```

## Investigation

From `operations.py` line 169-186, the code calls:
```python
entries_raw = client.add(
    path,
    recursive=recursive,
    name=path.name,
    allocations=allocations,
)
```

Then at line 202:
```python
root_cid = entries_raw[-1].get("cid", "") if entries_raw else ""
```

The empty result indicates `client.add()` (from `cluster_api.py`) is returning an empty list despite not raising an exception.

**Possible causes:**
1. Cluster API `/add` endpoint returning no entry data
2. Response parsing issue in `cluster_api.py`
3. Cluster not actually adding files (silent failure)

## Impact

**Severity: CRITICAL** - Blocks ntx IPFS integration

- ntx cannot verify uploads (no CID to check)
- ntx cannot track what was uploaded (no entries)
- ntx cannot restore from IPFS (no CID to fetch)
- Prevents completion of Category E (IPFS Integration) in ntx project

This is why ntx currently has the comment (ntx/src/ntx/ipfs.py:10):
> "NOTE: IPFS upload is currently unreliable and needs reimplementation."

## Success Criteria

**Test passes when:**

```python
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add
from community_cloud_storage.types import RC_SUCCESS

# Setup
test_dir = Path("/tmp/ccs-test-validation")
test_dir.mkdir(exist_ok=True)
(test_dir / "test.txt").write_text("Validation test content")

# Execute
cfg = load_config()
result = add(test_dir, profile="hrdag", config=cfg, recursive=True)

# Validate
assert result.returncode == RC_SUCCESS, f"Expected RC_SUCCESS, got {result.returncode}"
assert result.root_cid != "", f"root_cid is empty"
assert len(result.entries) > 0, f"entries is empty"
assert any(e.is_root for e in result.entries), f"No root entry found"

root_entry = [e for e in result.entries if e.is_root][0]
assert root_entry.cid == result.root_cid, f"Root entry CID doesn't match root_cid"

print("✓ SUCCESS: add() returns valid CID and entries")
print(f"  Root CID: {result.root_cid}")
print(f"  Entries: {len(result.entries)}")
```

When this test passes, ntx can proceed with E3-E8 (IPFS status verification, download, restore implementation).

## Environment

- CCS version: 0.4.0 (editable install from ../community-cloud-storage)
- Cluster nodes: 5 peers (nas, meerkat, chll, pihost, ipfs1)
- Profile: hrdag (primary=nas, backup=chll)
- Connectivity: ✓ Verified via `peers()` operation (all 5 peers reachable)
- Test date: 2026-01-29

## Related Files

- `src/community_cloud_storage/operations.py` - `add()` function (lines 86-225)
- `src/community_cloud_storage/cluster_api.py` - `ClusterClient.add()` method
- `src/community_cloud_storage/types.py` - `AddResult`, `CIDEntry` dataclasses

## Next Steps for CCS-Claude

1. Investigate `cluster_api.py` `ClusterClient.add()` method
2. Check if cluster API response is being parsed correctly
3. Test cluster API `/add` endpoint directly (curl or httpx)
4. Verify cluster is actually storing files (check `ipfs pin ls` on nodes)
5. Fix response parsing or add error handling if cluster returns empty
6. Run success criteria test to validate fix
7. Report back with:
   - Root cause identified
   - Fix applied
   - Test passing
