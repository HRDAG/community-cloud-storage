<!--
Author: PB and Claude
Date: 2026-01-10
License: (c) HRDAG, 2025, GPL-2 or newer

---
docs/architecture-plan.md
-->

# CCS Architecture Plan: Multi-Org Pinning with Cross-Org Backup

## Executive Summary

This document describes the target architecture for Community Cloud Storage (CCS), a private IPFS cluster serving 5 organizations with automatic cross-org backup and rebalancing. It includes a phased implementation plan starting with a test topology using existing infrastructure.

---

## 0. Implementation Status

**Last updated:** 2026-01-13

### Completed
- [x] Architecture plan written and approved
- [x] Host networking refactor (removed tailscale container)
- [x] NDJSON parsing fix in cluster_api.py
- [x] CCS code updated: replication settings in compose template
- [x] CCS code updated: `--node-role` and `--node-org` CLI options
- [x] Cluster state documented (peer IDs captured)

### Current Cluster State
| Node | Cluster Peer ID | Tailnet IP | Status |
|------|-----------------|------------|--------|
| nas | `12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ` | 100.64.0.31 | Running, needs config update |
| meerkat | `12D3KooWFCXpnVGGTk3ykyMTnkSpoesCS5KFeJEQ37Nw1xFuRzGn` | 100.64.0.4 | Running, needs config update |
| chll | — | — | Not yet deployed |
| pihost | — | — | Not yet deployed |
| ipfs1 | — | — | Not yet deployed |

### In Progress
- [ ] Ansible role creation (pulled forward from Phase 3)
- [ ] Deploy updated config to nas and meerkat via ansible

### Key Decision: Ansible-Driven Deployment
During Phase 1 implementation, we decided to pull ansible integration forward. Instead of CCS generating compose files and manually deploying, **ansible is now the single source of truth** for all node configuration. See Section 4.1 for details.

---

## 1. Goals

### 1.1 Primary Goal

Enable each organization to:
1. Pin files to their **local primary** node
2. Automatically replicate to **ben** (shared ultimate backup)
3. Automatically replicate to **one other org's primary** (cross-org backup, selected by free space)

### 1.2 Design Principles

| Principle | Implementation |
|-----------|----------------|
| Decentralized | Each org controls their primary node |
| Redundant | 3 copies: local + backup + cross-org |
| Self-healing | Automatic rebalancing on node failure |
| Simple ops | Ansible deploys everything, CCS CLI for daily use |
| Graceful transitions | Test topology → production without data loss |

### 1.3 Non-Goals (for now)

- Web UI (CLI only)
- Public access (private tailnet only)
- Automated garbage collection
- `ccs rm` command (too dangerous, manual only)

---

## 2. Target Architecture (Production)

### 2.1 Network Topology

```
                         ┌───────────────┐
                         │     ben       │
                         │   (ultimate   │
                         │    backup)    │
                         │  role=backup  │
                         └───────┬───────┘
                                 │
                                 │ all orgs replicate to ben
                                 │
     ┌───────────┬───────────┬───┴───┬───────────┬───────────┐
     │           │           │       │           │           │
 ┌───▼───┐   ┌───▼───┐   ┌───▼───┐   ┌───▼───┐   ┌───▼───┐
 │  nas  │◄─►│ orgB  │◄─►│ orgC  │◄─►│ orgD  │◄─►│ orgE  │
 │ HRDAG │   │primary│   │primary│   │primary│   │primary│
 │  org= │   │  org= │   │  org= │   │  org= │   │  org= │
 │ hrdag │   │ orgB  │   │ orgC  │   │ orgD  │   │ orgE  │
 └───────┘   └───────┘   └───────┘   └───────┘   └───────┘
     ▲                                               ▲
     └──────────── cross-org backup mesh ────────────┘
         (primaries back each other up via allocator)
```

### 2.2 Node Roles

