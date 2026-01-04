# Community Cloud Storage Setup Log

Test deployment of 3-node cluster on local LAN with ZFS-backed storage.

## Hardware Inventory

| Role | Hostname | Hardware | Arch | USB Storage | Notes |
|------|----------|----------|------|-------------|-------|
| bootstrap | rpi5 | Raspberry Pi 5 | ARM64 | TBD | Always-on, low power |
| node-2 | meerkat | System76 Meerkat | x86_64 | TBD | |
| node-3 | beelink | Beelink NUC | x86_64 | TBD | |

## Prerequisites Checklist

### On your laptop (admin workstation)

- [ ] SSH access to all 3 nodes
- [ ] `ipfs` CLI installed ([install guide](https://docs.ipfs.tech/install/command-line/))
- [ ] `ipfs-cluster-ctl` installed ([download](https://dist.ipfs.tech/#ipfs-cluster-ctl))
- [ ] `uv` installed ([install guide](https://docs.astral.sh/uv/getting-started/installation/))
- [ ] Laptop added to headscale tailnet

### On each node

- [ ] Docker installed and running
- [ ] User in `docker` group (or using rootless Docker)
- [ ] USB drive connected

### Headscale

- [ ] Auth key generated for ccs containers
- [ ] ACLs configured to allow nodes to communicate

---

## Phase 0: Node Preparation

Run these steps on each node via SSH from your laptop.

### 0.1 Verify Docker

```bash
docker --version
docker compose version
```

Expected: Docker 24+ and Compose v2.

### 0.2 Identify USB Device

```bash
lsblk
```

Note the device name (e.g., `/dev/sda`). **Do not use a partition like `/dev/sda1` for ZFS - use the whole disk.**

Record here:

| Node | USB Device | Size |
|------|------------|------|
| rpi5 | /dev/sdX | GB |
| meerkat | /dev/sdX | GB |
| beelink | /dev/sdX | GB |

### 0.3 Install ZFS (if needed)

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y zfsutils-linux

# Verify
zfs --version
```

### 0.4 Create ZFS Pool and Dataset

**WARNING: This will erase the USB drive!**

```bash
# Replace /dev/sdX with your actual device
DISK=/dev/sdX

# Create pool (use -f to force if disk has existing partitions)
sudo zpool create -f ccs-pool $DISK

# Create datasets for each service
sudo zfs create ccs-pool/tailscale
sudo zfs create ccs-pool/ipfs
sudo zfs create ccs-pool/ipfs-cluster
sudo zfs create ccs-pool/incoming

# Set mount points
sudo zfs set mountpoint=/srv/ccs/tailscale ccs-pool/tailscale
sudo zfs set mountpoint=/srv/ccs/ipfs ccs-pool/ipfs
sudo zfs set mountpoint=/srv/ccs/ipfs-cluster ccs-pool/ipfs-cluster
sudo zfs set mountpoint=/srv/ccs/incoming ccs-pool/incoming

# Verify
zfs list
ls -la /srv/ccs/
```

Expected output:

```
NAME                   USED  AVAIL  REFER  MOUNTPOINT
ccs-pool               xxx   xxx    xxx    /ccs-pool
ccs-pool/tailscale     xxx   xxx    xxx    /srv/ccs/tailscale
ccs-pool/ipfs          xxx   xxx    xxx    /srv/ccs/ipfs
ccs-pool/ipfs-cluster  xxx   xxx    xxx    /srv/ccs/ipfs-cluster
ccs-pool/incoming      xxx   xxx    xxx    /srv/ccs/incoming
```

### 0.5 Set Permissions for Docker

```bash
# Docker typically runs as root, but let's ensure paths are accessible
sudo chmod 755 /srv/ccs
sudo chmod 755 /srv/ccs/*
```

**Checkpoint:** All 3 nodes should have ZFS pools and datasets ready.

| Node | ZFS Pool Created | Datasets Mounted |
|------|------------------|------------------|
| rpi5 | [ ] | [ ] |
| meerkat | [ ] | [ ] |
| beelink | [ ] | [ ] |

---

## Phase 1: Headscale Auth Key

### 1.1 Generate Auth Key

On your headscale server:

```bash
# Adjust user and expiry as needed
headscale preauthkeys create --user <your-user> --reusable --expiration 90d
```

Record the key: `_______________________________________________`

**Keep this secret!**

### 1.2 Verify ACLs

Ensure your headscale ACL policy allows the ccs nodes to communicate on these ports:

| Port | Service | Protocol |
|------|---------|----------|
| 4001 | IPFS swarm | TCP |
| 5001 | IPFS API | TCP |
| 8080 | IPFS gateway | TCP |
| 9094 | IPFS Cluster API | TCP |
| 9096 | IPFS Cluster swarm | TCP |

---

## Phase 2: Bootstrap Node (rpi5)

### 2.1 Save Auth Key

SSH to rpi5:

```bash
# On rpi5
echo "YOUR_HEADSCALE_KEY_HERE" > ~/.ts-authkey
chmod 600 ~/.ts-authkey
```

### 2.2 Create Working Directory

```bash
mkdir -p ~/ccs && cd ~/ccs
```

### 2.3 Generate Compose File

From your **laptop** (which has community-cloud-storage installed):

```bash
uvx community-cloud-storage create \
    --ts-authkey-file ~/.ts-authkey \
    --cluster-peername rpi5 \
    --output rpi5-compose.yml
```

Then copy to the node:

```bash
scp rpi5-compose.yml rpi5:~/ccs/compose.yml
```

**Alternative:** If your laptop doesn't have the auth key file, copy it temporarily or run the command on a machine that does.

### 2.4 Modify Compose for ZFS Volumes

SSH to rpi5 and edit `~/ccs/compose.yml`:

**Before (Docker named volumes):**

```yaml
services:
  tailscale:
    volumes:
      - tailscale:/var/lib/tailscale
  ipfs:
    volumes:
      - ipfs:/data/ipfs
  ipfs-cluster:
    volumes:
      - ipfs-cluster:/data/ipfs-cluster
      - ./incoming:/incoming

volumes:
  ipfs:
  ipfs-cluster:
  tailscale:
```

**After (ZFS bind mounts):**

```yaml
services:
  tailscale:
    volumes:
      - /srv/ccs/tailscale:/var/lib/tailscale
  ipfs:
    volumes:
      - /srv/ccs/ipfs:/data/ipfs
  ipfs-cluster:
    volumes:
      - /srv/ccs/ipfs-cluster:/data/ipfs-cluster
      - /srv/ccs/incoming:/incoming

# DELETE the volumes: section at the bottom entirely
```

### 2.5 Headscale-Specific Tailscale Config

For self-hosted Tailscale (headscale), you may need to add the login server URL. Edit the tailscale service environment:

```yaml
  tailscale:
    image: tailscale/tailscale:latest
    hostname: rpi5
    environment:
      TS_AUTHKEY: <your-key>
      TS_STATE_DIR: /var/lib/tailscale
      TS_USERSPACE: false
      TS_EXTRA_ARGS: --login-server=https://your-headscale-server.example.com
    # ... rest unchanged
```

### 2.6 Start Bootstrap Node

```bash
cd ~/ccs
docker compose up -d
```

### 2.7 Verify

```bash
# Check containers running
docker compose ps

# Check tailscale connected
docker compose exec tailscale tailscale status

# Check IPFS running
docker compose exec ipfs ipfs id
```

Also verify in headscale:

```bash
headscale nodes list
```

You should see `rpi5` registered.

**Checkpoint:**

- [ ] rpi5 containers running (4 containers)
- [ ] rpi5 visible in headscale
- [ ] IPFS responding

---

## Phase 3: Clone and Join (meerkat, beelink)

### 3.1 Generate Clone Compose Files

From your **laptop** (must be on tailnet to reach rpi5):

```bash
# For meerkat
uvx community-cloud-storage clone \
    --input rpi5-compose.yml \
    --cluster-peername meerkat \
    --bootstrap-host rpi5 \
    --output meerkat-compose.yml

# For beelink
uvx community-cloud-storage clone \
    --input rpi5-compose.yml \
    --cluster-peername beelink \
    --bootstrap-host rpi5 \
    --output beelink-compose.yml
```

**Note:** The clone command talks to the running bootstrap node to get IPFS peer IDs, so rpi5 must be running and reachable via tailnet.

### 3.2 Copy and Modify Compose Files

For each node (meerkat and beelink):

```bash
# Copy to node
scp meerkat-compose.yml meerkat:~/ccs/compose.yml

# SSH to node
ssh meerkat

# Edit compose.yml:
# 1. Replace Docker volumes with ZFS bind mounts (same as Phase 2.4)
# 2. Add TS_EXTRA_ARGS for headscale (same as Phase 2.5)
```

### 3.3 Start Nodes

On each node:

```bash
cd ~/ccs
docker compose up -d
docker compose ps
```

### 3.4 Verify Cluster

From any node or your laptop (on tailnet):

```bash
# Check cluster peers
ipfs-cluster-ctl --host /dns4/rpi5/tcp/9094 peers ls
```

Should show 3 peers.

**Checkpoint:**

| Node | Containers Up | In Headscale | In Cluster |
|------|---------------|--------------|------------|
| rpi5 | [ ] | [ ] | [ ] |
| meerkat | [ ] | [ ] | [ ] |
| beelink | [ ] | [ ] | [ ] |

---

## Phase 4: Testing

### 4.1 Access Web UI

From your laptop browser (must be on tailnet):

- http://rpi5 - bootstrap node UI
- http://meerkat - node 2 UI
- http://beelink - node 3 UI

### 4.2 Add Test File

```bash
# Create test file
echo "Hello from community cloud storage test" > /tmp/test.txt

# Add via CLI (from laptop, targeting any node)
uvx community-cloud-storage add --cluster-peername rpi5 /tmp/test.txt
```

Note the CID returned: `_______________________________________________`

### 4.3 Check Replication Status

```bash
uvx community-cloud-storage status --cluster-peername rpi5 <CID>
```

Should show the file pinned on all 3 nodes.

### 4.4 Retrieve From Different Node

```bash
# Get the file from a different node than where it was added
uvx community-cloud-storage get \
    --cluster-peername beelink \
    --output /tmp/test-retrieved.txt \
    <CID>

# Verify contents
cat /tmp/test-retrieved.txt
```

### 4.5 Test Deletion

```bash
uvx community-cloud-storage rm --cluster-peername rpi5 <CID>

# Verify removed from all nodes
uvx community-cloud-storage status --cluster-peername meerkat <CID>
```

---

## Phase 5: Notes and Observations

### Issues Encountered

_Document any problems and solutions here as you go._

| Issue | Node(s) | Solution |
|-------|---------|----------|
| | | |

### Performance Observations

_Note any latency, sync times, etc._

### Changes Made to Tool

_If we need to modify community-cloud-storage during setup, note them here._

---

## Appendix A: Compose Volume Diff

Full diff for converting Docker volumes to ZFS bind mounts:

```diff
 services:
   tailscale:
     volumes:
-      - tailscale:/var/lib/tailscale
+      - /srv/ccs/tailscale:/var/lib/tailscale

   ipfs:
     volumes:
-      - ipfs:/data/ipfs
+      - /srv/ccs/ipfs:/data/ipfs

   ipfs-cluster:
     volumes:
-      - ipfs-cluster:/data/ipfs-cluster
-      - ./incoming:/incoming
+      - /srv/ccs/ipfs-cluster:/data/ipfs-cluster
+      - /srv/ccs/incoming:/incoming

-volumes:
-  ipfs:
-  ipfs-cluster:
-  tailscale:
```

## Appendix B: Useful Commands

```bash
# View IPFS cluster peers
ipfs-cluster-ctl --host /dns4/<node>/tcp/9094 peers ls

# View IPFS swarm peers
ipfs --api /dns/<node>/tcp/5001 swarm peers

# List all pinned content
uvx community-cloud-storage ls --cluster-peername <node>

# Check ZFS pool status
zpool status ccs-pool

# Check ZFS dataset usage
zfs list -r ccs-pool

# Restart all containers
docker compose restart

# View logs
docker compose logs -f
```

## Appendix C: Teardown

To remove everything and start fresh:

```bash
# On each node
cd ~/ccs
docker compose down -v

# Optionally destroy ZFS (WARNING: deletes all data)
sudo zpool destroy ccs-pool
```
