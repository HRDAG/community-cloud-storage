<!--
Author: PB and Claude
Date: 2026-01-13
License: (c) HRDAG, 2026, GPL-2 or newer

---
community-cloud-storage/docs/ansible-task-report-20260113.md
-->

# CCS Ansible Role Implementation Report

**Date:** 2026-01-13
**Status:** Deployed to nas and meerkat, pending full verification

---

## Summary

Created and deployed an Ansible role (`roles/ccs`) in `hrdag-ansible` to manage CCS (Community Cloud Storage) nodes. The role deploys IPFS + IPFS Cluster via Docker Compose with configuration driven entirely from Ansible inventory.

---

## Files Created

### Role Structure

```
hrdag-ansible/roles/ccs/
├── defaults/main.yml      # Space thresholds, variable documentation
├── handlers/main.yml      # restart ccs handler
├── tasks/main.yml         # 196 lines: prereqs, docker, deploy, health check
└── templates/
    └── compose.yml.j2     # Docker compose with IPFS + Cluster
```

### Inventory

```
inventory/
├── group_vars/
│   └── ccs_nodes.yml      # Vaulted secrets (cluster_secret, swarm_key, auth)
└── host_vars/
    ├── meerkat.yml        # New file with CCS config
    └── nas.yml            # Added CCS config to existing file
```

### Other

- `playbooks/ccs-deploy.yml` - Deployment playbook
- `docs/ccs-role-requirements.md` - Requirements document
- `ansible.cfg` - Added `vault_password_file = ~/creds/vault_pass`

---

## Configuration Details

### Cluster-Wide Settings (group_vars/ccs_nodes.yml)

Encrypted with ansible-vault. Contains:

| Variable | Value |
|----------|-------|
| `ccs_cluster_secret` | (vaulted) |
| `ccs_ipfs_swarm_key` | (vaulted) |
| `ccs_basic_auth_user` | admin |
| `ccs_basic_auth_password` | (vaulted) |
| `ccs_replication_factor_min` | 2 |
| `ccs_replication_factor_max` | 3 |
| `ccs_disable_repinning` | false |
| `ccs_monitor_ping_interval` | 2s |
| `ccs_ipfs_image` | ipfs/kubo:v0.36.0 |
| `ccs_cluster_image` | ipfs/ipfs-cluster:latest |

### Per-Node Settings

**nas:**
```yaml
ccs_cluster_peername: nas-ccs
ccs_volume_path: /mnt/hrdag-nas/ccs
ccs_node_role: primary
ccs_node_org: hrdag
ccs_peer_id: 12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ
ccs_ipfs_peer_id: 12D3KooWEgKUafShAghxZ64eXhZvCvU2MqzKtiLoGD7BBo1bPJnp
```

**meerkat:**
```yaml
ccs_cluster_peername: meerkat-ccs
ccs_volume_path: /mnt/sda1/ccs
ccs_node_role: primary
ccs_node_org: test-orgB
ccs_peer_id: 12D3KooWFCXpnVGGTk3ykyMTnkSpoesCS5KFeJEQ37Nw1xFuRzGn
ccs_ipfs_peer_id: 12D3KooWM4YjhLG6XfTX6oN3BpaS41U5AiPxCGMLgDgDhgeVviF8
ccs_bootstrap_host: nas
```

---

## Deployment Results

### nas

```
PLAY RECAP *****************************************************************
nas    : ok=12   changed=2    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0
```

- compose.yml updated with replication settings and tags
- Containers restarted
- Peer ID verified: `12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ`

### meerkat

```
PLAY RECAP *****************************************************************
meerkat: ok=12   changed=2    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0
```

- compose.yml updated with replication settings and tags
- Bootstrap peer address corrected to nas's tailscale IP
- Containers restarted
- Peer ID verified: `12D3KooWFCXpnVGGTk3ykyMTnkSpoesCS5KFeJEQ37Nw1xFuRzGn`

### Cluster Status

Both nodes see each other:

```json
{"peername": "nas-ccs", "id": "12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ"}
{"peername": "meerkat-ccs", "id": "12D3KooWFCXpnVGGTk3ykyMTnkSpoesCS5KFeJEQ37Nw1xFuRzGn"}
```

---

## Verification Test Sequence

Run these tests to verify full functionality:

### 1. Cluster Connectivity

