<!--
Author: PB and Claude
Date: 2026-01-30
License: (c) HRDAG, 2026, GPL-2 or newer
-->

# Bug Report: get() Downloads HTML Directory Listing Instead of Files

## Summary

**Bug:** `operations.get()` downloads HTML directory listing instead of actual file content when retrieving CIDs from IPFS gateway.

**Severity:** HIGH - Blocks IPFS restore functionality in ntx

**Status:** CONFIRMED

## Reproduction

### Test Setup

```python
#!/usr/bin/env python3
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import get

config_file = Path.home() / ".ccs" / "config.yml"
config = load_config(config_file)
cid = "QmTYMoB7MDHKjDKs3zf8F8f5BFFeZs8Nsc8d2KHfz9Mos3"
dest = Path("/tmp/ccs-python-test-output")

print(f"Downloading CID: {cid}")
print(f"Destination: {dest}")

try:
    get(cid, dest, config, profile="hrdag")
    print(f"\n✓ Download successful!")
except Exception as e:
    print(f"\n✗ Error: {e}")
```

### Test CID Details

- **CID:** `QmTYMoB7MDHKjDKs3zf8F8f5BFFeZs8Nsc8d2KHfz9Mos3`
- **Content:** ntx commit 2026-01-21T01:10:36Z (1 file, 74 bytes total)
- **Upload status:** ✓ Successfully pinned on 3 nodes (chll, nas, meerkat)
- **Expected size:** 74 bytes (tar archive)
- **Actual downloaded size:** 249KB (HTML)

### Actual Result

```bash
$ python3 /tmp/test_ccs_get.py
Downloading CID: QmTYMoB7MDHKjDKs3zf8F8f5BFFeZs8Nsc8d2KHfz9Mos3
Destination: /tmp/ccs-python-test-output

✓ Download successful!

Downloaded 4 items:
  . (dir)
  2026-01-21T01:10:36Z.tar (249867 bytes)
  2026-01-21T01:10:36Z.tar.age.sig (566 bytes)
  2026-01-21T01:10:36Z.tar.age (709 bytes)
```

**Problem:** The `.tar` file is 249KB but should be 74 bytes.

```bash
$ file /tmp/ccs-python-test-output/2026-01-21T01:10:36Z.tar
/tmp/ccs-python-test-output/2026-01-21T01:10:36Z.tar: HTML document, ASCII text, with very long lines (63631)

$ head -5 /tmp/ccs-python-test-output/2026-01-21T01:10:36Z.tar
<!DOCTYPE html>
<html lang="en">
<head>
  <title>/ipfs/QmTYMoB7MDHKjDKs3zf8F8f5BFFeZs8Nsc8d2KHfz9Mos3/2026-01-21T01:10:36Z.tar</title>
  <meta charset="utf-8">
```

**Confirmed:** Downloaded HTML directory listing instead of binary tar archive.

## Root Cause Analysis

### Current Implementation (operations.py:466-508)

```python
def get(
    cid: str,
    dest: Path,
    config: CCSConfig,
    profile: Optional[str] = None,
    host: str = None,
) -> None:
    """Download content from IPFS cluster by CID."""
    pin_status = status(cid, config, host)
    download_host = _select_download_peer(pin_status, config, profile)

    # Download via IPFS gateway (port 8080)
    url = f"http://{download_host}:8080/ipfs/{cid}"
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
```

### The Problem

**IPFS gateway behavior for directories:**
- When accessing `/ipfs/{cid}` where CID is a directory (UnixFS directory)
- Gateway returns HTML directory listing (web UI)
- NOT the raw content or tar archive

**What we're seeing:**
- CID `QmTYM...` is UnixFS directory containing 3 files
- HTTP GET to `http://chll:8080/ipfs/QmTYM...` returns HTML
- Browser-friendly behavior, but wrong for programmatic download

### Expected Gateway Behavior

IPFS gateway supports multiple download modes:

| URL Pattern | Returns | Use Case |
|-------------|---------|----------|
| `/ipfs/{cid}` | HTML listing (directories) OR raw file (files) | Browser viewing |
| `/ipfs/{cid}?download=true` | **Force download** (tar for dirs) | Programmatic retrieval |
| `/ipfs/{cid}?format=tar` | **Tar archive** (directories) | Explicit tar request |
| `/api/v0/get?arg={cid}` | **IPFS API format** (original structure) | IPFS node API |

**CCS currently uses:** `/ipfs/{cid}` → Gets HTML for directories

**CCS should use:** `/ipfs/{cid}?download=true` OR `/ipfs/{cid}?format=tar`

## Proposed Fix

### Option 1: Add download=true Query Parameter (Simplest)

```python
def get(
    cid: str,
    dest: Path,
    config: CCSConfig,
    profile: Optional[str] = None,
    host: str = None,
) -> None:
    """Download content from IPFS cluster by CID."""
    pin_status = status(cid, config, host)
    download_host = _select_download_peer(pin_status, config, profile)

    # Download via IPFS gateway with download=true to force binary response
    url = f"http://{download_host}:8080/ipfs/{cid}?download=true"  # ← ADD THIS
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
```

