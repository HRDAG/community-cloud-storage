<!--
Author: PB and Claude
Date: 2025-01-06
License: (c) HRDAG, 2025, GPL-2 or newer

---
~/docs/ccs-status-2025-01-06.md
-->

# CCS Project Status - 2025-01-06

## Current State

**Cluster nodes running:**
- nas-ccs (100.64.0.5) - bootstrap node
- meerkat-ccs (100.64.0.6) - second node

Both nodes are seeing each other and cluster is operational.

## Completed Today

### 1. HTTP API Refactor (committed)

Eliminated dependency on `ipfs-cluster-ctl` and `ipfs` binaries. CCS now talks directly to cluster via HTTP.

**Commits (not yet pushed):**
```
c64b605 Refactor to use HTTP API instead of ipfs-cluster-ctl binary
4ea5153 Add config file auth and CID manifest support
fd289ae Add --ts-authkey-file, --basic-auth, and peer ID options to clone command
```

**New files:**
- `src/community_cloud_storage/cluster_api.py` - ClusterClient and IPFSClient classes

**Key changes:**
- `ccs add/rm/ls/status` use HTTP to port 9094 (cluster API)
- `ccs get` uses HTTP to port 5001 (IPFS API)
- `--basic-auth-file` reads credentials from `~/.ccs/config.yml`
- `--cid-manifest` writes JSON manifest of added CIDs
- Tests updated to mock HTTP clients

### 2. Port 5001 Security Hardening (deployed)

IPFS API was exposed to entire tailnet. Now locked to localhost only.

**Fixed on both nodes:**
```bash
docker compose exec ipfs ipfs config Addresses.API /ip4/127.0.0.1/tcp/5001
docker compose restart ipfs
```

**Verified:** `curl -X POST http://nas-ccs:5001/api/v0/id` now fails with "connection refused"

**Note for Ansible:** meerkat requires `sudo`, nas does not (docker group membership differs)

### 3. Documentation Updated

**~/docs/ccs-security-hardening.md** (new)
- Port analysis and threat model
- Two-layer defense plan (Docker + ACLs)
- Implementation steps with Ansible outlines
- Completion notes for port 5001 fix

**~/docs/ccs-ipfs-replication-ideas.md** (updated)
- Added Section 8: CCS Architecture (v0.4.0+)
- CLI reference with all new options
- Config file format
- CID manifest format
- Removed ipfs-cluster-ctl dependency from onboarding

**README.md** (updated, uncommitted)
- Removed ipfs/ipfs-cluster-ctl installation requirement

## Pending

### Immediate (next session)

1. **Update compose template** - change `CLUSTER_IPFSHTTP_NODEMULTIADDRESS` from `/dns4/0.0.0.0/tcp/5001` to `/ip4/127.0.0.1/tcp/5001`

2. **Push commits** - 3 commits ahead of origin

3. **Test ccs commands** - verify HTTP API works against live cluster:
   ```bash
   ccs ls --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
   ccs add --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml /tmp/test.txt
   ```

### Later (security hardening phase 2)

4. **Headscale ACLs** - restrict ports 4001, 8080, 9094, 9096 to CCS nodes + admin only
   - Tag CCS nodes with `tag:ccs` (removes from autogroup:member)
   - Create ACL policy at `/srv/secrets/headscale/acl.json`
   - See ccs-security-hardening.md for full plan

5. **Ansible playbook** - automate CCS node deployment and hardening

## Key Files

| File | Purpose |
|------|---------|
| `~/docs/ccs-security-hardening.md` | Security plan and implementation notes |
| `~/docs/ccs-ipfs-replication-ideas.md` | Main design doc (updated) |
| `~/.ccs/config.yml` | Basic auth credentials for cluster API |
| `/mnt/hrdag-nas/ccs/compose.yml` | nas-ccs deployment |
| `/mnt/sda1/ccs/compose.yml` | meerkat-ccs deployment |

## Config File Format

**~/.ccs/config.yml:**
```yaml
cluster:
  basic_auth_user: admin
  basic_auth_password: <password>
```

## Quick Reference

```bash
# CCS commands (from Mac, on tailnet)
ccs ls --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
ccs add --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml /path/to/file
ccs status <CID> --cluster-peername nas-ccs --basic-auth-file ~/.ccs/config.yml
ccs get <CID> --cluster-peername nas-ccs --output /path/to/output

# Check node status
ssh nas "cd /mnt/hrdag-nas/ccs && docker compose ps"
ssh meerkat "cd /mnt/sda1/ccs && sudo docker compose ps"

# Verify port 5001 locked down
curl -m 5 -X POST http://nas-ccs:5001/api/v0/id  # should fail
curl -m 5 -X POST http://meerkat-ccs:5001/api/v0/id  # should fail
```

## Git Status

```
Branch: main
Ahead of origin by: 3 commits
Uncommitted: README.md update (minor)
```

Ready to push when you return.
