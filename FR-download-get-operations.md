<!--
Author: PB and Claude
Date: 2026-01-29
License: (c) HRDAG, 2026, GPL-2 or newer
-->

# Feature Request: Download/Get Operations for Content Retrieval

## Summary

**Request:** Add download/get operations to CCS for retrieving content by CID from IPFS Cluster.

**Priority:** HIGH - Blocks ntx restore functionality

**Requester:** ntx (archival pipeline)

## Problem Statement

CCS currently provides operations for uploading content to IPFS Cluster (`add()`) and checking pin status (`status()`), but no way to retrieve content back by CID.

This blocks disaster recovery workflows where users need to restore archived files from IPFS.

### Current Capabilities

| Operation | Purpose | Status |
|-----------|---------|--------|
| `add()` | Upload content to cluster | ✓ Available |
| `status()` | Query pin status by CID | ✓ Available |
| `ls()` | List directory by CID | ✓ Available |
| `peers()` | List cluster peers | ✓ Available |
| **`get()` / `download()`** | **Retrieve content by CID** | **✗ Missing** |

## Use Case

ntx archives consortium data to S3 and IPFS for redundancy. Users restore files by content hash:

```bash
# Current: Works with S3
ntx restore-s3 --content-hash 62ac14... --output ./restored/

# Blocked: Cannot restore from IPFS
ntx restore-ipfs --content-hash 62ac14... --output ./restored/
# Error: IPFS restore blocked by missing CCS get/download operation
```

**Why this matters:**
- S3 may be unavailable (outage, cost, access restrictions)
- IPFS provides geographic redundancy across 5 cluster peers
- Disaster recovery requires multiple retrieval paths
- Cannot fully utilize IPFS infrastructure investment without download

## Proposed API

### Simple get() function (recommended)

```python
from community_cloud_storage.operations import get

def get(
    cid: str,
    dest: Path,
    config: CCSConfig,
    profile: Optional[str] = None
) -> None:
    """Download content from IPFS cluster by CID.

    Args:
        cid: IPFS CID to retrieve
        dest: Destination path for downloaded content
        config: CCS configuration
        profile: Profile name (uses primary node)

    Raises:
        RuntimeError: If CID not found or download fails
    """
```

**Behavior:**
- Download content at CID to dest path
- If CID is directory, download recursively
- Use profile's primary node, fallback to backup if primary unavailable
- Raise clear exceptions on failure (network error, CID not found, etc.)

**Matches IPFS CLI semantics:** `ipfs get <cid>`

## Implementation Considerations

### Question 1: Does IPFS Cluster API support content retrieval?

Need to determine if:
- Cluster API provides `/pins/{cid}/data` endpoint (or similar) for content
- OR: Must connect to IPFS node directly on cluster peers

### Question 2: If direct IPFS node access required

Possible approach:

```python
def get(cid: str, dest: Path, config: CCSConfig, profile: str = None) -> None:
    # 1. Query cluster for pin status
    pin_status = status(cid, config=config)

    # 2. Find peer with content
    peer = find_pinning_peer(pin_status)

    # 3. Connect to IPFS node API on that peer
    ipfs_api = get_ipfs_node_api(peer)  # port 5001

    # 4. Retrieve via IPFS API: POST /api/v0/get?arg={cid}
    ipfs_api.get(cid, dest)
```

**Configuration needs:**
- IPFS node API addresses for each cluster peer
- Default IPFS API port: 5001
- Authentication tokens if IPFS nodes require auth

### Question 3: Should CCS manage IPFS node connections?

Options:
- **A:** CCS handles IPFS node API client (recommended for consistency)
- **B:** User calls ipfs CLI directly via subprocess (loses cluster awareness)
- **C:** CCS provides helper but user manages IPFS connections (complex)

Recommend Option A for consistency with CCS design philosophy.

## Success Criteria

### Test 1: Download Single File

```python
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add, get
import tempfile

# Upload test file
cfg = load_config()
test_file = Path("test.txt")
test_file.write_text("Hello IPFS")

result = add(test_file, profile="hrdag", config=cfg)
cid = result.root_cid

# Download to new location
with tempfile.TemporaryDirectory() as tmpdir:
    dest = Path(tmpdir) / "downloaded.txt"
    get(cid, dest, config=cfg)

    # Verify content matches
    assert dest.read_text() == "Hello IPFS"
```

**Expected:** ✓ Test passes, file content matches

### Test 2: Download Directory

```python
# Upload directory
test_dir = Path("test-dir")
test_dir.mkdir()
(test_dir / "file1.txt").write_text("Content 1")
(test_dir / "file2.txt").write_text("Content 2")

result = add(test_dir, profile="hrdag", config=cfg, recursive=True)
root_cid = result.root_cid

# Download directory
with tempfile.TemporaryDirectory() as tmpdir:
    dest = Path(tmpdir) / "downloaded"
    get(root_cid, dest, config=cfg)

    # Verify structure
    assert (dest / "file1.txt").exists()
    assert (dest / "file2.txt").exists()
    assert (dest / "file1.txt").read_text() == "Content 1"
```

**Expected:** ✓ Directory structure preserved, all files present

### Test 3: CID Not Found

```python
fake_cid = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"

try:
    get(fake_cid, Path("output"), config=cfg)
    assert False, "Should raise exception"
except RuntimeError as e:
    assert "not found" in str(e).lower() or "not pinned" in str(e).lower()
```

**Expected:** ✓ Raises clear error for non-existent CID

## Current Workaround

ntx can use subprocess to call ipfs CLI directly:

```python
import subprocess

def download_workaround(cid: str, dest: Path) -> None:
    """Workaround until CCS provides get()."""
    subprocess.run(
        ["ipfs", "get", cid, "-o", str(dest)],
        check=True
    )
```

**Limitations:**
- Requires ipfs CLI installed
- Uses local IPFS node only (ignores CCS cluster)
- No cluster peer selection or failover
- Bypasses CCS configuration

## Impact

**Blocked in ntx:**
- `restore-ipfs` command (CLI stub exists, raises NotImplementedError)
- `ipfs.download()` function (documented blocker)
- Full disaster recovery (S3-only restore currently)

**Timeline:**
- Not urgent (S3 restore works)
- Important for redundancy strategy
- Would like in next CCS release

## Related Files

**In ntx repo:**
- ntx/docs/category-e-ipfs-investigation.md - E4, E6, E7 blocked
- ntx/docs/feature-request-ccs-download.md - Detailed analysis
- ntx/src/ntx/cli.py:1127-1149 - restore-ipfs stub
- ntx/src/ntx/ipfs.py:95-119 - download() blocker

## Questions for Implementation

1. Does IPFS Cluster API provide content retrieval endpoints?
2. Should CCS connect to IPFS node APIs directly?
3. How to handle authentication for IPFS node APIs?
4. Should download verify content hash automatically?
5. Should we support streaming large files (memory efficiency)?

## Recommendation

Implement simple `get(cid, dest, config)` operation that:
1. Queries cluster for pin status
2. Selects peer with pinned content
3. Retrieves from IPFS node on that peer
4. Handles errors clearly
5. Supports both files and directories

This unblocks ntx restore functionality and provides foundation for more sophisticated download options later (streaming, partial retrieval, multi-peer parallel download, etc.).