| Role | Tag | Count | Purpose |
|------|-----|-------|---------|
| primary | `role=primary` | 5 | Each org's main storage node |
| backup | `role=backup` | 1 | Shared ultimate backup (ben) |
| overflow | `role=overflow` | 0+ | Emergency overflow (not in normal rotation) |

### 2.3 Replication Strategy

When Org A adds a file:

| Replica | Node | Selection Method |
|---------|------|------------------|
| 1 | Org A primary | Explicit allocation (local) |
| 2 | ben | Explicit allocation (backup) |
| 3 | Another org's primary | Allocator: role=primary, org≠A, by freespace |

**Result:** Every file exists on 3 nodes across at least 2 organizations plus the shared backup.

### 2.4 IPFS Cluster Configuration

```json
{
  "cluster": {
    "replication_factor_min": 2,
    "replication_factor_max": 3,
    "disable_repinning": false
  },
  "allocator": {
    "balanced": {
      "allocate_by": ["tag:role", "tag:org", "freespace"]
    }
  }
}
```

**Replication factor rationale:**
- `min: 2` — If one node fails, we still have 2 copies. Dropping below 2 triggers rebalancing.
- `max: 3` — local + backup + one cross-org. No need for more.

### 2.5 Per-Node Tags

Each node's `service.json` includes:

```json
{
  "informer": {
    "tags": {
      "tags": {
        "role": "primary",
        "org": "hrdag"
      }
    }
  }
}
```

### 2.6 CCS Client Configuration

`~/.ccs/config.yml` on admin workstations (populated by ansible):

```yaml
# Shared backup node (all orgs use this)
backup_node: ben

# Per-org profiles
profiles:
  hrdag:
    primary: nas
  orgB:
    primary: orgB-node
  orgC:
    primary: orgC-node
  orgD:
    primary: orgD-node
  orgE:
    primary: orgE-node

# All cluster nodes with peer IDs
# NOTE: This section is populated/updated by ansible during deploys
nodes:
  nas:
    host: nas
    peer_id: 12D3KooW...
  ben:
    host: ben
    peer_id: 12D3KooW...
  orgB-node:
    host: orgB-node
    peer_id: 12D3KooW...
  # ... etc
```

**Peer ID workflow:**
1. Ansible deploys CCS to node
2. Ansible queries node for peer ID: `curl http://localhost:9094/id | jq -r '.id'`
3. Ansible stores peer ID in inventory (`host_vars/<node>.yml`)
4. Ansible runs `ccs-sync-config.yml` to update admin workstation configs

### 2.7 Pin Workflow

```bash
$ ccs add --profile hrdag /path/to/archive

# Internal steps:
# 1. ipfs add -r on nas (HRDAG primary) → root CID
# 2. Look up peer IDs: nas, ben
# 3. POST /pins/{CID}?allocations=nas_peer,ben_peer
#    with replication-min=2, replication-max=3
# 4. Allocator picks 3rd replica from other primaries by freespace
# 5. Write to manifest (CID, path, timestamp, allocations)
```

---

## 3. Test Architecture (Current Phase)

### 3.1 Test Topology

Until production orgs are onboarded (~2 months), we use existing infrastructure:

```
                         ┌───────────────┐
                         │     chll      │
                         │  (pretend     │
                         │    ben)       │
                         │ role=backup   │
                         └───────┬───────┘
                                 │
     ┌───────────┬───────────┬───┴───────────────┐
     │           │           │                   │
 ┌───▼───┐   ┌───▼───┐   ┌───▼───┐         ┌─────▼─────┐
 │  nas  │   │meerkat│   │pihost │         │   ipfs1   │
 │ HRDAG │   │test-  │   │test-  │         │  test-    │
 │  org= │   │ orgB  │   │ orgC  │         │  orgD     │
 │ hrdag │   │       │   │       │         │           │
 └───────┘   └───────┘   └───────┘         └───────────┘
   real        ▲            ▲                   ▲
   primary     └────────────┴───────────────────┘
                  pretend cross-org primaries
```

