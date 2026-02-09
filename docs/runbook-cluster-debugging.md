# CCS Cluster Debugging Runbook
Author: PB and Claude
Date: 2026-02-08
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/runbook-cluster-debugging.md

## Architecture

- Each node runs ipfs-cluster in a Docker container (`ccs-cluster`)
- CCS talks to cluster REST API on port 9094 (via Tailscale IPs)
- No `ipfs-cluster-ctl` needed from client — CCS uses HTTP API directly
- Cluster uses CRDT consensus (no raft leader election)
- Version: 1.1.5

## Quick Health Check

From any machine with CCS installed:

```bash
# List all peers and their status
uv run ccs peers

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

## Node Inventory

| Node    | Tailscale IP | LAN IP        | Role    |
|---------|-------------|---------------|---------|
| nas     | 100.64.0.31 | 192.168.1.8   | primary (hrdag) |
| chll    | 100.64.0.32 | 209.121.245.6 | backup  |
| meerkat | 100.64.0.4  | 192.168.1.34  | primary (test-orgB) |
| pihost  | 100.64.0.2  | 192.168.1.x   | primary (test-orgC) |
| ipfs1   | 100.64.0.51 | 192.168.1.24  | primary (test-orgD) |

## Diagnosis: Node Not Responding

### Step 1: Check from client

```bash
# Ping Tailscale IP
ping -c1 -W2 <tailscale-ip>

# Check cluster API
curl -v -m5 -u "$AUTH" http://<tailscale-ip>:9094/id
```

Results:
- **Ping OK, port 9094 refused** → machine up, container down
- **Ping OK, port 9094 timeout** → firewall or container not listening
- **Ping fails** → machine offline or Tailscale down

### Step 2: SSH to the node

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

### Step 3: Container in restart loop

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

### Step 4: Container not running (exited)

```bash
# Check exit code
sudo docker inspect ccs-cluster --format='{{.State.ExitCode}}'

# Try restarting
sudo docker start ccs-cluster
sudo docker logs -f ccs-cluster  # watch startup
```

## Diagnosis: Peer ID Mismatch

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

## Diagnosis: Stale Peer in Cluster

If the cluster remembers a peer that no longer exists:

```bash
# The cluster (CRDT mode) doesn't have a "remove peer" command.
# Stale peers will show "failed to dial" but are harmless.
# They'll be cleaned up when/if the peer comes back with the same ID,
# or can be ignored.
```

## Diagnosis: Disk Full

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

### Moving IPFS data to a bigger disk

1. Stop containers: `sudo docker compose -f /mnt/sda1/ccs/compose.yml down`
2. rsync preserving permissions: `rsync -aHAX /mnt/sda1/ccs/ /mnt/newdisk/ccs/`
3. Update compose.yml volume mounts (or symlink old path to new)
4. Start containers: `sudo docker compose -f /path/to/compose.yml up -d`

Important:
- **Stop containers before copying** — badger DB is not safe to copy while running
- **Preserve ownership/permissions** — containers run as specific uid
- **Copy everything** — IPFS datastore + cluster state (identity keys, CRDT state)
- If cluster identity is lost, peer gets a new ID (requires config update)

## 2026-02-08 Incident Notes

### pihost (100.64.0.2)
- Machine up (ping OK), port 9094 connection refused
- Container `ccs-cluster` in restart loop: **disk quota exceeded**
- `/mnt/sda1` at 99% (7.2T/7.3T) — only 1TB is CCS, rest is other data
- Not in any peer's `cluster_peers` list
- **Fix**: free space on /mnt/sda1, container will auto-restart

### ipfs1 (100.64.0.51)
- Machine offline (Tailscale ping fails, port 9094 timeout)
- Cluster remembers peer ID `12D3KooWEa7paY...` at this IP
- Config has different peer_id `12D3KooWFdQri2...` (stale — container was recreated)
- **Fix**: power on machine, update peer_id in config after verifying actual ID
