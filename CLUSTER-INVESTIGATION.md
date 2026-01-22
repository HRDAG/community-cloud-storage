<!--
Author: PB and Claude
Date: 2026-01-22
License: (c) HRDAG, 2026, GPL-2 or newer

---
community-cloud-storage/CLUSTER-INVESTIGATION.md
-->

# IPFS Cluster Investigation Spec

**For:** Claude instance with SSH access to ipfs1, meerkat, pihost, chll

**Context:** NTX archive system needs IPFS cluster for uploads. Cluster API returns "not enough peers" - only chll visible, other nodes not peering despite containers running.

---

## Known State

| Node | Role | Tailscale IP | Status |
|------|------|--------------|--------|
| chll | backup | 100.64.0.32 | Online, only sees itself |
| nas | hrdag primary | 100.64.0.31 | Unknown (no SSH access) |
| meerkat | test-orgB primary | 100.64.0.4 | Container running, can't reach chll:9096 |
| pihost | test-orgC primary | 100.64.0.2 | Unknown |
| ipfs1 | test-orgD primary | 100.64.0.51 | Unknown |

**Cluster requires:** Minimum 2 peers for replication
**Currently available:** 1 peer (chll)

**Error from cluster API:**
```
"not enough peers to allocate CID. Needed at least: 2.
 Wanted at most: 3. Available candidates: 1."
```

---

## Investigation Tasks

### 1. Network Connectivity (all nodes)

```bash
# On each node (meerkat, pihost, ipfs1, chll):
echo "=== $(hostname) ==="

# Tailscale status
tailscale status | head -10

# Can reach chll?
ping -c2 100.64.0.32
nc -zv 100.64.0.32 9096 2>&1   # cluster peer port
nc -zv 100.64.0.32 9094 2>&1   # cluster API port

# Can reach each other?
nc -zv 100.64.0.4 9096 2>&1    # meerkat
nc -zv 100.64.0.2 9096 2>&1    # pihost
nc -zv 100.64.0.51 9096 2>&1   # ipfs1
```

### 2. Cluster Daemon Status (all nodes)

```bash
# Docker-based:
sudo docker ps | grep -E "cluster|ipfs"
sudo docker logs ccs-cluster --tail 100 2>&1 | grep -iE "peer|error|connect|bootstrap"

# Or systemd-based:
systemctl status ipfs-cluster
journalctl -u ipfs-cluster --since "1 hour ago" | grep -iE "peer|error|connect"
```

### 3. Cluster Identity & Config (all nodes)

```bash
# Get cluster peer ID
sudo docker exec ccs-cluster ipfs-cluster-ctl id 2>&1

# Check what peers it sees
sudo docker exec ccs-cluster ipfs-cluster-ctl peers ls 2>&1

# Check bootstrap config
sudo docker exec ccs-cluster cat /data/ipfs-cluster/service.json | grep -A5 "bootstrap"
```

### 4. From chll specifically

```bash
# What peers does chll see?
sudo docker exec ccs-cluster ipfs-cluster-ctl peers ls

# Cluster health
sudo docker exec ccs-cluster ipfs-cluster-ctl health graph
```

---

## Report Back

Please provide:

1. **Connectivity matrix:** Which nodes can reach which on ports 9094/9096
2. **Tailscale status:** Are all nodes on same Tailnet?
3. **Cluster logs:** Any error patterns (auth failures, connection refused, timeout)
4. **Peer visibility:** Output of `ipfs-cluster-ctl peers ls` from each node
5. **Bootstrap config:** Are nodes configured to find each other?

---

## Likely Fixes (depending on findings)

| Symptom | Fix |
|---------|-----|
| Port 9096 unreachable | Firewall/Tailscale ACL issue |
| "cluster secret mismatch" in logs | Regenerate/sync cluster secret |
| Empty bootstrap list | Add bootstrap peers to config |
| Peers visible but not pinning | Check replication config |
| Container running but not peered | Restart with correct bootstrap |

---

## CCS Code Issue Found

Separate from infra: When cluster returns error via streaming response, CCS gets empty body instead of error. With `stream-channels=false` query param, error is visible. This should be fixed in CCS to handle streaming errors properly.

Test command that reveals the error:
```bash
cd /home/pball/projects/community-cloud-storage
uv run python3 -c "
from pathlib import Path
from community_cloud_storage.config import load_config
from community_cloud_storage.cluster_api import ClusterClient

config = load_config(Path('~/.ccs/config.yml').expanduser())
node = config.get_node('chll')
auth = config.auth.to_tuple() if config.auth else None
client = ClusterClient(host=node.host, port=9094, basic_auth=auth)

path = Path('/tmp/test.txt')
path.write_text('test')
query = 'name=test&local=true&stream-channels=false'

with open(path, 'rb') as f:
    files = {'file': (path.name, f)}
    response = client.session.post(f'{client.base_url}/add?{query}', files=files)

print(f'Status: {response.status_code}')
print(f'Body: {response.text}')
"
```
