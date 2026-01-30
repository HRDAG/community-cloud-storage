<!--
Author: PB and Claude
Date: 2026-01-29
License: (c) HRDAG, 2026, GPL-2 or newer

---
community-cloud-storage/docs/FIX-PLAN-empty-entries-bug.md
-->

# Fix Plan: Empty Entries Bug

**Bug:** operations.add() returns RC_SUCCESS with empty entries when cluster has errors

**Root Cause:** Cluster returns errors via HTTP trailers when streaming enabled, which our code doesn't check

**Research:** See `docs/ipfs-cluster-research.md` sections 8-11 for detailed analysis

---

## Executive Summary

**Recommended Fix:** Switch to buffered mode (`stream-channels=false`) + add validation

**Why this approach:**
- ✅ Simplest and most reliable
- ✅ Officially recommended for production
- ✅ Makes errors visible as proper HTTP 500 responses
- ✅ Fixes URL encoding bug simultaneously
- ✅ Minimal code changes

**Effort:** ~2-3 hours implementation + testing

---

## Implementation Steps

### Step 1: Enable Buffered Mode (15 min)

**File:** `src/community_cloud_storage/cluster_api.py`

**Change `_build_add_params()` method:**

```python
def _build_add_params(
    self, name: str, allocations: list[str] = None, local: bool = True
) -> str:
    """Build query string for /add endpoint."""
    from urllib.parse import urlencode

    params = {
        "name": name,
        "stream-channels": "false",  # Enable buffered mode for reliable errors
    }

    if allocations:
        params["allocations"] = ",".join(allocations)

    if local:
        params["local"] = "true"

    return urlencode(params)  # Proper URL encoding
```

**This fixes:**
- HTTP trailer error handling
- URL encoding bugs (spaces, special chars)
- Applies to all 3 add methods (_add_file, _add_directory, _add_directory_curl)

---

### Step 2: Update Response Parsing (30 min)

**Goal:** Handle JSON array response format from buffered mode

**Update `_add_file()` method (lines 201-221):**

```python
def _add_file(
    self, path: Path, name: str, allocations: list[str] = None, local: bool = True
) -> list:
    """Add a single file."""
    query = self._build_add_params(name, allocations, local)
    logger.debug(f"_add_file: query string = {query}")

    with open(path, "rb") as f:
        files = {"file": (path.name, f)}
        response = self._request("POST", f"/add?{query}", files=files)

    # Parse response (buffered mode returns JSON array or single object)
    body = response.text.strip()
    if not body:
        raise ClusterAPIError("Empty response body - server error occurred")

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ClusterAPIError(f"Invalid JSON response: {body[:200]}") from e

    # Handle both array and single object
    if isinstance(data, dict):
        results = [data]
    elif isinstance(data, list):
        results = data
    else:
        raise ClusterAPIError(f"Unexpected response type: {type(data)}")

    # Check for inline errors and validate
    for entry in results:
        if entry.get("Type") == "error":
            raise ClusterAPIError(
                entry.get("Message", "Unknown cluster error"),
                entry.get("Code", 0)
            )
        logger.debug(f"_add_file: parsed entry = {entry}")

    if len(results) == 0:
        raise ClusterAPIError("No entries returned from cluster")

    logger.debug(f"_add_file: total entries = {len(results)}")
    return results
```

**Update `_add_directory()` method (lines 223-293) - same pattern:**
- Replace NDJSON parsing with JSON.loads
- Add error checking
- Add empty result validation

**Update `_add_directory_curl()` method (lines 295-373):**
- Curl still returns NDJSON (not affected by stream-channels param in query)
- Keep NDJSON parsing but add inline error detection
- Add empty result validation

---

### Step 3: Add Safety Net in operations.py (15 min)

**File:** `src/community_cloud_storage/operations.py`

**Add validation after `client.add()` call (around line 169):**

```python
# Add to cluster with allocations
try:
    entries_raw = client.add(
        path,
        recursive=recursive,
        name=path.name,
        allocations=allocations,
    )
except ClusterAPIError as e:
    return AddResult(
        root_cid="",
        root_path=str(path),
        entries=[],
        allocations=allocations,
        profile=profile,
        added_at=datetime.now(timezone.utc),
        cluster_host=target_host,
        returncode=RC_FAILED,
        error=str(e),
    )
except Exception as e:
    return AddResult(
        root_cid="",
        root_path=str(path),
        entries=[],
        allocations=allocations,
        profile=profile,
        added_at=datetime.now(timezone.utc),
        cluster_host=target_host,
        returncode=RC_FAILED,
        error=f"Unexpected error: {e}",
    )

# NEW: Validate entries_raw is not empty (safety net)
if not entries_raw:
    return AddResult(
        root_cid="",
        root_path=str(path),
        entries=[],
        allocations=allocations,
        profile=profile,
        added_at=datetime.now(timezone.utc),
        cluster_host=target_host,
        returncode=RC_FAILED,
        error="No entries returned from cluster (possible server error)",
    )

# Root is the last entry from IPFS
root_cid = entries_raw[-1].get("cid", "") if entries_raw else ""
# ... rest of method
```