### 3.2 Test Node Assignments

| Node | Role | Org Tag | Notes |
|------|------|---------|-------|
| nas | primary | hrdag | Real HRDAG primary (stays) |
| chll | backup | shared | Pretending to be ben |
| meerkat | primary | test-orgB | Pretending to be Org B |
| pihost | primary | test-orgC | Pretending to be Org C |
| ipfs1 | primary | test-orgD | Pretending to be Org D |

### 3.3 Test CCS Configuration

`~/.ccs/config.yml` during testing (populated by ansible):

```yaml
backup_node: chll  # Will become 'ben' later

profiles:
  hrdag:
    primary: nas

# Populated by ansible from host_vars after each deploy
nodes:
  nas:
    host: nas
    peer_id: 12D3KooW...  # captured by ansible
  chll:
    host: chll
    peer_id: 12D3KooW...  # captured by ansible
  meerkat:
    host: meerkat
    peer_id: 12D3KooW...  # captured by ansible
  pihost:
    host: pihost
    peer_id: 12D3KooW...  # captured by ansible
  ipfs1:
    host: ipfs1
    peer_id: 12D3KooW...  # captured by ansible
```

### 3.4 Transition Plan

**Phase: chll → ben (~1 month)**

1. Deploy ben with `role=backup`, `org=shared`
2. Update `~/.ccs/config.yml`: `backup_node: ben`
3. New pins go to ben instead of chll
4. Options for existing pins on chll:
   - Keep chll as secondary backup (belt + suspenders)
   - Or: remove chll from cluster, rebalancer migrates pins

**Phase: test nodes → real orgs (~2 months)**

For each real org coming online:

1. Deploy orgX-node with `role=primary`, `org=orgX`
2. Retag corresponding test node: `role=overflow`
3. Optionally remove test node from cluster
4. Rebalancer automatically migrates pins to real org node

**Data safety during transitions:**

- `replication_factor_min: 2` ensures removing one node triggers re-allocation
- Rebalancer runs automatically when `disable_repinning: false`
- Never remove a node until its pins are replicated elsewhere

---

## 4. Implementation Phases

### Phase 1: Cluster Configuration (This Sprint)

**Goal:** Configure existing cluster (nas, meerkat) properly, add remaining test nodes.

**Key change:** Ansible integration pulled forward. All deployment is now ansible-driven.

**Tasks:**

1.1. ✅ **Document current cluster state** (DONE)
   - Captured peer IDs from nas and meerkat
   - Verified current settings (no replication factors, repinning disabled by default)

1.2. ✅ **Update CCS code with new settings** (DONE)
   - Added `CLUSTER_REPLICATIONFACTORMIN: "2"` to compose template
   - Added `CLUSTER_REPLICATIONFACTORMAX: "3"` to compose template
   - Added `CLUSTER_DISABLEREPINNING: "false"` to compose template
   - Added `--node-role` and `--node-org` CLI options
   - Added `CLUSTER_INFORMER_TAGS_TAGS` env var for tags

1.3. 🔄 **Create ansible role for CCS deployment** (IN PROGRESS)
   - Ansible templates compose.yml (not CCS python code)
   - All node-specific config in ansible inventory
   - Secrets in ansible-vault
   - See `../hrdag-ansible/docs/ccs-role-requirements.md`

1.4. **Deploy to existing nodes via ansible**
   - nas: `role=primary`, `org=hrdag`
   - meerkat: `role=primary`, `org=test-orgB`
   - Verify replication settings applied
   - Capture peer IDs to inventory

1.5. **Add remaining test nodes via ansible**
   - chll: `role=backup`, `org=shared`
   - pihost: `role=primary`, `org=test-orgC`
   - ipfs1: `role=primary`, `org=test-orgD`

