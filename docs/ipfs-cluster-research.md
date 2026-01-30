# IPFS Cluster /add Endpoint: Streaming Response Format Research

**Date:** January 2026  
**Purpose:** Python client implementation for IPFS Cluster REST API  
**Focus:** Detecting and extracting errors from streaming `/add` responses

---

## Executive Summary

The IPFS Cluster `/add` endpoint uses NDJSON (Newline-Delimited JSON) for streaming responses by default. Errors in streaming mode are problematic because they can arrive via HTTP trailers (inaccessible to many HTTP clients) or appear as inline JSON objects in the stream. For production Python clients, **using `stream-channels=false`** is recommended for reliability.

---

## 1. Streaming Format Specification

### Wire Format (`stream-channels=true`, default)

The `/add` endpoint returns **NDJSON** - one JSON object per line, with no surrounding array brackets and no commas between objects.

**Success response example:**
```
{"code":0,"message":"","Name":"test1.jpg","Hash":"QmPxBet4MHo93b9nCE2FYRtDTowVA3bMRdDBZcYAiBkZKN","Size":"4696045"}
{"code":0,"message":"","Name":"test2.jpg","Hash":"QmfJ8fzLwCmuvxNG8RH41RmmjGzMrXw38pjP85EJSiXKJ4","Size":"4696045"}
```

**HTTP Headers:**
```
HTTP/1.1 200 OK
Content-Type: application/json
Transfer-Encoding: chunked
Trailer: X-Stream-Error
X-Chunked-Output: 1
```

