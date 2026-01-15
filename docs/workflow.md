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

## Adding Files

Upload a file from your local machine to the cluster:

```bash
ccs add --cluster-peername nas --basic-auth-file ~/.ccs/config.yml /path/to/file
```

Output:
```
adding /path/to/file to nas-ccs
root CID: QmVqTRe9i8eydScA3ZYmTJ8SYNT4CRDBfBWqen63VuyKBP
entries: 1
```

The file is uploaded via HTTP to the cluster API and automatically replicated to all nodes.

## Checking Status

Verify a file is pinned and replicated:

```bash
ccs status <CID> --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
```

Look for `"status": "pinned"` on each node in `peer_map`.

## Listing Pins

List all CIDs pinned in the cluster:

```bash
ccs ls --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
```

## Retrieving Files

Download a file by CID:

```bash
ccs get <CID> --cluster-peername nas --output /path/to/output
```

Note: `get` uses the IPFS gateway (port 8080) and does not require authentication.

## Removing Files

Unpin a CID from the cluster:

```bash
ccs rm <CID> --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
```

## Example Session

```bash
# Create a test file
echo "Hello from CCS" > /tmp/test.txt

# Add to cluster
ccs add --cluster-peername nas --basic-auth-file ~/.ccs/config.yml /tmp/test.txt
# → root CID: QmXYZ...

# Check replication
ccs status QmXYZ... --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
# → pinned on nas AND meerkat

# Retrieve from cluster
ccs get QmXYZ... --cluster-peername nas --output /tmp/retrieved.txt
cat /tmp/retrieved.txt
# → Hello from CCS

# Clean up
ccs rm QmXYZ... --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
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