**Deliverables:**
- Ansible role: `ccs` in hrdag-ansible
- 5-node test cluster running
- All nodes tagged correctly
- Replication and rebalancing enabled
- Peer IDs in ansible inventory

### 4.1 Ansible-Driven Deployment Model

**Rationale:** During Phase 1, we discovered that manually patching compose files doesn't scale. Each node has different volume paths, and secrets were scattered. We pulled ansible integration forward to establish a single source of truth.

**Before (CCS-generated compose):**
```
ccs create/clone → compose.yml → scp to node → docker compose up
```
- CCS python code generates compose.yml with baked-in values
- Volume paths hardcoded per-node
- Secrets scattered in compose files on each node
- Manual deployment

**After (Ansible-driven compose):**
```
ansible-playbook ccs-deploy.yml -l nas → compose.yml templated → deployed
```
- Ansible inventory holds all node config (host_vars)
- Ansible templates compose.yml using jinja2
- Secrets in ansible-vault (single location)
- Reproducible, automated deployment

**Responsibility split:**

| Task | Owner |
|------|-------|
| IPFS Cluster API library | CCS python (this repo) |
| CLI for daily ops (add, ls, status) | CCS python (this repo) |
| compose.yml template | hrdag-ansible |
| Docker installation | hrdag-ansible |
| Secrets management (vault) | hrdag-ansible |
| Peer ID capture | hrdag-ansible |
| Node deployment | hrdag-ansible |

**CCS python code does NOT generate compose files anymore** — that's ansible's job.

**Deprecated CCS commands:** `ccs create` and `ccs clone` still exist but are vestigial. Use ansible for all deployments.

**Ansible inventory structure:**
```
hrdag-ansible/
  inventory/
    group_vars/
      ccs_nodes.yml           # Cluster-wide: secrets, replication settings
    host_vars/
      nas.yml                 # Node-specific: volume_path, role, org, peer_id
      meerkat.yml
      chll.yml
      pihost.yml
      ipfs1.yml
  roles/
    ccs/
      templates/compose.yml.j2
      tasks/main.yml
```

**Example host_vars/nas.yml:**
```yaml
ccs_cluster_peername: nas-ccs
ccs_volume_path: /mnt/hrdag-nas/ccs
ccs_node_role: primary
ccs_node_org: hrdag
ccs_peer_id: 12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ  # captured after deploy
```

**Example group_vars/ccs_nodes.yml (vaulted):**
```yaml
ccs_cluster_secret: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
ccs_ipfs_swarm_key: !vault |
  ...
ccs_basic_auth_password: !vault |
  ...
```

### Phase 2: CCS CLI Updates (Next Sprint)

**Goal:** Update `ccs add` to use explicit allocations with the new architecture.

**Tasks:**

2.1. **Refactor CCS as library-first architecture**
   - CCS must be importable as a Python library, not just a CLI
   - All commands (`add`, `ls`, `status`, `peers`) are functions returning serializable objects
   - Objects support `to_json()` / `from_json()` round-trip without data loss
   - CLI is a thin wrapper: calls library function, writes JSON to stdout or `--outputjson=<path>`

2.2. **Update config schema**
   - Add `backup_node` field
   - Add `profiles` section with org → primary mapping
   - Add `nodes` section with peer IDs (populated by ansible)

2.3. **Update `ccs add` command/function**
   - Returns: `AddResult` object with CID, path, file metadata, IPFS metadata, allocations
   - CLI: writes JSON to stdout or `--outputjson=<path>`
   - Load profile (--profile flag or default)
   - Determine local primary from profile
   - Look up backup node peer ID
   - Build explicit allocations: [local_peer_id, backup_peer_id]
   - Add `--replication-min` and `--replication-max` to API call

2.4. **Add peer ID discovery**
   - `ccs peers` command/function to list cluster nodes
   - Peer IDs primarily come from config (populated by ansible)
   - `--fetch` flag queries cluster for fresh data