**Benefits:**
- Minimal change (1 character difference)
- Gateway handles tar creation automatically for directories
- Works for both files and directories
- Standard IPFS gateway feature

### Option 2: Use IPFS Node API (More Control)

```python
def get(cid: str, dest: Path, config: CCSConfig, ...) -> None:
    """Download via IPFS node API (port 5001) instead of gateway."""
    pin_status = status(cid, config, host)
    download_host = _select_download_peer(pin_status, config, profile)

    # Use IPFS API endpoint
    url = f"http://{download_host}:5001/api/v0/get?arg={cid}"
    response = requests.post(url, stream=True)  # API uses POST
    response.raise_for_status()

    # API returns tar archive directly
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
```

**Benefits:**
- More control over format
- Uses official IPFS API
- Can add compression, archive options

**Drawbacks:**
- Requires port 5001 accessible (in addition to 9094 cluster, 8080 gateway)
- Different auth model than gateway
- More complex configuration

### Option 3: Detect File vs Directory

```python
def get(cid: str, dest: Path, config: CCSConfig, ...) -> None:
    """Download content, detecting file vs directory."""
    pin_status = status(cid, config, host)
    download_host = _select_download_peer(pin_status, config, profile)

    # Try HEAD request to check Content-Type
    head_url = f"http://{download_host}:8080/ipfs/{cid}"
    head_response = requests.head(head_url)
    content_type = head_response.headers.get("Content-Type", "")

    if "text/html" in content_type or "directory" in content_type:
        # Directory: request tar
        url = f"http://{download_host}:8080/ipfs/{cid}?format=tar"
    else:
        # File: download directly
        url = f"http://{download_host}:8080/ipfs/{cid}"

    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
```

**Benefits:**
- Handles files and directories optimally
- No unnecessary tar for single files

**Drawbacks:**
- Extra HEAD request
- More complex logic
- Content-Type detection may be unreliable

## Recommendation

**Use Option 1** (`?download=true`) because:
- Simplest fix (1 line change)
- Works for all CID types (files, directories)
- Standard IPFS gateway feature
- No extra requests or configuration needed

## Test Plan

### Test 1: Download Directory (Current Failure Case)

```python
from community_cloud_storage.operations import get

cid = "QmTYMoB7MDHKjDKs3zf8F8f5BFFeZs8Nsc8d2KHfz9Mos3"
dest = Path("/tmp/test-download")

get(cid, dest, config, profile="hrdag")

# Verify: dest should be tar archive, not HTML
assert dest.exists()
assert dest.stat().st_size < 1000  # Should be ~74 bytes, not 249KB
with open(dest, "rb") as f:
    header = f.read(5)
    assert header != b"<!DOC"  # Not HTML
    # Should be tar or directory structure
```

### Test 2: Download Single File

```python
# Upload single file to get CID
test_file = Path("/tmp/test-single.txt")
test_file.write_text("Hello IPFS")

from community_cloud_storage.operations import add, get
result = add(test_file, profile="hrdag", config=config)
single_file_cid = result.root_cid

# Download it
dest = Path("/tmp/downloaded-single.txt")
get(single_file_cid, dest, config)

# Verify content
assert dest.read_text() == "Hello IPFS"
```

### Test 3: Large File (Streaming Test)

```python
# Upload ~10MB file
large_file = Path("/tmp/large-test.bin")
large_file.write_bytes(b"X" * 10_000_000)

result = add(large_file, profile="hrdag", config=config)
large_cid = result.root_cid

# Download via streaming
dest = Path("/tmp/downloaded-large.bin")
get(large_cid, dest, config)

# Verify size and content
assert dest.stat().st_size == 10_000_000
assert dest.read_bytes() == b"X" * 10_000_000
```

## Impact

**Currently broken:**
- ntx `restore-ipfs` command (cannot download commits from IPFS)
- Any CCS user trying to retrieve directories
- Integration tests for download functionality

**After fix:**
- ntx can implement full IPFS restore workflow
- CCS provides complete upload/download lifecycle
- IPFS cluster becomes viable backup storage

## Related Issues

- FR-download-get-operations.md - Original feature request (implemented but buggy)
- ntx/docs/category-e-ipfs-investigation.md - Documented E4 blocker
- ntx/TODAY.md - Category E blocked

## References

**IPFS Gateway Specification:**
- https://docs.ipfs.tech/reference/http/gateway/
- Query parameters: `download`, `format`, `filename`

**IPFS HTTP API:**
- https://docs.ipfs.tech/reference/kubo/rpc/#api-v0-get
- `/api/v0/get` endpoint documentation

## Environment

- **CCS version:** Latest (as of 2026-01-30)
- **IPFS node:** Kubo (version unknown)
- **Cluster:** 5 peers (chll, nas, meerkat, pihost, ipfs1)
- **Test client:** Python 3.x with requests library

## Next Steps

1. Apply Option 1 fix (add `?download=true` to URL)
2. Run Test Plan (Tests 1-3)
3. Verify with ntx integration test
4. Update FR-download-get-operations.md status to "Implemented"
5. Enable ntx restore-ipfs functionality
