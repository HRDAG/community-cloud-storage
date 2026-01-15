# Author: PB and Claude
# Date: 2026-01-15
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# community-cloud-storage/docs/BUG-cluster-not-persisting-pins.md

# Bug Report: IPFS Cluster Not Persisting Pin Records

## Status: RESOLVED

**Resolution**: The symptoms were caused by `~/.ccs/config.yml` still using LAN hostnames instead of tailscale IPs. Once the config was updated, the same directory adds and pins correctly.

**Root cause**: The code fixes (commit b7dc09f) require `~/.ccs/config.yml` to use tailscale IPs (e.g., `host: 100.64.0.31` instead of `host: nas`). The LAN hostname resolved to an IP where the cluster API wasn't listening, causing the add to go through a different path that didn't properly persist pins.

**Verification** (2026-01-15):
```python
# Same directory that "failed" now works:
result = add(Path('/var/tmp/ntx/staging/commit_2026-01-07T03:33:17Z'),
             profile='hrdag', config=cfg)
# cid: QmdnpfPD4duTF3dz6Nnn3D9VLhH8wfupZsonVQwPDY8TKN
# allocations: 3 peers
# pinned_count: 3
# nas: pinned, chll: pinned, ipfs1: pinned
```

**Note**: Content added before the fix (e.g., `QmcSmYJ9A4J1WFzGPEzpdbQ6KLNPptkops1Cksj1SwXQDF`) remains unpinned and needs to be manually re-added or pinned via `ipfs-cluster-ctl pin add <CID>`.

---

## Original Report (for historical reference)

## Summary

After fixing the `is_fully_pinned()` and allocation bugs (commit b7dc09f), we discovered a deeper issue: the IPFS cluster accepts add requests with allocations and returns success with allocation info, but **does not persist the pin records**. Subsequent status queries show empty allocations and all nodes report "unpinned".

## Environment

- community-cloud-storage: b7dc09f (post-fix)
- IPFS Cluster: 5 nodes (nas, meerkat, chll, pihost, ipfs1)
- Profile: hrdag (primary=nas, backup=chll)
- Config: Using tailscale IPs (100.64.x.x)
- Tested: 2026-01-15

## Symptoms

### 1. Add Operation Returns Allocations

```
POST http://100.64.0.31:9094/add?name=commit_2026-01-07T03:33:17Z&allocations=12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ,12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj&local=true HTTP/1.1" 200

Response:
{"name":"commit_.../manifest.json",
 "cid":"QmcSmYJ9A4J1WFzGPEzpdbQ6KLNPptkops1Cksj1SwXQDF",
 "size":24700,
 "allocations":["12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj",
                "12D3KooWFdQri2MC953pHjsuDoV9orWmhczfgrimPYqYjn8jx5Yn",
                "12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ"]}
```

The cluster returned 3 allocations: chll, ipfs1, nas. This looks correct.

### 2. Status Query Shows No Allocations

Immediately after add, querying status:

```
GET http://100.64.0.32:9094/pins/QmcSmYJ9A4J1WFzGPEzpdbQ6KLNPptkops1Cksj1SwXQDF HTTP/1.1" 200

Response:
{"cid":"QmcSmYJ9A4J1WFzGPEzpdbQ6KLNPptkops1Cksj1SwXQDF",
 "name":"",
 "allocations":[],
 "created":"2026-01-15T20:39:42.854564198Z",
 "peer_map":{
   "12D3KooWEAMhQTa1...":{"peername":"pihost","status":"unpinned",...},
   "12D3KooWFCXpnVGG...":{"peername":"meerkat","status":"unpinned",...},
   "12D3KooWFdQri2MC...":{"peername":"ipfs1","status":"unpinned",...},
   "12D3KooWMJJ4ZVwH...":{"peername":"chll","status":"unpinned",...},
   "12D3KooWRwzo72Zs...":{"peername":"nas","status":"unpinned",...}
 }}
```

**Key observations:**
- `allocations: []` - empty, despite add returning 3 allocations
- `name: ""` - empty, despite add specifying a name
- All peers show `status: "unpinned"`
- `created` timestamp is the query time, not the add time

### 3. Same Result From All Nodes

Querying status from nas (where add was performed):
```python
result = ccs_status(cid, cfg, host='nas')
# allocations: [], pinned_count: 0
```

Querying from chll (default node):
```python
result = ccs_status(cid, cfg, host='chll')
# allocations: [], pinned_count: 0
```

The pin records don't exist on any node.

## Reproduction

