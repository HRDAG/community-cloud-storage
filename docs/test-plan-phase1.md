<!--
Author: PB and Claude
Date: 2026-01-13
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/test-plan-phase1.md
-->

# CCS Phase 1 Test Plan

## Verification Test Results (2026-01-13)

All tests PASSED on nas + meerkat cluster.

| Test | Status | Notes |
|------|--------|-------|
| 1. Cluster connectivity | ✅ PASS | Both nodes see each other |
| 2. Add file, verify replication | ✅ PASS | CID pinned on both nodes |
| 3. Retrieve from other node | ✅ PASS | Content matches original |
| 4. Replication settings | ✅ PASS | min=2, max=3, repinning=false |
| 5. Tags configured | ✅ PASS | role + org tags on both nodes |

Test CID: `QmambnazmvsNECwxtiLLmzx5ThRYgWNPXvzcFfacXB2sSg`

---

## Adding Remaining Test Nodes

### Node Status

| Node | Tailnet IP | Reachable | Docker | CCS Volume Path | Role | Org |
|------|------------|-----------|--------|-----------------|------|-----|
| nas | 100.64.0.31 | ✅ | ✅ | /mnt/hrdag-nas/ccs | primary | hrdag |
| meerkat | 100.64.0.4 | ✅ | ✅ | /mnt/sda1/ccs | primary | test-orgB |
| chll | 100.64.0.32 | ❌ offline | ? | TBD | backup | shared |
| pihost | 100.64.0.2 | ✅ | needs install | TBD | primary | test-orgC |
| ipfs1 | 100.64.0.51 | ✅ | needs install | TBD | primary | test-orgD |

### Prerequisites for Each Node

Before running ansible `ccs-deploy.yml`:

1. **Determine volume path** — Where will CCS store data?
   - Check available disk space: `df -h`
   - Create directory: `sudo mkdir -p /path/to/ccs`

2. **Ensure node is in ansible inventory**
   - Add to `inventory/hosts.yml` under `ccs_nodes` group
   - Create `inventory/host_vars/<hostname>.yml`

### Ansible Deployment Steps

For each node (example: pihost):

```bash
cd ~/projects/hrdag/hrdag-ansible

# 1. Create host_vars file
cat > inventory/host_vars/pihost.yml << 'EOF'
tailscale_ip: 100.64.0.2
ccs_cluster_peername: pihost-ccs
ccs_volume_path: /path/to/ccs        # UPDATE THIS
ccs_node_role: primary
ccs_node_org: test-orgC
ccs_bootstrap_host: nas
EOF

# 2. Dry run
ansible-playbook playbooks/ccs-deploy.yml -l pihost --check --diff

# 3. Deploy
ansible-playbook playbooks/ccs-deploy.yml -l pihost

# 4. Capture peer ID from output and add to host_vars
# ccs_peer_id: 12D3KooW...
# ccs_ipfs_peer_id: 12D3KooW...
```

### Post-Deployment Verification

After adding each node:

```bash
# 1. Check node appears in cluster
ccs ls --cluster-peername nas --basic-auth-file ~/.ccs/config.yml | jq '.peer_map | keys'

# 2. Verify connectivity from new node
curl -s -u admin:PASSWORD http://<new-node>:9094/peers | jq -s '.[].peername'

# 3. Verify tags on new node
ssh <new-node> "sudo grep TAGS /path/to/ccs/compose.yml"
```

---

## Tag-Based Allocation Test Plan

### Goal

Verify that when adding files, the allocator respects tags:
1. Pin to local primary (explicit allocation)
2. Pin to backup node (explicit allocation)
3. Third replica selected by allocator based on role=primary, different org, freespace

### Current Limitation

With only 2 nodes (nas, meerkat), we can't fully test the allocator choosing a third node. Need at least 3 nodes.

### Test After 3+ Nodes Available

Once chll (backup) is online:

```bash
# Add file from nas with explicit allocations to nas + chll
# Third replica should go to meerkat (only other primary)

# 1. Add test file
echo "Tag allocation test $(date)" > /tmp/tag-test.txt
ccs add --cluster-peername nas --basic-auth-file ~/.ccs/config.yml /tmp/tag-test.txt

# 2. Check allocations
ccs status <CID> --cluster-peername nas --basic-auth-file ~/.ccs/config.yml | jq '{
  allocations: .allocations,
  peer_map: .peer_map | to_entries | map({peer: .value.peername, status: .value.status})
}'
```

### Expected Behavior (5-node cluster)

When HRDAG adds a file:
- Replica 1: nas (local primary, explicit)
- Replica 2: chll/ben (backup, explicit)
- Replica 3: one of {meerkat, pihost, ipfs1} selected by freespace

### Test Matrix

| Add From | Explicit Allocs | Expected 3rd Replica |
|----------|-----------------|----------------------|
| nas (hrdag) | nas, chll | meerkat OR pihost OR ipfs1 |
| meerkat (test-orgB) | meerkat, chll | nas OR pihost OR ipfs1 |
| pihost (test-orgC) | pihost, chll | nas OR meerkat OR ipfs1 |

---

## Rebalancing Test (Future)

Once cluster is stable with 3+ nodes:

1. Add files with replication
2. Stop one node
3. Wait for rebalancer (up to 24h or configured interval)
4. Verify pins moved to remaining nodes
5. Restart stopped node
6. Verify it syncs back

---

## Clean Up Test Data

```bash
# Remove test CID when done
ccs rm QmambnazmvsNECwxtiLLmzx5ThRYgWNPXvzcFfacXB2sSg --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
```