```bash
# Check peers from nas
ssh nas "curl -s -u admin:PASSWORD http://localhost:9094/peers" | jq -s '.[].peername'
# Expected: "nas-ccs", "meerkat-ccs"

# Check peers from meerkat
ssh meerkat "curl -s -u admin:PASSWORD http://localhost:9094/peers" | jq -s '.[].peername'
# Expected: "nas-ccs", "meerkat-ccs"
```

### 2. Add Test File and Verify Replication

```bash
# Add a test file via IPFS on nas
CID=$(ssh nas "echo 'CCS ansible test $(date)' | docker exec -i ccs-ipfs ipfs add -q")
echo "Added CID: $CID"

# Pin to cluster (triggers replication)
ssh nas "curl -s -X POST -u admin:PASSWORD 'http://localhost:9094/pins/$CID'"

# Wait for replication (few seconds)
sleep 5

# Check pin status - should show PINNED on both nodes
ssh nas "curl -s -u admin:PASSWORD 'http://localhost:9094/pins/$CID'" | jq '.peer_map | to_entries[] | {peer: .key, status: .value.status}'
```

### 3. Retrieve from Other Node

```bash
# Retrieve content from meerkat (proves replication worked)
ssh meerkat "docker exec ccs-ipfs ipfs cat $CID"
# Expected: "CCS ansible test <timestamp>"
```

### 4. Verify Replication Settings

```bash
# Check that replication factors are applied
ssh nas "curl -s -u admin:PASSWORD http://localhost:9094/pins" | jq -s '.[0] | {replication_factor_min, replication_factor_max}'
# Expected: {"replication_factor_min": 2, "replication_factor_max": 3}
```

### 5. Verify Tags Configuration

```bash
# Tags are configured in compose.yml but may not be visible via API
ssh nas "sudo grep TAGS /mnt/hrdag-nas/ccs/compose.yml"
# Expected: CLUSTER_INFORMER_TAGS_TAGS: '{"role": "primary", "org": "hrdag"}'

ssh meerkat "sudo grep TAGS /mnt/sda1/ccs/compose.yml"
# Expected: CLUSTER_INFORMER_TAGS_TAGS: '{"role": "primary", "org": "test-orgB"}'
```

---

## Usage

### Deploy to a Node

```bash
cd ~/projects/hrdag/hrdag-ansible

# Dry run
ansible-playbook playbooks/ccs-deploy.yml -l <hostname> --check --diff

# Apply
ansible-playbook playbooks/ccs-deploy.yml -l <hostname>

# Config-only update (no Docker install check)
ansible-playbook playbooks/ccs-deploy.yml -l <hostname> --tags configure
```

### Add a New CCS Node

1. Add host to `inventory/hosts.yml` under `ccs_nodes` group
2. Create `inventory/host_vars/<hostname>.yml` with:
   ```yaml
   tailscale_ip: 100.64.0.XX
   ccs_cluster_peername: <hostname>-ccs
   ccs_volume_path: /path/to/ccs/data
   ccs_node_role: primary  # or backup
   ccs_node_org: <org-name>
   ccs_bootstrap_host: nas  # existing node to join
   ```
3. Create the volume path on the host
4. Run: `ansible-playbook playbooks/ccs-deploy.yml -l <hostname>`
5. Add `ccs_peer_id` and `ccs_ipfs_peer_id` from playbook output to host_vars

---

## Design Decisions

1. **Ownership:** Directories are created without forcing ownership. Docker/containers manage their own permissions (typically uid 1000).

2. **Space checks:** Pre-flight verification with configurable thresholds (fail <10GB, warn <50GB). Skipped in `--check` mode.

3. **Docker installation:** Only installs if Docker not present. Avoids conflicts with Docker CE vs docker.io packages.

4. **Peer ID capture:** Displayed in playbook output for manual addition to inventory. One-time operation per node.

5. **Tags on tasks:** Use `--tags configure` for config-only updates without Docker installation checks.

6. **Incoming mount:** `{{ ccs_volume_path }}/incoming:/incoming` included for file staging before IPFS ingestion.

---

## Git Commit

```
c6c1128 Add CCS role for IPFS cluster deployment

11 files changed, 734 insertions(+)
```

---

## Next Steps

1. Run verification test sequence above
2. Add remaining nodes (chll, pihost, ipfs1) as needed
3. Test tag-based allocation with multi-org pins
4. Consider automating peer ID capture (callback plugin or separate playbook)