**Note:** The `Content-Type` should technically be `application/x-ndjson`, but the server returns `application/json`. This is a known inconsistency (see kubo issue #3737).

### Buffered Format (`stream-channels=false`)

With this parameter, the API buffers output and returns a valid JSON array:

```json
[
  {"code":0,"message":"","Name":"test1.jpg","Hash":"QmPxBet4...","Size":"4696045"},
  {"code":0,"message":"","Name":"test2.jpg","Hash":"QmfJ8fz...","Size":"4696045"}
]
```

**Source:** IPFS Cluster CHANGELOG - "The stream-channels=false query parameter for the /add endpoint will let the API buffer the output when adding and return a valid JSON array once done, making this API endpoint behave like a regular, non-streaming one."

---

## 2. Error Handling in Streaming Mode

### The Core Problem

Errors in streaming mode are communicated via **HTTP Trailers** - specifically the `X-Stream-Error` header sent AFTER the response body completes. Most HTTP clients (including browser fetch API) cannot access HTTP trailers.

**Error scenarios:**

| Scenario | Behavior |
|----------|----------|
| Error before streaming starts | HTTP 200, empty body |
| Error during streaming | Partial NDJSON, then connection closes |
| Error inline in stream | JSON object with `Type: "error"` |
| Error in trailer | `X-Stream-Error` header after body |

### Inline Error Object Format

Errors can appear as JSON objects within the NDJSON stream:

```json
{"Message":"not enough peers to allocate","Code":0,"Type":"error"}
```

Or:
```json
{"Message":"http: invalid Read on closed Body","Code":0,"Type":"error"}
```

**Critical:** The js-ipfs-api historically did NOT throw errors when encountering these - it silently ignored them and returned partial results.

### HTTP Trailer Format

The `X-Stream-Error` trailer contains a JSON-encoded error:

```
X-Stream-Error: {"Message":"unexpected EOF","Code":0,"Type":"error"}
```

### Empty Body Problem

When cluster encounters an error before any output can be streamed, you get:
- HTTP 200 status (headers already committed)
- Empty response body
- No visible error

**Source:** GitHub issue ipfs-cluster#1365 - "When attempting to do a cluster add with a complex/strange DAG, the ipfs-cluster fails to add it. Trying to add returns a OK response, but it does not return a JSON body."

---

## 3. How Official Clients Handle Streaming

### Go Client (ipfs-cluster-ctl)

Uses Go channels for streaming output:

```go
AddMultiFile(ctx context.Context, 
             multiFileR *files.MultiFileReader, 
             params api.AddParams, 
             out chan<- api.AddedOutput) error
```

The client reads from the channel and handles errors returned via the error return value after streaming completes.

**CLI flag:** `ipfs-cluster-ctl add --no-stream` buffers on the client side.

### JavaScript Client (@nftstorage/ipfs-cluster)

The NFT.storage client (now deprecated) parsed streaming responses by reading the response as text and splitting on newlines. Error handling was minimal - it would fail with "Unexpected end of JSON input" on empty bodies.

---

## 4. Production Recommendations

### Use `stream-channels=false` for Reliability

**Official documentation warning:**

> Using the /add endpoint with Nginx in front as a reverse proxy may cause problems. Make sure to add `?stream-channels=false` to every Add request to avoid them. The problems manifest themselves as "connection reset by peer while reading upstream" errors.

**Trade-off:** Buffering causes in-memory allocation for large responses, but is "perfectly fine for regular usage."

### When to Use Streaming

Use streaming (`stream-channels=true`) only when:
- You need real-time progress updates for large uploads
- You're adding many files and want incremental CID feedback
- Memory constraints require streaming

### Error Detection Checklist

1. Check HTTP status (though 200 doesn't guarantee success)
2. Handle empty response body as error
3. Parse each NDJSON line and check for error objects
4. Access HTTP trailers if your client supports them
5. Validate expected fields exist in response objects

---

## 5. Python Implementation

### Complete Client Implementation

```python
"""
IPFS Cluster Python Client
Handles both streaming and buffered /add endpoint responses
"""

import json
import requests
from typing import Iterator, Dict, Any, Optional, List, Union
from dataclasses import dataclass


class ClusterAddError(Exception):
    """Raised when IPFS Cluster /add operation fails"""
    def __init__(self, message: str, code: int = 0):
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass
class AddedFile:
    """Represents a successfully added file"""
    name: str
    cid: str  # Called "Hash" in older responses, "cid" in newer
    size: int
    
    @classmethod
    def from_response(cls, data: Dict[str, Any]) -> 'AddedFile':
        return cls(
            name=data.get('name') or data.get('Name', ''),
            cid=data.get('cid') or data.get('Hash', ''),
            size=int(data.get('size') or data.get('Size', 0))
        )


class IPFSClusterClient:
    """
    Client for IPFS Cluster REST API
    
    Usage:
        client = IPFSClusterClient('http://localhost:9094')
        
        # Recommended: buffered mode for reliability
        results = client.add_buffered(files={'file': open('test.txt', 'rb')})
        
        # Streaming mode for progress updates
        for entry in client.add_streaming(files={'file': open('test.txt', 'rb')}):
            print(f"Added: {entry.name} -> {entry.cid}")
    """
    
    def __init__(self, base_url: str, auth: Optional[tuple] = None, 
                 timeout: int = 300):
        """
        Initialize client.
        
        Args:
            base_url: Cluster API URL (e.g., 'http://localhost:9094')
            auth: Optional (username, password) tuple for basic auth
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.auth = auth
        self.timeout = timeout
        self.session = requests.Session()
        if auth:
            self.session.auth = auth
    
    def _check_for_error(self, data: Dict[str, Any]) -> None:
        """
        Check if a response object represents an error.
        Raises ClusterAddError if error detected.
        """
        # Check for explicit error type
        if data.get('Type') == 'error':
            raise ClusterAddError(
                data.get('Message', 'Unknown error'),
                data.get('Code', 0)
            )
        
        # Check for error message without type (some error formats)
        if 'Message' in data and 'cid' not in data and 'Hash' not in data:
            # Has Message but no CID - likely an error
            raise ClusterAddError(
                data.get('Message', 'Unknown error'),
                data.get('Code', 0)
            )
        
        # Check code field (non-zero usually indicates error in some responses)
        # Note: code=0 with message="" is success in AddedOutput format
        if data.get('code', 0) != 0 and data.get('message'):
            raise ClusterAddError(data['message'], data['code'])
    
    def _check_trailers(self, response: requests.Response) -> None:
        """
        Check HTTP trailers for X-Stream-Error.
        Only works with streaming responses.
        """
        try:
            if hasattr(response.raw, 'trailers') and response.raw.trailers:
                error_trailer = response.raw.trailers.get(b'X-Stream-Error')
                if error_trailer:
                    error_data = json.loads(error_trailer.decode('utf-8'))
                    raise ClusterAddError(
                        error_data.get('Message', str(error_data)),
                        error_data.get('Code', 0)
                    )
        except (AttributeError, json.JSONDecodeError):
            pass  # Trailers not available or not parseable
    
    def add_streaming(
        self,
        files: Dict[str, Any],
        name: Optional[str] = None,
        allocations: Optional[List[str]] = None,
        local: bool = False,
        cid_version: int = 1,
        raw_leaves: bool = True,
    ) -> Iterator[AddedFile]:
        """
        Add files with streaming response.
        
        Yields AddedFile objects as they are processed.
        Raises ClusterAddError if any error is detected.
        
        Args:
            files: Dict suitable for requests library files parameter
            name: Optional name for the pin
            allocations: Optional list of peer IDs to allocate to
            local: If True, only add to local peer
            cid_version: CID version (0 or 1)
            raw_leaves: Use raw leaves in DAG
            
        Yields:
            AddedFile objects for each successfully added file
        """
        params = {
            'local': str(local).lower(),
            'cid-version': str(cid_version),
            'raw-leaves': str(raw_leaves).lower(),
        }
        if name:
            params['name'] = name
        if allocations:
            params['allocations'] = ','.join(allocations)
        
        url = f"{self.base_url}/add"
        
        response = self.session.post(
            url, 
            files=files, 
            params=params, 
            stream=True,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        has_content = False
        
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.strip():
                continue
            
            has_content = True
            
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                raise ClusterAddError(f"Invalid JSON in response: {line[:100]}") from e
            
            # Check for error
            self._check_for_error(entry)
            
            # Yield successful entry
            yield AddedFile.from_response(entry)
        
        # Check for empty response (error occurred before streaming started)
        if not has_content:
            raise ClusterAddError(
                "Empty response body - server error occurred before streaming started"
            )
        
        # Check trailers for errors
        self._check_trailers(response)
    
    def add_buffered(
        self,
        files: Dict[str, Any],
        name: Optional[str] = None,
        allocations: Optional[List[str]] = None,
        local: bool = False,
        cid_version: int = 1,
        raw_leaves: bool = True,
    ) -> List[AddedFile]:
        """
        Add files with buffered response (RECOMMENDED).
        
        Uses stream-channels=false for reliable JSON array response.
        
        Args:
            files: Dict suitable for requests library files parameter
            name: Optional name for the pin
            allocations: Optional list of peer IDs to allocate to
            local: If True, only add to local peer
            cid_version: CID version (0 or 1)
            raw_leaves: Use raw leaves in DAG
            
        Returns:
            List of AddedFile objects
            
        Raises:
            ClusterAddError: If add operation fails
        """
        params = {
            'stream-channels': 'false',  # KEY: Request buffered response
            'local': str(local).lower(),
            'cid-version': str(cid_version),
            'raw-leaves': str(raw_leaves).lower(),
        }
        if name:
            params['name'] = name
        if allocations:
            params['allocations'] = ','.join(allocations)
        
        url = f"{self.base_url}/add"
        
        response = self.session.post(
            url, 
            files=files, 
            params=params,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        # Check for empty body
        body = response.text.strip()
        if not body:
            raise ClusterAddError(
                "Empty response body - server error occurred"
            )
        
        # Parse JSON
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise ClusterAddError(f"Invalid JSON response: {body[:200]}") from e
        
        # Handle single object (wrap in list)
        if isinstance(result, dict):
            self._check_for_error(result)
            return [AddedFile.from_response(result)]
        
        # Handle array
        if not isinstance(result, list):
            raise ClusterAddError(f"Unexpected response type: {type(result)}")
        
        # Check each entry for errors and convert
        results = []
        for entry in result:
            self._check_for_error(entry)
            results.append(AddedFile.from_response(entry))
        
        return results
    
    def add(
        self,
        files: Dict[str, Any],
        streaming: bool = False,
        **kwargs
    ) -> Union[List[AddedFile], Iterator[AddedFile]]:
        """
        Add files to cluster.
        
        Args:
            files: Dict suitable for requests library files parameter
            streaming: If True, use streaming mode; otherwise buffered
            **kwargs: Additional arguments passed to add_buffered/add_streaming
            
        Returns:
            List of AddedFile (buffered) or Iterator of AddedFile (streaming)
        """
        if streaming:
            return self.add_streaming(files, **kwargs)
        return self.add_buffered(files, **kwargs)


# Example usage and testing
if __name__ == '__main__':
    import sys
    import tempfile
    import os
    
    # Configuration
    CLUSTER_URL = os.environ.get('CLUSTER_URL', 'http://localhost:9094')
    
    print(f"Testing IPFS Cluster client against {CLUSTER_URL}")
    print("=" * 60)
    
    client = IPFSClusterClient(CLUSTER_URL)
    
    # Create test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Hello, IPFS Cluster!")
        test_file = f.name
    
    try:
        # Test buffered mode (recommended)
        print("\n1. Testing buffered mode (stream-channels=false)...")
        with open(test_file, 'rb') as f:
            try:
                results = client.add_buffered(files={'file': f})
                for r in results:
                    print(f"   Added: {r.name} -> {r.cid} ({r.size} bytes)")
            except ClusterAddError as e:
                print(f"   Error: {e.message}")
        
        # Test streaming mode
        print("\n2. Testing streaming mode...")
        with open(test_file, 'rb') as f:
            try:
                for entry in client.add_streaming(files={'file': f}):
                    print(f"   Added: {entry.name} -> {entry.cid} ({entry.size} bytes)")
            except ClusterAddError as e:
                print(f"   Error: {e.message}")
        
        print("\n" + "=" * 60)
        print("Tests completed!")
        
    finally:
        os.unlink(test_file)
```

### Minimal Implementation (Copy-Paste Ready)

```python
import json
import requests

def add_to_cluster(cluster_url: str, filepath: str) -> dict:
    """
    Add a file to IPFS Cluster with proper error handling.
    Uses buffered mode for reliability.
    
    Returns dict with 'cid', 'name', 'size' on success.
    Raises Exception on error.
    """
    url = f"{cluster_url.rstrip('/')}/add"
    params = {'stream-channels': 'false', 'cid-version': '1'}
    
    with open(filepath, 'rb') as f:
        response = requests.post(url, files={'file': f}, params=params)
    
    response.raise_for_status()
    
    if not response.text.strip():
        raise Exception("Empty response - server error")
    
    result = response.json()
    
    # Handle array response
    if isinstance(result, list):
        result = result[-1]  # Last entry is the root
    
    # Check for error
    if result.get('Type') == 'error' or ('Message' in result and 'cid' not in result):
        raise Exception(result.get('Message', 'Unknown error'))
    
    return {
        'cid': result.get('cid') or result.get('Hash'),
        'name': result.get('name') or result.get('Name'),
        'size': int(result.get('size') or result.get('Size', 0))
    }
```

---

## 6. Reference Links

### Source Code
- REST API: https://github.com/ipfs-cluster/ipfs-cluster/blob/master/api/rest/restapi.go
- Go Client: https://github.com/ipfs-cluster/ipfs-cluster/blob/master/api/rest/client/client.go
- ipfs-cluster-ctl: https://github.com/ipfs-cluster/ipfs-cluster/blob/master/cmd/ipfs-cluster-ctl/main.go

### Documentation
- REST API Reference: https://ipfscluster.io/documentation/reference/api/
- Go API Client: https://pkg.go.dev/github.com/ipfs-cluster/ipfs-cluster/api/rest/client

### Relevant Issues
- #632 - Proper JSON output (stream-channels=false): https://github.com/ipfs-cluster/ipfs-cluster/issues/632
- #810 - Streaming blocks on /add: https://github.com/ipfs-cluster/ipfs-cluster/issues/810
- #852 - Improve error handling on add: https://github.com/ipfs-cluster/ipfs-cluster/issues/852
- #1365 - Invalid JSON on failure: https://github.com/ipfs-cluster/ipfs-cluster/issues/1365

### Related Projects
- JS Client (deprecated): https://github.com/nftstorage/ipfs-cluster
- Python IPFS HTTP Client: https://github.com/ipfs-shipyard/py-ipfs-http-client

---

## 7. Version History

| Cluster Version | Notes |
|-----------------|-------|
| 0.8.0+ | `stream-channels=false` parameter added |
| 0.10.0+ | Streaming RPC for internal operations |
| 1.0.0+ | Block streaming to final destinations |
| 1.1.0+ | Current stable, no breaking API changes |

---

## Appendix: Response Object Schemas

### AddedOutput (Success)
```json
{
  "name": "filename.txt",
  "cid": "bafybeig...",
  "size": 12345,
  "allocations": ["peer1", "peer2"]
}
```

Note: Older versions use `Name`, `Hash`, `Size` (capitalized).

### Error Object
```json
{
  "Message": "not enough peers to allocate CID",
  "Code": 0,
  "Type": "error"
}
```

### Legacy AddedOutput (with code/message fields)
```json
{
  "code": 0,
  "message": "",
  "Name": "filename.txt",
  "Hash": "Qm...",
  "Size": "12345"
}
```

---

## 8. Local Investigation Results (2026-01-29)

### Bug Reproduction and Analysis

**Context:** community-cloud-storage Python client was returning `RC_SUCCESS` with empty entries when cluster had errors.

#### Diagnostic Test Results

Created test comparing streaming ON vs OFF with actual cluster:

**Test 1: Streaming Enabled (Default Behavior)**
```
POST /add?name=test-debug&local=true&allocations=...
Status: 200 OK
Headers:
  Trailer: X-Stream-Error
  X-Chunked-Output: 1
  Transfer-Encoding: chunked
  Content-Type: application/json
Body: (empty, 0 bytes)
Result: 0 entries parsed
```

**Test 2: Streaming Disabled (stream-channels=false)**
```
POST /add?name=test-debug&...&stream-channels=false
Status: 500 Internal Server Error
Body: {"code":500,"message":"not enough peers to allocate CID. Needed at least: 2. Wanted at most: 3. Available candidates: 1. See logs for more info."}
Result: Proper error visible
```

**Root Cause Confirmed:**
- Cluster returns errors via `X-Stream-Error` HTTP trailer
- Python requests library `response.text` is empty (trailer not exposed)
- Parser treats empty body as successful empty list
- No exception raised → returns `RC_SUCCESS` incorrectly

#### Code Audit: Vulnerable Locations

Found **5 locations** parsing NDJSON with same vulnerability:

1. **`ClusterClient._add_file()`** (cluster_api.py:212-221)
   - No validation of empty results
   - Risk: HIGH - core add operation

2. **`ClusterClient._add_directory()`** (cluster_api.py:285-293)
   - Same issue, uses MultipartEncoder
   - Risk: HIGH - core add operation

3. **`ClusterClient._add_directory_curl()`** (cluster_api.py:358-367)
   - Parses curl stdout, not HTTP response
   - May not show trailers in stdout
   - Risk: HIGH - large file uploads

4. **`ClusterClient.pins()`** (cluster_api.py:113-128)
   - Has partial protection: `if response.status_code == 204 or not response.text`
   - Still vulnerable to trailer errors
   - Risk: MEDIUM - GET operation

5. **`operations.peers()`** (operations.py:274-282)
   - Parses NDJSON directly in operations layer
   - No validation
   - Risk: MEDIUM - GET operation

**Current Error Handling Gaps:**
- `_request()` only checks HTTP 4xx/5xx status codes
- No trailer header checking anywhere
- No validation that `len(results) > 0` for add operations
- Tests only cover happy path

#### Additional Bug: URL Encoding

Tests document but don't fix URL encoding issues:
- File names with spaces not encoded: `"my file.txt"` → should be `"my%20file.txt"`
- Special chars break query string: `"file&name=bad"` → should be `"file%26name%3Dbad"`
- Could cause cluster to fail parsing query params

**Current implementation:**
```python
def _build_add_params(self, name: str, allocations: list[str] = None, 
                      local: bool = True) -> str:
    params = [f"name={name}"]  # No URL encoding!
    if allocations:
        params.append(f"allocations={','.join(allocations)}")
    if local:
        params.append("local=true")
    return "&".join(params)
```

#### Test Coverage Gaps

Existing tests in `test_cluster_api.py`:
- ✅ Mock successful NDJSON responses
- ✅ Verify query parameter construction
- ✅ Document URL encoding bugs
- ❌ No tests for empty response body
- ❌ No tests for error responses
- ❌ No tests for trailer headers
- ❌ No tests for inline error objects

---

## 9. Implementation Plan

### Strategy: Hybrid Approach

Based on research recommendations and local testing, implement **buffered mode with inline error detection**.

### Phase 1: Add `stream-channels=false` (Primary Fix)

**Goal:** Make errors visible as proper HTTP status codes with JSON body

**Changes to `cluster_api.py`:**

```python
def _build_add_params(
    self, name: str, allocations: list[str] = None, local: bool = True
) -> str:
    """Build query string for /add endpoint."""
    from urllib.parse import urlencode
    
    params = {
        "name": name,
        "stream-channels": "false",  # CRITICAL: Enable buffered mode
    }
    
    if allocations:
        params["allocations"] = ",".join(allocations)
    
    if local:
        params["local"] = "true"
    
    return urlencode(params)  # Proper URL encoding
```

**Benefits:**
- ✅ Errors return HTTP 500 with JSON body
- ✅ Existing `_request()` error handling catches them
- ✅ Response is valid JSON array (easier parsing)
- ✅ Fixes URL encoding simultaneously
- ✅ One-line change to fix 3 add methods

**Trade-off:**
- ⚠️ Response buffered in memory (acceptable per docs: "perfectly fine for regular usage")
- ⚠️ No progress updates during upload (acceptable for CCS use case)

### Phase 2: Response Validation (Defense in Depth)

**Goal:** Catch any errors that slip through

**Add validation to all parse sites:**

```python
# In _add_file(), _add_directory(), _add_directory_curl()
results = []
for line in response.text.strip().split("\n"):
    if line:
        entry = json.loads(line)
        
        # Check for inline error object
        if entry.get("Type") == "error":
            raise ClusterAPIError(
                entry.get("Message", "Unknown cluster error"),
                entry.get("Code", 0)
            )
        
        results.append(entry)

# Validate non-empty results for add operations
if len(results) == 0:
    raise ClusterAPIError(
        "Empty response from cluster - possible server error. "
        f"Status: {response.status_code}, Body: {response.text[:200]}"
    )

return results
```

**Add to `operations.add()` as final safety net:**

```python
# operations.py:169 - after client.add() returns
if not entries_raw:
    return AddResult(
        root_cid="",
        root_path=str(path),
        entries=[],
        allocations=allocations,
        profile=profile,
        added_at=datetime.now(timezone.utc),
        cluster_host=target_host or "",
        returncode=RC_FAILED,  # Not RC_SUCCESS!
        error="No entries returned from cluster (possible cluster error)",
    )
```

### Phase 3: Handle Response Format Changes

**Goal:** Support both array and single-object responses from buffered mode

Research shows `stream-channels=false` returns valid JSON array. Update parsing:

```python
# In _add_file(), _add_directory() after getting response
body = response.text.strip()
if not body:
    raise ClusterAPIError("Empty response body")

# Parse JSON (could be array or single object)
try:
    data = json.loads(body)
except json.JSONDecodeError as e:
    raise ClusterAPIError(f"Invalid JSON: {body[:200]}") from e

# Handle both formats
if isinstance(data, list):
    results = data
elif isinstance(data, dict):
    # Single object response (for single file)
    results = [data]
else:
    raise ClusterAPIError(f"Unexpected response type: {type(data)}")

# Check each entry for errors
for entry in results:
    if entry.get("Type") == "error":
        raise ClusterAPIError(
            entry.get("Message", "Unknown error"),
            entry.get("Code", 0)
        )

return results
```

### Phase 4: Update Tests

**Add comprehensive error handling tests:**

```python
# test_cluster_api.py

def test_add_with_empty_response():
    """Empty response body should raise error."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    
    with pytest.raises(ClusterAPIError, match="Empty response"):
        # Should fail validation

def test_add_with_inline_error():
    """Inline error object should raise ClusterAPIError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"Type":"error","Message":"not enough peers","Code":0}'
    
    with pytest.raises(ClusterAPIError, match="not enough peers"):
        # Should detect error object

def test_add_with_stream_channels_false():
    """Verify stream-channels=false is added to query."""
    # Check that _build_add_params includes it

def test_url_encoding():
    """File names with special chars should be URL encoded."""
    result = client._build_add_params("my file&name.txt")
    assert "my+file" in result or "my%20file" in result
    assert "%26" in result  # & encoded
```

### Phase 5: Documentation Updates

**Update docstrings to reflect buffered mode:**

```python
def add(self, path: Path, ...) -> list:
    """
    Add a file or directory to the cluster.
    
    Uses buffered mode (stream-channels=false) for reliable error handling.
    Response is buffered in memory and returned as complete JSON array.
    
    Returns:
        List of dicts with 'name', 'cid', 'size', 'allocations' for each item.
        Last item is the root CID.
        
    Raises:
        ClusterAPIError: If cluster returns error or response is invalid
    """
```

**Add migration note to README/CHANGELOG:**
```markdown
## Breaking Change: Buffered Add Mode

v0.5.0 switches to buffered mode (stream-channels=false) for /add operations.

**Why:** Streaming mode errors were invisible (returned via HTTP trailers).
**Impact:** Large uploads buffer in memory. If you upload >1GB files, monitor memory.
**Alternative:** For huge uploads, use ipfs-cluster-ctl directly with --no-stream.
```

---

## 10. Implementation Checklist

### Files to Modify

- [ ] `src/community_cloud_storage/cluster_api.py`
  - [ ] Update `_build_add_params()` - add stream-channels=false + URL encoding
  - [ ] Update `_add_file()` - validate results, check inline errors
  - [ ] Update `_add_directory()` - validate results, check inline errors
  - [ ] Update `_add_directory_curl()` - validate results
  - [ ] Update `pins()` - validate results (optional but recommended)
  - [ ] Add docstring notes about buffered mode

- [ ] `src/community_cloud_storage/operations.py`
  - [ ] Update `add()` - validate entries_raw not empty before parsing
  - [ ] Update `peers()` - validate results (optional)
  - [ ] Update docstrings

- [ ] `test/test_cluster_api.py`
  - [ ] Add test_add_with_empty_response
  - [ ] Add test_add_with_inline_error
  - [ ] Add test_add_buffered_mode
  - [ ] Add test_url_encoding_special_chars
  - [ ] Update existing tests for new response format

- [ ] Documentation
  - [ ] Update README.md - note buffered mode
  - [ ] Add CHANGELOG entry
  - [ ] Update BUG-add-returns-empty-entries.md - mark as resolved

### Testing Plan

1. **Unit tests** - Mock responses with errors
2. **Integration test** - Real cluster with insufficient peers (reproduce bug)
3. **Success test** - Verify normal adds still work
4. **Large file test** - Ensure buffered mode handles large uploads
5. **Special char test** - File names with spaces, &, =, etc.

### Rollout Strategy

1. Implement Phase 1 (stream-channels=false)
2. Run full test suite
3. Test against real cluster
4. Implement Phase 2 (validation)
5. Run tests again
6. Deploy and monitor

### Success Criteria

✅ Test from BUG-add-returns-empty-entries.md passes:
```python
result = add(test_dir, profile="hrdag", config=cfg, recursive=True)
assert result.returncode == RC_SUCCESS
assert result.root_cid != ""
assert len(result.entries) > 0
assert any(e.is_root for e in result.entries)
```

✅ Error case properly fails:
```python
# With insufficient peers
result = add(test_dir, profile="hrdag", config=cfg)
assert result.returncode == RC_FAILED
assert "not enough peers" in result.error
```

---

## 11. Alternative Considered: Keep Streaming Mode

**Why we rejected this:**

Would require:
- Parsing HTTP trailers (requests library doesn't expose them easily)
- Switching to httpx or raw sockets
- Significantly more complex implementation
- Still vulnerable to edge cases

**When to reconsider:**
- If memory becomes a constraint (very large uploads)
- If real-time progress updates are needed
- If cluster deployment ensures no peering errors

For CCS use case (community archive uploads), buffered mode is appropriate.

---
