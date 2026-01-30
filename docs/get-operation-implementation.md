<!--
Author: PB and Claude
Date: 2026-01-30
License: (c) HRDAG, 2026, GPL-2 or newer
-->

# Get Operation Implementation: Complete History

**Status:** ✅ IMPLEMENTED & FIXED
**Date:** 2026-01-30

## Summary

Implemented `operations.get()` to retrieve content from IPFS Cluster, enabling full upload/download lifecycle. Initial implementation had a bug where directories downloaded as HTML instead of tar archives. Bug was identified, fixed, and verified.

## Feature Request (FR-download-get-operations.md)

### Original Requirements

**Goal:** Add operations.get() and ccs get CLI command to download content from IPFS cluster by CID.

**Design Decisions:**
- **Return pattern:** Exception-based (raise on error) to match status(), peers()
- **API approach:** Use IPFS gateway (port 8080) for broad accessibility
- **Profile support:** Optional --profile parameter to prefer primary node
- **Peer selection:** Query cluster for pin status, select based on profile preference

### Implementation (TDD Approach)

**Phase 1-2: Tests (Red)**
- 6 unit tests: 3 error cases, 3 success cases
- Error cases: nonexistent CID, unknown profile, no pinned peers
- Success cases: file download, profile preference, backup fallback

**Phase 3: Implementation (Green)**
- Added `get()` function in operations.py
- Added `_select_download_peer()` helper for peer selection logic
- Uses IPFS gateway (port 8080) instead of API (port 5001) for network compatibility

**Phase 4: CLI Integration**
- Updated existing `ccs get` command to use operations.get()
- Options: --dest (required), --profile, --config-file, --host

**Phase 5: Integration Test**
- End-to-end test: add file → wait for pin → get file → verify content

## Bug Report (BUG-get-downloads-html-instead-of-files.md)

### Problem Discovered

**Symptom:** Downloads returned HTML directory listings instead of actual content for directories.

**Test Case:**
- CID: `QmTYMoB7MDHKjDKs3zf8F8f5BFFeZs8Nsc8d2KHfz9Mos3` (ntx commit directory)
- Expected: 74 byte tar archive
- Actual: 249KB HTML document

**Root Cause:**
IPFS gateway behavior:
- `/ipfs/{cid}` → Returns HTML listing for directories (browser-friendly)
- `/ipfs/{cid}?format=tar` → Returns tar archive for directories

### Bug Fix Implementation

**Solution:** Intelligent content-type detection

1. **HEAD request first:** Check Content-Type to detect file vs directory
2. **For directories** (Content-Type: text/html): Add `?format=tar` parameter
3. **For files:** Download directly without format parameter (preserves raw content)

**Code Changes:**
```python
# Check if CID is a directory by doing HEAD request
base_url = f"http://{download_host}:8080/ipfs/{cid}"
head_response = requests.head(base_url, allow_redirects=True)
content_type = head_response.headers.get("Content-Type", "")

# If directory, use format=tar to get archive instead of HTML
if "text/html" in content_type or "directory" in content_type:
    url = f"{base_url}?format=tar"
else:
    url = base_url
```

### Verification

**Test Results:**
- ✅ Unit tests: 19/19 passing (7 get() tests including new directory test)
- ✅ Integration test: File download works correctly
- ✅ Directory download: Returns 38K tar archive (not 249K HTML)
- ✅ Single file: Returns raw content (not wrapped in tar)

**Manual Testing:**
```bash
# Directory CID from bug report
$ ccs get QmTYMoB...Mos3 --dest archive.tar --profile hrdag
Downloaded QmTYMoB...Mos3 to archive.tar

$ file archive.tar
archive.tar: POSIX tar archive  # ✓ Correct (was HTML before)

$ tar -tf archive.tar | head -3
QmTYMoB...Mos3
QmTYMoB...Mos3/2026-01-21T01_10_36Z.1.dar.age
QmTYMoB...Mos3/2026-01-21T01_10_36Z.par2  # ✓ Valid contents
```

## Final Implementation Details

### Functions Added

**operations.py:**
- `get(cid, dest, config, profile, host)` - Main download function
- `_select_download_peer(pin_status, config, profile)` - Peer selection helper

**cli.py:**
- `ccs get <cid> --dest <path> [--profile <org>] [--host <node>]`

### Network Architecture

The implementation handles the deployment's network topology:
- **Cluster API** (port 9094): Uses tailscale IPs from config (100.64.0.x)
- **IPFS Gateway** (port 8080): Also accessible via tailscale IPs
- **Peer selection**: Queries cluster for pin status, selects based on profile preference

### Test Coverage

**Unit Tests (test_operations.py):**
1. `test_get_nonexistent_cid_raises` - ClusterAPIError for missing CID
2. `test_get_unknown_profile_raises` - ConfigError for invalid profile
3. `test_get_no_pinned_peers_raises` - CCSError when content not pinned
4. `test_get_file_success` - Download file without format parameter
5. `test_get_directory_with_format_tar` - Download directory as tar archive
6. `test_get_with_profile_prefers_primary` - Profile-based peer selection
7. `test_get_fallback_to_backup` - Fallback when primary unavailable

**Integration Test (test_integration.py):**
- `test_add_and_get_file` - End-to-end add→get roundtrip with content verification

## Impact

**Enables:**
- ✅ ntx restore-ipfs command (can now download commits from IPFS)
- ✅ Complete CCS upload/download lifecycle
- ✅ IPFS cluster as viable backup storage solution

**Blocks removed:**
- ntx Category E implementation
- IPFS-based disaster recovery workflows

## References

**IPFS Gateway Specification:**
- https://docs.ipfs.tech/reference/http/gateway/
- Query parameters: `download`, `format`, `filename`

**Related Commits:**
- 5c3dbda - Add get() operation with directory detection to fix HTML download bug

## Lessons Learned

1. **Test with real data:** Integration test with simple file passed, but directory CID revealed HTML download bug
2. **Gateway vs API:** IPFS gateway (port 8080) more accessible than API (port 5001) in this deployment
3. **Content-type detection:** HEAD request with Content-Type check reliably distinguishes files from directories
4. **Network topology matters:** Config has tailscale IPs for cluster API; gateway also accessible via same IPs