---

### Step 4: Add Tests (45 min)

**File:** `test/test_cluster_api.py`

**Add test for empty response:**

```python
@patch.object(ClusterClient, '_request')
def test_add_file_empty_response_raises_error(self, mock_request):
    """Empty response body should raise ClusterAPIError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    mock_request.return_value = mock_response

    client = ClusterClient("localhost")

    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test")
        path = Path(f.name)

    try:
        with pytest.raises(ClusterAPIError, match="Empty response"):
            client.add(path)
    finally:
        path.unlink()
```

**Add test for inline error:**

```python
@patch.object(ClusterClient, '_request')
def test_add_file_inline_error_raises(self, mock_request):
    """Inline error object should raise ClusterAPIError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"Type":"error","Message":"not enough peers","Code":0}'
    mock_request.return_value = mock_response

    client = ClusterClient("localhost")

    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test")
        path = Path(f.name)

    try:
        with pytest.raises(ClusterAPIError, match="not enough peers"):
            client.add(path)
    finally:
        path.unlink()
```

**Add test for buffered mode format:**

```python
@patch.object(ClusterClient, '_request')
def test_add_file_buffered_mode_array_response(self, mock_request):
    """Buffered mode returns JSON array, should parse correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '[{"name":"test.txt","cid":"QmTest","size":42}]'
    mock_request.return_value = mock_response

    client = ClusterClient("localhost")

    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test")
        path = Path(f.name)

    try:
        results = client.add(path)
        assert len(results) == 1
        assert results[0]["cid"] == "QmTest"
    finally:
        path.unlink()
```

**Verify stream-channels parameter:**

```python
def test_build_add_params_includes_stream_channels_false(self):
    """Verify stream-channels=false is added to query params."""
    client = ClusterClient("localhost")
    result = client._build_add_params("test.txt", ["peer1"], local=True)

    # Should include stream-channels=false
    assert "stream-channels=false" in result
    # Should be URL encoded
    assert "stream-channels" in result  # Check key exists
```

**Test URL encoding:**

```python
def test_url_encoding_spaces(self):
    """File names with spaces should be URL encoded."""
    client = ClusterClient("localhost")
    result = client._build_add_params("my file.txt")

    # Space should be encoded as + or %20
    assert "my+file.txt" in result or "my%20file.txt" in result

def test_url_encoding_special_chars(self):
    """Special characters should be URL encoded."""
    client = ClusterClient("localhost")
    result = client._build_add_params("file&name=test.txt")

    # & should be encoded as %26, = as %3D
    assert "%26" in result
    assert "%3D" in result
```

---

### Step 5: Update Documentation (15 min)

**Update method docstrings:**

```python
def add(self, path: Path, recursive: bool = True, name: str = None,
        allocations: list[str] = None, local: bool = True) -> list:
    """
    Add a file or directory to the cluster.

    Uses buffered mode (stream-channels=false) for reliable error handling.
    The entire response is buffered in memory before being returned.

    Args:
        path: Path to file or directory
        recursive: If True and path is directory, add recursively
        name: Pin name for cluster metadata (defaults to filename/dirname)
        allocations: List of peer IDs for explicit allocation (optional)
        local: If True, always include the connected node in allocations

    Returns:
        List of dicts with 'name', 'cid', 'size', 'allocations'.
        Last item is the root CID.

    Raises:
        ClusterAPIError: If cluster returns error, response is invalid,
                        or result is empty
        ValueError: If path doesn't exist or is invalid type

    Note:
        Large uploads (>500MB) will be buffered in memory. For very large
        files, consider using ipfs-cluster-ctl directly.
    """
```

**Add CHANGELOG entry:**