2.5. **Update `ccs ls` and `ccs status`**
   - Return structured objects with replication health
   - Show which nodes have each pin
   - Show replication status (✓ healthy, ⚠ degraded, ✗ critical)
   - CLI: `--outputjson=<path>` option

2.6. **Add `ccs config` command**
   - Display current config
   - Validate config (all peer IDs resolvable, etc.)
   - `--outputjson=<path>` option

**Deliverables:**
- CCS importable as Python library with typed return objects
- All CLI commands support `--outputjson=<path>`
- `ccs add --profile <org>` works with explicit allocations
- `ccs peers` shows all cluster nodes
- `ccs ls` shows replication health

### Phase 3: Ansible Integration (Following Sprint)

**Status:** PULLED FORWARD into Phase 1. Core ansible role is now part of Phase 1.

**Remaining Phase 3 work:** Polish and documentation after initial deployment works.

**Tasks:**

3.1. ~~Write requirements document~~ → Moved to Phase 1.3

3.2. **Add operational playbooks** (after basic deploy works)
   - `ccs-configure.yml` — Update config on existing nodes without full redeploy
   - `ccs-retag.yml` — Change node tags (for transitions)
   - `ccs-sync-config.yml` — Push peer IDs to admin workstation `~/.ccs/config.yml`

3.3. **Document ansible workflows**
   - Adding a new org
   - Transitioning test node to real org
   - Removing a node safely
   - Rotating secrets

**Deliverables:**
- Operational playbooks beyond basic deploy
- Workflow documentation in hrdag-ansible

### Phase 4: Production Onboarding (Ongoing)

**Goal:** Onboard real organizations as they come online.

**Tasks per org:**

4.1. **Deploy org's primary node**
   - Run ansible playbook
   - Verify joins cluster
   - Tag with `role=primary`, `org=<orgname>`

4.2. **Update CCS config**
   - Add org to `profiles` section
   - Add node to `nodes` section with peer ID

4.3. **Retire corresponding test node**
   - Retag to `role=overflow`
   - Verify pins replicated to real org node
   - Optionally remove from cluster

4.4. **Test org's workflow**
   - `ccs add --profile <org> /test/file`
   - Verify pins to: org primary + backup + cross-org

**Deliverables per org:**
- Org's primary node running
- Org can add files with proper replication
- Test node retired

### Phase 5: Ben Deployment (~1 month)

**Goal:** Replace chll with ben as the ultimate backup.

**Tasks:**

5.1. **Deploy ben**
   - Run ansible playbook
   - Tag: `role=backup`, `org=shared`
   - Verify joins cluster

5.2. **Update CCS config**
   - Change `backup_node: chll` → `backup_node: ben`
   - Add ben to `nodes` section

5.3. **Migrate from chll**
   - Option A: Keep both (chll becomes secondary backup)
   - Option B: Retag chll, let rebalancer migrate pins
   - Option C: Manual migration with verification

5.4. **Verify backup integrity**
   - All pins replicated to ben
   - chll can be safely retired

**Deliverables:**
- ben running as backup
- All pins replicated to ben
- chll retired or repurposed

---

## 5. Rollback Plan

If issues arise, we can rollback at any phase:

| Phase | Rollback |
|-------|----------|
| Phase 1 | Revert cluster config, git tag `v0.4.0-tailscale` has last known good |
| Phase 2 | Revert CLI changes, old `ccs add` still works |
| Phase 3 | Ansible changes are additive, manual deploy still works |
| Phase 4 | Don't remove test nodes until verified |
| Phase 5 | Keep chll until ben is verified |

---

## 6. Monitoring & Operations

### 6.1 Health Checks

All CCS commands support `--outputjson=<path>` for machine-readable output:

```bash
# Check cluster status (human-readable)
ccs peers                              # List all peers, online status
ccs ls                                 # List pins with replication status

# Machine-readable for monitoring scripts
ccs peers --outputjson=/tmp/peers.json
ccs ls --outputjson=/tmp/pins.json
ccs status <CID> --outputjson=/tmp/status.json

# Per-node checks
ssh node "docker compose ps"           # Container health
ssh node "ipfs repo stat"              # Storage usage
```

