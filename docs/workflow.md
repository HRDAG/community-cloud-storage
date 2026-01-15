<!--
Author: PB and Claude
Date: 2026-01-14
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/workflow.md
-->

# CCS Workflow

## Prerequisites

1. Install the `ccs` command:
   ```bash
   ./install.sh
   ```

2. Create config file `~/.ccs/config.yml`:
   ```yaml
   # Authentication (required)
   cluster:
     basic_auth_user: admin
     basic_auth_password: <your-password>

   # Default node for CLI commands
   default_node: nas

   # Shared backup node (all orgs replicate here)
   backup_node: chll

   # Organization profiles
   profiles:
     hrdag:
       primary: nas
     test-orgB:
       primary: meerkat

   # Cluster nodes with peer IDs (populated by ansible)
   nodes:
     nas:
       host: nas
       peer_id: 12D3KooW...
     meerkat:
       host: meerkat
       peer_id: 12D3KooW...
     chll:
       host: chll
       peer_id: 12D3KooW...
   ```

   See `config.yml.example` in repo root for full template.

3. Set permissions: `chmod 600 ~/.ccs/config.yml`

4. Be on the Tailnet (Tailscale connected)

5. Validate your config:
   ```bash
   ccs config
   ```

## Adding Files

Upload a file or directory to the cluster using a profile:

```bash
ccs add /path/to/file --profile hrdag
```

Output:
```
added /path/to/file with profile hrdag
root CID: QmVqTRe9i8eydScA3ZYmTJ8SYNT4CRDBfBWqen63VuyKBP
entries: 1
allocations: 12D3KooWRwzo..., 12D3KooWMJJ4...
```

The file is pinned to:
1. Your profile's primary node (nas for hrdag)
2. The backup node (chll)
3. One additional node chosen by the cluster allocator

### Saving the manifest

To save the full result as JSON for database storage:

```bash
ccs add /path/to/directory --profile hrdag --output-json manifest.json
```

The manifest contains:
- `root_cid`: The root CID
- `entries`: All files/directories with their individual CIDs
- `allocations`: Peer IDs where content is pinned
- `returncode`: 0 for success, non-zero for errors

## Checking Status

Verify a CID is pinned and replicated:

```bash
ccs status <CID>
```

Returns JSON with pin status across all nodes. Look for `"status": "pinned"` in `peer_map`.

## Listing Pins

List all CIDs pinned in the cluster:

```bash
ccs ls
```

Returns JSON array of all pins with replication info.

## Listing Peers

List all nodes in the cluster:

```bash
ccs peers
```

Returns JSON array of peer info including names and addresses.

## Validating Config

Check your configuration for errors:

```bash
ccs config                    # Display config with validation
ccs config --validate-only    # Just check for errors
ccs config --output-json config-check.json   # Export validation results
```

## Retrieving Files

Download a file by CID (uses IPFS gateway, no auth required):

```bash
ccs get <CID> --cluster-peername nas --output /path/to/output
```

## Removing Files

Unpin a CID from the cluster:

```bash
ccs rm <CID> --cluster-peername nas
```

**Warning:** This removes the pin from all nodes. Use with caution.

## Example Session

```bash
# Validate config first
ccs config --validate-only

# Create a test directory
mkdir -p /tmp/test-archive
echo "File 1" > /tmp/test-archive/file1.txt
echo "File 2" > /tmp/test-archive/file2.txt

# Add to cluster with manifest
ccs add /tmp/test-archive --profile hrdag --output-json /tmp/manifest.json

# Check the manifest
cat /tmp/manifest.json | jq '.root_cid, .entries | length'
# → "QmXYZ..."
# → 3

# Verify replication
ccs status $(cat /tmp/manifest.json | jq -r '.root_cid')

# List all pins
ccs ls | jq 'length'
```

## Library Usage

CCS can be imported as a Python library:

```python
from community_cloud_storage import add, load_config, RC_SUCCESS

config = load_config()
result = add("/path/to/file", profile="hrdag", config=config)

if result.ok:  # or: result.returncode == RC_SUCCESS
    print(f"Added: {result.root_cid}")
    # Save to database
    db.store(result.to_json())
else:
    print(f"Error: {result.error}")
```

## Cluster Nodes

| Node | Tailnet Hostname | Role | Org |
|------|------------------|------|-----|
| nas | nas | primary | hrdag |
| meerkat | meerkat | primary | test-orgB |
| chll | chll | backup | shared |
| pihost | pihost | primary | test-orgC |
| ipfs1 | ipfs1 | primary | test-orgD |

See `docs/architecture-plan.md` for full cluster topology.

## Ports

| Port | Service | Access |
|------|---------|--------|
| 9094 | Cluster API | Tailnet (auth required) |
| 8080 | IPFS Gateway | Tailnet (read-only, no auth) |
| 5001 | IPFS API | Localhost only (hardened) |