```markdown
## [0.5.0] - 2026-01-29

### Fixed
- **CRITICAL:** Fix add() returning RC_SUCCESS with empty entries when cluster errors
  - Root cause: Cluster errors returned via HTTP trailers in streaming mode
  - Solution: Switch to buffered mode (stream-channels=false)
  - Errors now properly return HTTP 500 with visible error messages
  - Fixes bug #BUG-add-returns-empty-entries.md

### Changed
- **BREAKING:** add() operations now use buffered mode instead of streaming
  - Responses buffered in memory (acceptable for typical usage <500MB)
  - For very large uploads, use ipfs-cluster-ctl with --no-stream
  - Provides more reliable error handling

### Improved
- Fix URL encoding bugs in query parameters (spaces, special characters)
- Add validation that add() results are non-empty
- Better error messages when cluster operations fail
- Comprehensive test coverage for error scenarios
```

---

## Testing Checklist

### Unit Tests
- [ ] Run `pytest test/test_cluster_api.py` - all pass
- [ ] Run `pytest test/test_operations.py` - all pass
- [ ] New tests added for empty response
- [ ] New tests added for inline errors
- [ ] New tests added for buffered mode format
- [ ] New tests added for URL encoding

### Integration Tests

**Test 1: Reproduce original bug (should now fail properly)**
```bash
cd /home/pball/projects/community-cloud-storage
uv run python3 -c "
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add
from community_cloud_storage.types import RC_FAILED

test_dir = Path('/tmp/ccs-test')
test_dir.mkdir(exist_ok=True)
(test_dir / 'test.txt').write_text('test')

cfg = load_config()
result = add(test_dir, profile='hrdag', config=cfg)

# Should now return RC_FAILED with error message
assert result.returncode == RC_FAILED, f'Expected RC_FAILED, got {result.returncode}'
assert result.error is not None, 'Expected error message'
assert 'not enough peers' in result.error.lower(), f'Unexpected error: {result.error}'

print('✓ Error properly detected and returned')
print(f'Error: {result.error}')
"
```

**Test 2: Success case (after fixing cluster peering)**
```bash
# After ensuring cluster has enough peers
uv run python3 -c "
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add
from community_cloud_storage.types import RC_SUCCESS

test_dir = Path('/tmp/ccs-test-success')
test_dir.mkdir(exist_ok=True)
(test_dir / 'file1.txt').write_text('content 1')
(test_dir / 'file2.txt').write_text('content 2')

cfg = load_config()
result = add(test_dir, profile='hrdag', config=cfg, recursive=True)

assert result.returncode == RC_SUCCESS, f'Expected RC_SUCCESS, got {result.returncode}'
assert result.root_cid != '', 'Expected non-empty root_cid'
assert len(result.entries) > 0, 'Expected non-empty entries'
assert any(e.is_root for e in result.entries), 'Expected root entry'

print('✓ Success case works correctly')
print(f'Root CID: {result.root_cid}')
print(f'Entries: {len(result.entries)}')
"
```

**Test 3: URL encoding**
```bash
uv run python3 -c "
from pathlib import Path
from community_cloud_storage.cluster_api import ClusterClient

client = ClusterClient('localhost')

# Test spaces
result = client._build_add_params('my file.txt')
assert 'my+file' in result or 'my%20file' in result, f'Spaces not encoded: {result}'

# Test special chars
result = client._build_add_params('file&name=test.txt')
assert '%26' in result and '%3D' in result, f'Special chars not encoded: {result}'

print('✓ URL encoding works correctly')
"
```

---

## Rollout Plan

### Pre-deployment
1. Run all unit tests
2. Run integration tests against test cluster
3. Review code changes
4. Update documentation

### Deployment
1. Merge to main branch
2. Tag release v0.5.0
3. Deploy to pypi (if applicable)
4. Update dependent projects (ntx)

### Post-deployment
1. Monitor for issues
2. Test with real workloads
3. Document any edge cases
4. Update BUG-add-returns-empty-entries.md as RESOLVED

---

## Rollback Plan

If issues arise:

1. Revert `_build_add_params()` to remove `stream-channels=false`
2. Keep validation logic (defense in depth)
3. Fall back to streaming mode temporarily
4. Investigate specific issue

**Revert command:**
```bash
git revert <commit-hash>
```

---

## Success Criteria

✅ **Primary:** Test from BUG-add-returns-empty-entries.md passes
✅ **Secondary:** All existing tests still pass
✅ **Tertiary:** New error tests pass
✅ **Integration:** Real cluster uploads work with proper error handling

---

## Estimated Effort

- Implementation: 2 hours
- Testing: 1 hour
- Documentation: 0.5 hours
- **Total: 3.5 hours**

---

## Next Steps

Ready to implement? Ask PB to approve this plan, then proceed with Step 1.
