Author: PB and Claude
Date: 2026-02-09
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/REFERENCE.md

# CCS Cluster Reference

## Architecture

- Each node runs ipfs-cluster in a Docker container (`ccs-cluster`)
- CCS talks to cluster REST API on port 9094 (via Tailscale IPs)
- No `ipfs-cluster-ctl` needed from client — CCS uses HTTP API directly
- Cluster uses CRDT consensus (no raft leader election)
- Version: 1.1.5

## Node Inventory

| Node    | Tailscale IP | LAN IP        | Role    |
|---------|-------------|---------------|---------|
| nas     | 100.64.0.31 | 192.168.1.8   | primary (hrdag) |
| chll    | 100.64.0.32 | 209.121.245.6 | backup  |
| meerkat | 100.64.0.4  | 192.168.1.34  | primary (test-orgB) |
| pihost  | 100.64.0.2  | 192.168.1.25  | primary (test-orgC) |
| ipfs1   | 100.64.0.51 | 192.168.1.24  | primary (test-orgD) |

## CCS Commands

| Command | Purpose |
|---------|---------|
| `ccs add <path> --profile <name>` | Add file/directory to cluster with org+size metadata |
| `ccs status <cid>` | Show pin status across all nodes |
| `ccs ls` | List all pinned CIDs |
| `ccs peers` | List cluster peers and online status |
| `ccs health` | Cluster health summary (exit: 0=ok, 1=degraded, 2=error) |
| `ccs repair` | Detect and recover broken pins (exit: 0=clean, 1=fixed, 2=lost) |
| `ccs ensure-pins --profile <name>` | Fix allocation policy gaps |
| `ccs get <cid> --dest <path>` | Download a pinned CID |
| `ccs config --validate-only` | Validate configuration |

Most commands support `--host`, `--json`, `--output`, `--dry-run` where applicable.

## Quick Health Check

From any machine with CCS installed:

```bash
# Cluster health summary (peers + pin errors)
uv run ccs health

# List all peers and their status
uv run ccs peers

# Detect and fix broken pins
uv run ccs repair --dry-run

# Validate config
uv run ccs config --validate-only
```

Or raw API (from scott, using chll as entry point):

```bash
AUTH=$(sudo cat /etc/tfc/keys/ccs-auth)
# Peers (NDJSON — one JSON object per line)
curl -s -u "$AUTH" http://100.64.0.32:9094/peers | jq -s .

# Single peer identity
curl -s -u "$AUTH" http://100.64.0.32:9094/id | jq .
```

Note: cluster API returns NDJSON, not JSON arrays. Use `jq -s .` to collect
into an array, or process line-by-line.

## Diagnostic Procedures

### Node Not Responding

#### Step 1: Check from client

```bash
# Ping Tailscale IP
ping -c1 -W2 <tailscale-ip>

# Check cluster API
curl -v -m5 -u "$AUTH" http://<tailscale-ip>:9094/id
```

Results:
- **Ping OK, port 9094 refused** — machine up, container down
- **Ping OK, port 9094 timeout** — firewall or container not listening
- **Ping fails** — machine offline or Tailscale down

#### Step 2: SSH to the node

```bash
ssh <node>

# Check container status
sudo docker ps -a | grep cluster
sudo docker ps -a | grep ipfs

# Check logs
sudo docker logs ccs-cluster --tail 50

# Check if in restart loop
sudo docker inspect ccs-cluster --format='{{.State.Status}} restarts={{.RestartCount}}'
```

#### Step 3: Container in restart loop

If `docker ps` shows "Restarting":

```bash
# Read the crash logs
sudo docker logs ccs-cluster --tail 100

# Common causes:
# 1. IPFS container not running (cluster can't connect to IPFS API)
sudo docker ps | grep ipfs
sudo docker start ccs-ipfs  # if stopped

# 2. Corrupt datastore
# Check for lock files or corrupt badger DB
sudo docker exec ccs-cluster ls -la /data/ipfs-cluster/

# 3. Bootstrap peer unreachable
# Check CLUSTER_PEERADDRESSES in docker-compose or env
sudo docker inspect ccs-cluster | grep -i peer

# 4. Port conflict
sudo ss -tlnp | grep 9094
```

#### Step 4: Container not running (exited)

```bash
# Check exit code
sudo docker inspect ccs-cluster --format='{{.State.ExitCode}}'

# Try restarting
sudo docker start ccs-cluster
sudo docker logs -f ccs-cluster  # watch startup
```

### Peer ID Mismatch

If a node's peer ID in `/etc/tfc/ccs.toml` doesn't match what the cluster
sees, the container was likely recreated without preserving identity.

```bash
# Check actual peer ID on the node
ssh <node> 'sudo docker exec ccs-cluster ipfs-cluster-ctl id 2>&1 | head -1'

# Compare with config
grep -A2 'nodes.<node>' /etc/tfc/ccs.toml
```

Fix: update `peer_id` in `/etc/tfc/ccs.toml` (or better, in ansible vars)
to match the actual peer ID. The cluster identity is stored in the container's
persistent volume — if that volume was lost, a new identity was generated.

### Stale Peer in Cluster

If the cluster remembers a peer that no longer exists:

```bash
# The cluster (CRDT mode) doesn't have a "remove peer" command.
# Stale peers will show "failed to dial" but are harmless.
# They'll be cleaned up when/if the peer comes back with the same ID,
# or can be ignored.
```

### Disk Full

If container logs show `disk quota exceeded` on lock file creation:

```bash
# Check disk usage
df -h
# Find what's using the CCS data disk
sudo du -sh /mnt/sda1/*/ | sort -h
# Check IPFS data size specifically
sudo du -sh /mnt/sda1/ccs/ipfs/ /mnt/sda1/ccs/ipfs-cluster/
```

The cluster container will auto-restart once disk space is freed. No manual
intervention needed beyond freeing space.

### Disk Replacement

Full procedure for replacing a data disk on a CCS node:

1. Stop containers: `sudo docker compose -f /mnt/sda1/ccs/compose.yml down`
2. Physically swap the disk (or mount new disk at a temporary path)
3. Partition + format: `sudo mkfs.ext4 /mnt/newdisk`
4. Mount new disk and rsync preserving permissions:
   `rsync -aHAX /mnt/sda1/ccs/ /mnt/newdisk/ccs/`
5. Update `/etc/fstab` to mount new disk at the expected path
6. Unmount old, remount new at original path
7. Start containers: `sudo docker compose -f /mnt/sda1/ccs/compose.yml up -d`

Important:
- **Stop containers before copying** — badger DB is not safe to copy while running
- **Preserve ownership/permissions** — containers run as specific uid
- **Copy everything** — IPFS datastore + cluster state (identity keys, CRDT state)
- If cluster identity is lost, peer gets a new ID (requires config update)
