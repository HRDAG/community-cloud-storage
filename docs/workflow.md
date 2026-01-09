<!--
Author: PB and Claude
Date: 2025-01-09
License: (c) HRDAG, 2025, GPL-2 or newer

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
   cluster:
     basic_auth_user: admin
     basic_auth_password: <your-password>
   ```

3. Be on the Tailnet (Tailscale connected)

## Adding Files

Upload a file from your local machine to the cluster:

```bash
ccs add --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml /path/to/file
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
ccs status <CID> --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
```

Look for `"status": "pinned"` on each node in `peer_map`.

## Listing Pins

List all CIDs pinned in the cluster:

```bash
ccs ls --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
```

## Retrieving Files

Download a file by CID:

```bash
ccs get <CID> --cluster-peername nas-ccs --output /path/to/output
```

Note: `get` uses the IPFS gateway (port 8080) and does not require authentication.

## Removing Files

Unpin a CID from the cluster:

```bash
ccs rm <CID> --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
```

## Example Session

```bash
# Create a test file
echo "Hello from CCS" > /tmp/test.txt

# Add to cluster
ccs add --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml /tmp/test.txt
# → root CID: QmXYZ...

# Check replication
ccs status QmXYZ... --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
# → pinned on nas-ccs AND meerkat-ccs

# Retrieve from cluster
ccs get QmXYZ... --cluster-peername nas-ccs --output /tmp/retrieved.txt
cat /tmp/retrieved.txt
# → Hello from CCS

# Clean up
ccs rm QmXYZ... --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
```

## Cluster Nodes

| Node | Tailnet Hostname | Role |
|------|------------------|------|
| nas-ccs | nas-ccs | Bootstrap node |
| meerkat-ccs | meerkat-ccs | Replica node |

## Ports

| Port | Service | Access |
|------|---------|--------|
| 9094 | Cluster API | Tailnet (auth required) |
| 8080 | IPFS Gateway | Tailnet (read-only, no auth) |
| 5001 | IPFS API | Localhost only (hardened) |