```python
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add, status

cfg = load_config()

# Add content - this succeeds and returns allocations
result = add(Path('/tmp/test-dir'), profile='hrdag', config=cfg)
print(f"Add allocations: {result.allocations}")
# ['12D3KooWRwzo72...', '12D3KooWMJJ4ZV...']

# Query status - allocations are gone
cid = result.root_cid
pin_status = status(cid, cfg)
print(f"Status allocations: {pin_status.allocations}")
# []
print(f"Pinned count: {pin_status.pinned_count()}")
# 0
```

## Analysis

### What's Working

1. **ccs code is correct**:
   - `add()` properly computes allocations from profile
   - Connects to profile's primary node (nas)
   - Passes `local=true` parameter
   - Sends allocations in query string

2. **Cluster API accepts the request**:
   - Returns HTTP 200
   - Returns CIDs for all files
   - Returns allocations in response

### What's Broken

The cluster is not persisting pin records. Possible causes:

1. **Cluster consensus failure**: Pin records may not be reaching quorum
2. **Add vs Pin semantics**: The `/add` endpoint may only add content to IPFS without creating cluster pin records
3. **Pin queue issue**: Pins may be queued but not processed
4. **Replication config**: `replication_factor_min`/`max` may be misconfigured
5. **Disk/storage issue**: Pin database may be failing to write

### Evidence the Content Exists in IPFS

The content IS in IPFS - the CIDs are valid and the files were uploaded. But the cluster pin management layer isn't tracking them.

## Comparison: Working vs Non-Working

### Test That Works (small test directory)

```python
# Small test with single file
result = add(Path('/tmp/ccs-test'), profile='hrdag', config=cfg)
pin_status = status(result.root_cid, cfg)

# This worked:
# allocations: ['chll', 'ipfs1', 'nas']
# pinned_count: 1
# nas: pinned, chll: pinning, ipfs1: pinning
```

### Test That Fails (ntx commit directory with 61 files)

```python
# Large directory with 61 files (29 .enc + 29 .sidecar + 3 metadata)
result = add(Path('/var/tmp/ntx/staging/commit_2026-01-07T03:33:17Z'),
             profile='hrdag', config=cfg)
pin_status = status(result.root_cid, cfg)

# This failed:
# allocations: []
# pinned_count: 0
# all nodes: unpinned
```

**Hypothesis**: The cluster may have issues with large batch adds. The small test worked but the larger commit directory failed.

## Debug Information

### Request Details (from CCS_DEBUG=1)

```
add() called: path=/var/tmp/ntx/staging/commit_2026-01-07T03:33:17Z,
              name=commit_2026-01-07T03:33:17Z,
              allocations=['12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ',
                          '12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj'],
              local=True

_add_directory: found 61 files
_add_directory: query string = name=commit_2026-01-07T03:33:17Z&allocations=12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ,12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj&local=true

Request: POST http://100.64.0.31:9094/add?name=...&allocations=...&local=true
Response status: 200
```

### Cluster Configuration (needs verification)

```yaml
# ~/.ccs/config.yml
default_node: chll
backup_node: chll

profiles:
  hrdag:
    primary: nas

nodes:
  nas:
    host: 100.64.0.31  # tailscale IP
    peer_id: 12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ
  chll:
    host: 100.64.0.32
    peer_id: 12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj
  # ... other nodes
```

## Investigation Steps Needed

1. **Check cluster logs on nas during add**:
   ```bash
   journalctl -u ipfs-cluster -f  # during add operation
   ```

2. **Check cluster pin state directly**:
   ```bash
   ipfs-cluster-ctl pin ls <CID>
   ipfs-cluster-ctl status <CID>
   ```

3. **Check cluster configuration**:
   ```bash
   ipfs-cluster-ctl config show | grep -E "replication|consensus"
   ```

4. **Test with ipfs-cluster-ctl directly**:
   ```bash
   ipfs-cluster-ctl add --allocations=<peer1>,<peer2> /path/to/dir
   ipfs-cluster-ctl pin ls  # check if pin exists
   ```

5. **Check if it's a batch size issue**:
   - Try adding a single file vs directory
   - Try smaller directories
   - Check if there's a limit on files per add

6. **Check cluster health**:
   ```bash
   ipfs-cluster-ctl peers ls
   ipfs-cluster-ctl health alerts
   ```

## Impact

- **Data at risk**: Content is added to IPFS but not tracked by cluster
- **No replication**: Without pin records, cluster won't replicate content
- **GC vulnerability**: Unpinned content may be garbage collected
- **False success**: Add returns success but content isn't properly managed

## Workaround

None currently. The content needs to be manually pinned via `ipfs-cluster-ctl pin add <CID>` after upload.

## Related

- Previous bug report: `BUG-is_fully_pinned-and-missing-allocations.md` (fixed in b7dc09f)
- The `is_fully_pinned()` and allocation fixes are working correctly
- This is a deeper cluster-level issue