### 6.2 Alerting (Future)

- Node offline > 1 hour
- Replication count < min for any CID
- Storage > 80% on any node

### 6.3 Backup Verification (Future)

Periodic job to verify:
- All CIDs exist on ben
- All CIDs have >= 2 replicas
- No orphaned pins (in cluster but not in manifest)

---

## 7. Design Decisions (Resolved)

1. **Manifest storage:** ✓ RESOLVED
   - CCS outputs JSON via `--outputjson=<path>` or returns objects when imported as library
   - Separate process (outside CCS scope) handles database storage
   - Interface: JSON files or Python objects with `to_json()`/`from_json()` round-trip

2. **Peer ID management:** ✓ RESOLVED — Hybrid approach
   - Ansible captures peer ID during deploy (authoritative source)
   - Ansible writes peer ID to `~/.ccs/config.yml` on admin workstations
   - CCS reads from local config (no network calls needed)
   - Single update path: ansible deploy → config updated

3. **chll capacity:** ✓ RESOLVED
   - chll has >50TB storage — sufficient for temporary backup role

4. **Cross-org privacy:** ✓ RESOLVED
   - IPFS Cluster shares pin metadata by default (CIDs, names visible to all nodes)
   - Privacy handled at application layer: files encrypted before add, named by hash
   - No sensitive metadata in pin names

5. **Rebalancer timing:** ✓ RESOLVED
   - Default: 24 hours before declaring node dead
   - Must be configurable via `CLUSTER_MONITORPINGINTERVAL` and related settings
   - Document tuning options in deployment guide 

---

## 8. Success Criteria

### Phase 1 Complete When:
- [ ] 5 test nodes in cluster (nas, chll, meerkat, pihost, ipfs1)
- [ ] All nodes tagged correctly
- [ ] `disable_repinning: false` on all nodes
- [ ] Replication factors set correctly
- [ ] Peer IDs captured and documented

### Phase 2 Complete When:
- [ ] `ccs add --profile hrdag /test` creates pin on nas + chll + one test node
- [ ] `ccs ls` shows all pins with replication status
- [ ] `ccs peers` shows all cluster nodes

### Full Production When:
- [ ] 5 real org primaries running
- [ ] ben running as backup
- [ ] Each org can add files with proper 3-way replication
- [ ] Test nodes retired
- [ ] Ansible manages all deployments

---

## Appendix A: Environment Variables for Cluster Config

IPFS Cluster supports environment variable overrides:

```yaml
# In compose.yml (or ansible template)
environment:
  CLUSTER_REPLICATIONFACTORMIN: "2"
  CLUSTER_REPLICATIONFACTORMAX: "3"
  CLUSTER_DISABLEREPINNING: "false"
  CLUSTER_INFORMER_TAGS_TAGS: '{"role": "primary", "org": "hrdag"}'
```

Tags are set via `CLUSTER_INFORMER_TAGS_TAGS` as a JSON string. Confirmed working in CCS code.

## Appendix B: Useful Commands

```bash
# Get peer ID from running cluster
curl -s http://localhost:9094/id | jq -r '.id'

# List all peers in cluster
curl -s http://localhost:9094/peers | jq -r '.[].id'

# Check pin status
curl -s http://localhost:9094/pins | jq '.cid, .peer_map'

# Add with explicit allocations
curl -X POST "http://localhost:9094/pins/<CID>?allocations=peer1,peer2"
```

## Appendix C: Related Documents

- `docs/docker-setup.md` — Current deployment guide
- `docs/ipfs-cluster-rebalancing.md` — Research on cluster behavior
- `../hrdag-ansible/docs/ccs-role-requirements.md` — Ansible role requirements (Phase 3 deliverable)
