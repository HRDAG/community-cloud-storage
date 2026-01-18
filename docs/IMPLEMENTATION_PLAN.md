# Implementation Plan: Full Archival Pipeline with 5-Org Multi-Tenant Setup

<!--
NOTE FOR AUTHOR: This document has been amended to align with ntx v2 architecture.
See "Changes from v1 Draft" section at the end for a summary of modifications.
Original preserved in IMPLEMENTATION_PLAN-v1-original.md
-->

## Goal

Transform the current prototype to a production-grade local development environment replicating the actual HRDAG deployment to 5 partner NGOs:
- **Full ntx archival pipeline** (encryption, hashing, Merkle trees, Ed25519 signatures, OpenTimestamps, IPFS uploads)
- **5-organization architecture** (HRDAG/nas + 4 partner NGOs), each with dedicated UI + API + IPFS node
- **Role-based IPFS replication** with allocation filters ensuring exactly 3 replicas per CID
- **Decoupled workflow**: UI stages files → API triggers ntx → ntx handles IPFS+S3
- **S3-compatible backup** via MinIO

## Key Architecture Decisions

Based on production requirements:
1. **5 orgs, 5 nodes**: Each organization operates 1 IPFS node (matching planned NGO deployment)
2. **UI decoupling**: Web UI only stages files to `/uploads`, doesn't interact with IPFS directly
3. **ntx orchestration**: API `/archive` endpoint triggers full ntx pipeline which handles IPFS cluster uploads and S3 backup
4. **Role-based replication**: IPFS cluster uses allocation filters with role tags to ensure 3 replicas across different organizations

---

## Current State

**Location**: `/Users/croblee/dev/hrdag/community-cloud-storage/`

**Architecture**:
```
Single UI (3000) → Single API (8000) → PostgreSQL + 3-node IPFS cluster (unused)
```

**Limitations**:
- Files stored as plaintext (no encryption)
- Mock CIDs ("mock-cid-1-...")
- Mock hashes ("mock-hash-...")
- No Merkle tree construction
- No Ed25519 signatures
- No OpenTimestamps
- IPFS cluster running but files never uploaded

**From server-documentation/docs/overview.md**:
Production archival flow:
```
filesystem → filelister → PostgreSQL (scottfiles.paths)
                               ↓
                          ntx scan
                               ↓
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
          IPFS CID      OpenTimestamps    Ed25519 sig
               └───────────────┴───────────────┘
                               ↓
                    community-cloud-storage
```

---

## Target Architecture

```
5 Organization Instances (Production-Like Multi-Tenant):

┌──────────────────────────────────────────────────────┐
│ hrdag-ui (3001) → hrdag-api (8001) → hrdag-ipfs      │
│   Role: primary, Org: hrdag, Node: nas               │
├──────────────────────────────────────────────────────┤
│ org2-ui (3002) → org2-api (8002) → org2-ipfs        │
│   Role: primary, Org: org2                           │
├──────────────────────────────────────────────────────┤
│ org3-ui (3003) → org3-api (8003) → org3-ipfs        │
│   Role: backup, Org: org3                            │
├──────────────────────────────────────────────────────┤
│ org4-ui (3004) → org4-api (8004) → org4-ipfs        │
│   Role: backup, Org: org4                            │
├──────────────────────────────────────────────────────┤
│ org5-ui (3005) → org5-api (8005) → org5-ipfs        │
│   Role: cross-org, Org: org5                         │
└──────────────────────────────────────────────────────┘
                    ↓
             Shared PostgreSQL
                    ↓
    5-Node IPFS Cluster (replication: min=3, max=3)
    Role-based allocation ensures 3 replicas
                    ↓
             MinIO S3 (backup)
```

**Network Layout**: 172.30.0.0/24
- PostgreSQL: .10
- IPFS kubo nodes: .21-.25 (5 nodes)
- IPFS cluster nodes: .31-.35 (5 nodes)
- API services: .41-.45 (5 APIs)
- UI services: .51-.55 (5 UIs)
- MinIO: .60

**Role Tags** (for allocation filters):
- hrdag/nas: `{"role":"primary","org":"hrdag"}`
- org2: `{"role":"primary","org":"org2"}`
- org3: `{"role":"backup","org":"org3"}`
- org4: `{"role":"backup","org":"org4"}`
- org5: `{"role":"cross-org","org":"org5"}`

**Replication Strategy**:
- Set `replication_factor_min=3, replication_factor_max=3`
- Cluster allocator uses role tags to distribute replicas:
  - 1 replica on uploader's primary node
  - 1 replica on backup node
  - 1 replica on cross-org node
- Ensures data redundancy across different organizations

---

## NTX Archival Pipeline (8 Stages)

<!-- NOTE: Updated to reflect ntx v2 architecture per ntx/docs/design-v2-commit-packaging.md -->

The API `/archive` endpoint triggers ntx's `ProcessingPipeline` which orchestrates all 8 stages:

### Stage 1: Collect
**Module**: `ntx/process.py:_stage_collect()`
- Query pending files from database (`commit_id IS NULL`)
- Generate commit_id (ISO timestamp: `2026-01-17T10:30:00Z`)
- Claim files to prevent duplicate processing
- Create staging directory: `/staging/commit_<commit_id>/`

### Stage 2: Hash
**Module**: `ntx/process.py:_stage_hash()` + `ntx/hashing.py:content_hash()`
- Compute BLAKE3 content_hash on raw file data
- Detect MIME type with `python-magic`
- Update database with content_hash

### Stage 3: Encrypt
**Module**: `ntx/process.py:_stage_encrypt()` + `ntx/crypto.py:encrypt()`
- Compress with LZ4 frame compression
- Encrypt with XChaCha20-Poly1305 (PyNaCl libsodium secretstream)
- Output: `/staging/commit_<id>/files/<content_hash>.enc`
- Build per-file metadata (encryption params, nonce)
- Compute metadata_hash = BLAKE3(canonical_json(metadata))

### Stage 4: Build Merkle Tree
**Module**: `ntx/process.py:_stage_build_tree()` + `ntx/merkle.py:build_tree()`
- Collect all metadata_hash values as leaves
- Construct Merkle tree (pairs hashed recursively with BLAKE3)
- Generate Merkle proofs for each leaf (siblings + left/right directions)
- Store merkle_root

### Stage 5: Package
<!-- NOTE: v2 change - replaces "Write Sidecars" stage -->
**Module**: `ntx/process.py:_stage_package()` + `ntx/packaging.py`
- Create tar archive of all `.enc` files (no compression - already encrypted)
- Split into ~50MB chunks: `split -b 50m archive.tar "${COMMIT_ID}_"`
- Generate par2 parity files (5% redundancy) for error recovery
- Delete intermediate `.enc` files after tar creation
- Output: `~20 chunks + par2 index + par2 parity (~24 files total)`

**Why packaging?** IPFS cluster multipart uploads stall with >300 files. Packaging
reduces files-per-upload from hundreds to ~24, solving the stall issue while adding
par2 error correction for durability.

### Stage 6: Sign
**Module**: `ntx/process.py:_stage_sign()` + `ntx/signing.py:sign_merkle_root()`
- Sign merkle_root with Ed25519 private key
- Build Manifest v2 JSON with:
  - commit_id, merkle_root, leaf_count
  - Per-file metadata **inline** (content_hash, encryption params, merkle_proof)
  - Packaging info (chunk_count, chunk_size, par2_redundancy)
  - Ed25519 signature (base64-encoded)
  - Software version, key IDs
- Write `/staging/commit_<id>/manifest.json`
- Record commit in database

### Stage 7: OpenTimestamps
**Module**: `ntx/ots.py:submit_and_save()`
- Submit merkle_root to OTS calendar servers:
  - `https://a.pool.opentimestamps.org`
  - `https://b.pool.opentimestamps.org`
- Receive pending timestamp
- Write `/staging/commit_<id>/manifest.json.ots` proof file
- Update database: `commits.ots_submitted_at = NOW()`
- **Note**: Bitcoin confirmation takes hours-to-days. Use `ntx upgrade` command later to check for confirmation.

### Stage 8: IPFS Upload + S3 Backup
<!-- NOTE: v2 change - uploads packaged commit (~24 files), not per-file -->
**Module**: `ntx/ipfs.py:upload()` + `ntx/s3.py:upload()`

**IPFS Upload**:
- Upload packaged commit directory to IPFS cluster (~24 files)
- Uses CCS library with profile-based configuration:
  ```python
  from community_cloud_storage.operations import add
  result = add(
      path=commit_dir,        # Contains chunks, par2, manifest
      profile="hrdag",        # or "org2", "org3", etc.
      config=ccs_config,
  )
  ```
- CCS determines allocations based on profile
- Extract single `commit_cid` from result (root directory CID)
- Update database:
  - `commits.commit_cid = <root_cid>`
  - `commits.uploaded_at = NOW()`

**S3 Backup** (via MinIO):
- Upload commit directory to S3-compatible storage
- Key structure: `commits/{commit_id}/{filename}`
- Update database: `commits.s3_uploaded_at = NOW()`

**Output Structure (v2)**:
```
staging/commit_2026-01-17T10:30:00Z/
├── 2026-01-17T10:30:00Z_aa       # chunk 1 (~50MB)
├── 2026-01-17T10:30:00Z_ab       # chunk 2
├── ...                            # ~20 chunks total
├── 2026-01-17T10:30:00Z.par2     # par2 index (~50KB)
├── 2026-01-17T10:30:00Z.vol00+20.par2  # par2 parity (~50MB at 5%)
├── manifest.json                  # Signed manifest with all metadata
└── manifest.json.ots              # OpenTimestamps proof

# Entire directory gets single commit_cid stored in commits.commit_cid
# Total: ~24 files, ~1.05GB per commit (1GB data + 5% parity)
```

---

## Manifest Format (v2)

<!-- NOTE: v2 consolidates all per-file metadata into manifest (no sidecars) -->

```json
{
  "version": 2,
  "commit_id": "2026-01-17T10:30:00Z",

  "files": [
    {
      "path_hex": "2f686f6d652f757365722f646f632e706466",
      "path_display": "/home/user/doc.pdf",
      "size": 12345,
      "mtime": 1705500000,
      "content_hash": "blake3:abc123def456...",
      "metadata_hash": "blake3:789xyz...",
      "filetype": "application/pdf",
      "encryption": {
        "algorithm": "XChaCha20-Poly1305",
        "key_id": "hrdag-backup-2026",
        "nonce": "base64-encoded-24-byte-nonce",
        "compressed": true,
        "compression_algorithm": "lz4"
      },
      "merkle_proof": {
        "leaf_index": 0,
        "siblings": ["blake3:sibling1...", "blake3:sibling2..."],
        "directions": ["L", "R"]
      }
    }
  ],

  "merkle": {
    "algorithm": "blake3",
    "root": "blake3:merkle-root-hash...",
    "leaf_count": 42
  },

  "signature": {
    "algorithm": "ed25519",
    "signer_org": "hrdag",
    "signer_key_id": "hrdag-signing-2026",
    "value": "base64-encoded-ed25519-signature"
  },

  "chain": {
    "sequence": 305,
    "previous_commit_id": "2026-01-16T22:00:00Z",
    "previous_merkle_root": "blake3:previous-root..."
  },

  "packaging": {
    "format": "tar+split+par2",
    "chunk_size": 52428800,
    "chunk_prefix": "2026-01-17T10:30:00Z_",
    "chunk_count": 21,
    "par2_redundancy": 5
  },

  "provenance": {
    "organization": "hrdag"
  },

  "software": {
    "name": "ntx",
    "version": "0.2.0"
  },

  "created_at": "2026-01-17T10:30:00Z"
}
```

---

## Critical Files to Modify

### 1. API Service Integration

**File**: `api/app.py` → backup to `api/app_original.py`
**File**: `api/app_ntx.py` (NEW) - Full ntx integration

**Key Architecture**:
- **UI Responsibility**: Only stages files to `/uploads/<date>/` directory via `POST /upload`
- **API Responsibility**: Triggers ntx pipeline via `POST /archive`
- **ntx Responsibility**: Handles encryption, Merkle trees, signing, OTS, packaging, IPFS uploads, S3 backup

**Implementation**:
```python
from pathlib import Path
from datetime import datetime, timezone

from ntx.process import ProcessingPipeline
from ntx.crypto import load_encryption_key
from ntx.signing import load_signing_key
from ntx.db import Database
from ntx.ots import submit_and_save
from ntx import ipfs as ntx_ipfs
from ntx import s3 as ntx_s3
from community_cloud_storage.config import load_config as load_ccs_config

class ArchivalService:
    """Wraps ntx pipeline for FastAPI integration.

    Decouples UI from IPFS operations - UI only stages files,
    API triggers ntx which handles all archival operations.
    """

    def __init__(self, config: dict):
        self.db = Database(config['database_url'])
        self.staging_dir = Path(config['staging_dir'])
        self.encryption_key = load_encryption_key(Path(config['encryption_key_path']))
        self.signing_key = load_signing_key(Path(config['signing_key_path']))
        self.organization = config['organization']
        self.ccs_config = load_ccs_config(Path(config['ccs_config_path']))
        self.ccs_profile = config['ccs_profile']

    def run_pipeline(self, batch_size_gb: float = 0.1) -> dict:
        """Execute full 8-stage ntx pipeline.

        Returns commit details including commit_cid.
        """
        # Stages 1-6: Collect, Hash, Encrypt, Build Tree, Package, Sign
        pipeline = ProcessingPipeline(
            db=self.db,
            staging_dir=self.staging_dir,
            encryption_key=self.encryption_key,
            signing_key=self.signing_key,
            organization=self.organization,
            batch_size_bytes=int(batch_size_gb * 1e9),
        )
        result = pipeline.run()

        if result['status'] == 'empty':
            return {'status': 'empty', 'message': 'No pending files to archive'}

        commit_dir = Path(result['commit_dir'])
        commit_id = result['commit_id']

        # Stage 7: OpenTimestamps (Bitcoin anchoring)
        ots_path = commit_dir / "manifest.json.ots"
        submit_and_save(
            merkle_root_hex=result['merkle_root'],
            output_path=ots_path,
            calendars=[
                "https://a.pool.opentimestamps.org",
                "https://b.pool.opentimestamps.org",
            ],
            timeout=30
        )
        self.db.update_commit_timestamp(commit_id, 'ots_submitted_at', datetime.now(timezone.utc))

        # Stage 8: IPFS Upload + S3 Backup
        ipfs_result = ntx_ipfs.upload(
            commit_dir=commit_dir,
            profile=self.ccs_profile,
            ccs_config=self.ccs_config,
        )
        self.db.update_commit_cid(commit_id, ipfs_result.identifier)
        self.db.update_commit_timestamp(commit_id, 'uploaded_at', ipfs_result.completed_at)

        # Optional S3 backup
        if self.config.get('s3_enabled'):
            s3_result = ntx_s3.upload(commit_dir=commit_dir, config=self.s3_config)
            self.db.update_commit_timestamp(commit_id, 's3_uploaded_at', s3_result.completed_at)

        return {
            'status': 'completed',
            'commit_id': commit_id,
            'file_count': result['file_count'],
            'total_size': result['total_size'],
            'merkle_root': result['merkle_root'],
            'commit_cid': ipfs_result.identifier,
            'ots_submitted': True,
            'note': 'Commit packaged and uploaded to IPFS cluster with 3 replicas'
        }

# FastAPI endpoints
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Stage file for archival (UI → API)"""
    # Save to /uploads/<date>/ directory
    # Does NOT touch IPFS - just filesystem staging

@app.post("/catalog")
async def run_catalog():
    """Scan /uploads and insert metadata to PostgreSQL"""
    # Simplified filelister-like scan

@app.post("/archive")
async def run_archive(batch_size_gb: float = 0.1):
    """Trigger full ntx pipeline (API → ntx → IPFS+S3)"""
    archival_service = ArchivalService(config)
    return archival_service.run_pipeline(batch_size_gb)
```

**Endpoints**:
- `POST /upload` - Stage file (UI → API, saves to /uploads/)
- `POST /catalog` - Scan /uploads/ and insert to database
- `POST /archive` - Trigger full ntx pipeline (returns commit_cid)
- `POST /archive/ots-upgrade` - Check OTS confirmation status
- `GET /archive/commit/{commit_id}` - Get commit details + CID
- `GET /status`, `GET /files`, `GET /commits` - Query data (unchanged)

### 2. Dependencies

**File**: `api/requirements.txt` (MODIFY)

```txt
# Existing
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-multipart==0.0.6
psycopg[binary]==3.1.18
pydantic==2.5.3
pydantic-settings==2.1.0

# NTX cryptographic dependencies
blake3>=1.0.0
lz4>=4.3.0
pynacl>=1.5.0
cryptography>=44.0.0
opentimestamps>=0.4.5
opentimestamps-client>=0.7.0
python-magic>=0.4.27
loguru>=0.7.0

# CCS (installed from local path in Dockerfile)
pyyaml>=6.0
requests>=2.31.0
requests-toolbelt>=1.0.0
```

### 3. Dockerfile

**File**: `api/Dockerfile` (MODIFY)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System dependencies (add libmagic for MIME detection, par2 for packaging)
RUN apt-get update && apt-get install -y \
    findutils \
    postgresql-client \
    libpq-dev \
    gcc \
    curl \
    libmagic1 \
    par2 \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install uv
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Install ntx and CCS from local repos
# (Docker build context includes parent directories)
COPY ../../ntx /tmp/ntx
COPY ../../community-cloud-storage/src /tmp/ccs
RUN cd /tmp/ntx && uv pip install --system -e . && \
    cd /tmp/ccs && uv pip install --system -e . && \
    rm -rf /tmp/ntx /tmp/ccs

# Copy application
COPY app_ntx.py app.py

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4. Docker Compose

**File**: `deployment/local/docker-compose.yml` (MAJOR UPDATE)

**Changes**:
- Add 5 org API services (hrdag-api, org2-api, org3-api, org4-api, org5-api)
- Add 5 org UI services (hrdag-ui, org2-ui, org3-ui, org4-ui, org5-ui)
- Add 5 IPFS nodes (node1-5) with 5 cluster nodes
- Add MinIO service
- Add per-org volumes (upload-hrdag, staging-hrdag, upload-org2, staging-org2, etc.)
- Mount keys directory (read-only)
- Mount config directory (read-only)
- Configure role tags per node

**Example Service** (HRDAG/nas):
```yaml
# ===================================================================
# HRDAG ORGANIZATION (nas node)
# ===================================================================

hrdag-api:
  build:
    context: ../../api
    dockerfile: Dockerfile
  container_name: archival-hrdag-api
  depends_on:
    postgres:
      condition: service_healthy
    hrdag-node-cluster:
      condition: service_started
  environment:
    - ORGANIZATION=hrdag
    - CONFIG_PATH=/config/hrdag.toml
    - CCS_CONFIG_PATH=/config/ccs-config.yml
  volumes:
    - upload-hrdag:/uploads
    - staging-hrdag:/staging
    - ./keys:/keys:ro
    - ./config:/config:ro
  ports:
    - "8001:8000"
  networks:
    archival-net:
      ipv4_address: 172.30.0.41

hrdag-ui:
  build:
    context: ../../ui
    dockerfile: Dockerfile
  container_name: archival-hrdag-ui
  depends_on:
    - hrdag-api
  environment:
    - VITE_API_URL=http://localhost:8001
    - VITE_ORG_NAME=HRDAG
  ports:
    - "3001:80"
  networks:
    archival-net:
      ipv4_address: 172.30.0.51

# HRDAG IPFS Node (nas)
hrdag-node-ipfs:
  image: ipfs/kubo:latest
  container_name: hrdag-node-ipfs
  entrypoint: /custom-entrypoint.sh
  environment:
    - LIBP2P_FORCE_PNET=1
  volumes:
    - hrdag-ipfs-data:/data/ipfs
    - ./ccs-config/swarm.key:/data/ipfs/swarm.key
    - ./ipfs-init/entrypoint.sh:/custom-entrypoint.sh:ro
  networks:
    archival-net:
      ipv4_address: 172.30.0.21

hrdag-node-cluster:
  image: ipfs/ipfs-cluster:latest
  container_name: hrdag-node-cluster
  depends_on:
    - hrdag-node-ipfs
  environment:
    - CLUSTER_PEERNAME=hrdag-nas
    - CLUSTER_SECRET=${CLUSTER_SECRET}
    - CLUSTER_IPFSHTTP_NODEMULTIADDRESS=/ip4/172.30.0.21/tcp/5001
    - CLUSTER_RESTAPI_HTTPLISTENMULTIADDRESS=/ip4/0.0.0.0/tcp/9094
    - CLUSTER_REPLICATIONFACTORMIN=3
    - CLUSTER_REPLICATIONFACTORMAX=3
    - CLUSTER_DISABLEREPINNING=false
    - CLUSTER_INFORMER_TAGS_TAGS={"role":"primary","org":"hrdag"}
  volumes:
    - hrdag-cluster-data:/data/ipfs-cluster
  ports:
    - "9091:9094"  # REST API
    - "9096:9096"  # Cluster swarm
  networks:
    archival-net:
      ipv4_address: 172.30.0.31

# Repeat pattern for org2, org3, org4, org5 with:
# - Different IPs (.22-.25 for IPFS, .32-.35 for cluster, .42-.45 for API, .52-.55 for UI)
# - Different ports (8002-8005 for API, 3002-3005 for UI, 9092-9095 for cluster REST)
# - Different role tags (see Target Architecture section)
```

**MinIO Service**:
```yaml
minio:
  image: minio/minio:latest
  container_name: archival-minio
  command: server /data --console-address ":9001"
  environment:
    - MINIO_ROOT_USER=minioadmin
    - MINIO_ROOT_PASSWORD=minioadmin123
  volumes:
    - minio-data:/data
  ports:
    - "9000:9000"   # S3 API
    - "9001:9001"   # Web console
  networks:
    archival-net:
      ipv4_address: 172.30.0.60
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
    interval: 10s
    timeout: 5s
    retries: 3
```

**Volumes**:
```yaml
volumes:
  postgres-data:
  hrdag-ipfs-data:
  hrdag-cluster-data:
  org2-ipfs-data:
  org2-cluster-data:
  org3-ipfs-data:
  org3-cluster-data:
  org4-ipfs-data:
  org4-cluster-data:
  org5-ipfs-data:
  org5-cluster-data:
  upload-hrdag:
  staging-hrdag:
  upload-org2:
  staging-org2:
  upload-org3:
  staging-org3:
  upload-org4:
  staging-org4:
  upload-org5:
  staging-org5:
  minio-data:
```

### 5. Setup Script

**File**: `deployment/local/setup.sh` (MODIFY)

**Add Key Generation**:
```bash
echo "Generating cryptographic keys..."
mkdir -p keys config

# Generate Ed25519 signing keys for each org
for org in hrdag org2 org3 org4 org5; do
    if [ ! -f "keys/${org}-signing" ]; then
        ssh-keygen -t ed25519 -f "keys/${org}-signing" -N "" -C "${org}@local-dev"
        echo "Generated Ed25519 signing key for ${org}"
    else
        echo "Using existing signing key for ${org}"
    fi

    # Generate XChaCha20-Poly1305 encryption keys (32 random bytes)
    if [ ! -f "keys/${org}-encryption.key" ]; then
        openssl rand 32 > "keys/${org}-encryption.key"
        chmod 600 "keys/${org}-encryption.key"
        echo "Generated encryption key for ${org}"
    else
        echo "Using existing encryption key for ${org}"
    fi
done

echo "Creating organization configs..."
./scripts/create-org-configs.sh

echo "Peer IDs will be extracted after cluster starts..."
echo "   Run: docker compose up -d"
echo "   Then: ./scripts/extract-peer-ids.sh"
```

**Add Peer ID Extraction** (run after docker compose up):
```bash
#!/bin/bash
# scripts/extract-peer-ids.sh
set -e

echo "Waiting for cluster to start..."
sleep 30

echo "Extracting IPFS cluster peer IDs..."

for i in 1 2 3 4 5; do
    port=$((9090 + i))
    echo "Checking node $i on port $port..."
    peer_id=$(curl -s http://localhost:${port}/id | jq -r '.id')

    if [ -n "$peer_id" ]; then
        echo "  Node $i: $peer_id"
        # Update ccs-config.yml with yq or sed
        # (Requires yq installed or use sed)
    else
        echo "  Failed to get peer ID from node $i"
    fi
done

echo "Peer IDs extracted. Restart API services to reload config:"
echo "   docker compose restart hrdag-api org2-api org3-api org4-api org5-api"
```

### 6. Configuration Files (NEW)

**Create**: `deployment/local/config/hrdag.toml`

```toml
[database]
dsn = "postgresql://archival:dev-password-change-in-production@postgres:5432/scottfiles"

[staging]
directory = "/staging"

[organization]
name = "hrdag"

[keys]
signing_key_path = "/keys/hrdag-signing"
encryption_key_path = "/keys/hrdag-encryption.key"

[ipfs]
api_addr = "/ip4/172.30.0.31/tcp/9094"  # Cluster REST API
profile = "hrdag"

[timestamps]
calendar_urls = [
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
]
timeout_seconds = 30

[commit]
size_limit_gb = 0.1
max_file_size_mb = 100

[rclone]
enabled = false  # Disable for local dev (use MinIO instead if needed)
```

**Replicate for org2.toml, org3.toml, org4.toml, org5.toml** with respective IPs and profiles.

**Create**: `deployment/local/config/ccs-config.yml`

```yaml
cluster:
  basic_auth_user: admin
  basic_auth_password: secret123

# Default node for CLI operations
default_node: hrdag-nas

# Backup/cross-org nodes
backup_node: org3
cross_org_node: org5

# Organization profiles map org name to primary node
profiles:
  hrdag:
    primary: hrdag-nas
  org2:
    primary: org2-node
  org3:
    primary: org3-node
  org4:
    primary: org4-node
  org5:
    primary: org5-node

# Cluster nodes with peer IDs (populated by extract-peer-ids.sh)
nodes:
  hrdag-nas:
    host: 172.30.0.31
    peer_id: ""  # Will be populated
    tags:
      role: "primary"
      org: "hrdag"
  org2-node:
    host: 172.30.0.32
    peer_id: ""
    tags:
      role: "primary"
      org: "org2"
  org3-node:
    host: 172.30.0.33
    peer_id: ""
    tags:
      role: "backup"
      org: "org3"
  org4-node:
    host: 172.30.0.34
    peer_id: ""
    tags:
      role: "backup"
      org: "org4"
  org5-node:
    host: 172.30.0.35
    peer_id: ""
    tags:
      role: "cross-org"
      org: "org5"
```

**Allocation Filter Logic** (enforced by IPFS Cluster):
When HRDAG uploads with `profile="hrdag"`:
1. Replica 1: hrdag-nas (explicit allocation, primary)
2. Replica 2: org3-node (backup role, different org)
3. Replica 3: org5-node (cross-org role, ensures cross-organizational redundancy)

This ensures every CID has 3 replicas across different organizations.

---

## Implementation Steps

### Phase 1: Foundation (Days 1-2)

1. **Backup current prototype**:
   ```bash
   cp api/app.py api/app_original.py
   cp deployment/local/docker-compose.yml deployment/local/docker-compose-3org.yml.bak
   ```

2. **Update requirements.txt**:
   - Add ntx dependencies (blake3, pynacl, lz4, opentimestamps, cryptography, python-magic)

3. **Update Dockerfile**:
   - Add libmagic and par2 system packages
   - Install ntx and CCS from local paths (`COPY ../../ntx /tmp/ntx`)

4. **Enhance setup.sh**:
   - Add key generation loop (Ed25519 + encryption keys for 5 orgs)
   - Create config directory
   - Call `create-org-configs.sh` script

5. **Create scripts/extract-peer-ids.sh**:
   - Extract cluster peer IDs after docker compose up
   - Update ccs-config.yml with peer IDs

### Phase 2: API Integration (Days 3-4)

6. **Create api/app_ntx.py**:
   - Import ntx modules and CCS
   - Create `ArchivalService` class
   - Implement `run_pipeline()` method (8 stages including packaging)
   - Keep existing endpoints (/upload saves to /uploads/, /catalog scans)
   - Replace `/archive` endpoint with real ntx pipeline trigger
   - Add `/archive/ots-upgrade` and `/archive/resume/{commit_id}`

7. **Test single-org workflow** (HRDAG only):
   ```bash
   docker compose up -d postgres hrdag-node-ipfs hrdag-node-cluster hrdag-api
   curl -F "file=@test.txt" http://localhost:8001/upload
   curl -X POST http://localhost:8001/catalog
   curl -X POST http://localhost:8001/archive?batch_size_gb=0.01
   # Verify real CID in response (not "mock-cid-...")
   ```

### Phase 3: 5-Org Deployment (Days 5-6)

8. **Update docker-compose.yml**:
   - Add hrdag-api, hrdag-ui (ports 8001, 3001, IPs .41, .51, .21, .31)
   - Add org2-api, org2-ui (ports 8002, 3002, IPs .42, .52, .22, .32)
   - Add org3-api, org3-ui (ports 8003, 3003, IPs .43, .53, .23, .33)
   - Add org4-api, org4-ui (ports 8004, 3004, IPs .44, .54, .24, .34)
   - Add org5-api, org5-ui (ports 8005, 3005, IPs .45, .55, .25, .35)
   - Add MinIO service (ports 9000, 9001, IP .60)
   - Add per-org volumes (10 upload volumes, 10 staging volumes, minio-data)
   - Mount keys and config directories (read-only)
   - Configure role tags per node

9. **Create config files**:
   - `config/hrdag.toml`, `config/org2.toml`, `config/org3.toml`, `config/org4.toml`, `config/org5.toml`
   - `config/ccs-config.yml`

10. **Run setup and start cluster**:
    ```bash
    cd deployment/local
    ./setup.sh
    docker compose up -d
    sleep 60  # Wait for 5-node cluster to form
    ./scripts/extract-peer-ids.sh
    docker compose restart hrdag-api org2-api org3-api org4-api org5-api
    ```

### Phase 4: Testing & Validation (Days 7-8)

11. **Test multi-org concurrent uploads**:
    ```bash
    # HRDAG
    curl -F "file=@testdata/hrdag1.txt" http://localhost:8001/upload
    curl -X POST http://localhost:8001/catalog
    curl -X POST http://localhost:8001/archive

    # Org2 (simultaneously)
    curl -F "file=@testdata/org2file.txt" http://localhost:8002/upload
    curl -X POST http://localhost:8002/catalog
    curl -X POST http://localhost:8002/archive
    ```

12. **Verify database has real data**:
    ```bash
    docker exec archival-postgres psql -U archival -d scottfiles -c \
      "SELECT id, commit_cid, merkle_root, leaf_count FROM commits LIMIT 5;"

    # Should show:
    # - Real merkle_root (64 hex chars)
    # - Real IPFS commit_cid (bafybei...)
    # - NOT "mock-..."
    ```

13. **Verify IPFS cluster replication (exactly 3 replicas)**:
    ```bash
    # Get commit_cid from database
    cid=$(docker exec archival-postgres psql -U archival -d scottfiles -t -c \
      "SELECT commit_cid FROM commits WHERE commit_cid IS NOT NULL LIMIT 1;" | xargs)

    # Check replication status
    curl -s http://localhost:9091/pins/${cid} | jq '.peer_map'

    # Should show exactly 3 peers with status "pinned"
    # Peers should be from different organizations (hrdag, backup, cross-org)
    ```

14. **Verify packaged commit structure**:
    ```bash
    docker exec archival-hrdag-api ls -lh /staging/commit_*/

    # Should show:
    # - *_aa, *_ab, ... (tar chunks, ~50MB each)
    # - *.par2 (par2 index)
    # - *.vol00+NN.par2 (par2 parity)
    # - manifest.json (with Ed25519 signature, all file metadata)
    # - manifest.json.ots (OpenTimestamps proof)
    # Total: ~24 files
    ```

15. **Verify OpenTimestamps submission**:
    ```bash
    curl -s -X POST http://localhost:8001/archive/ots-upgrade | jq '.'

    # Should show OTS status:
    # - "pending" initially (Bitcoin confirmation takes hours)
    # - Check again after 6-24 hours for "confirmed"
    ```

16. **Test role-based allocation**:
    ```bash
    # Upload from different orgs and verify replicas are on different nodes
    # HRDAG upload should replicate to: hrdag-nas, org3 (backup), org5 (cross-org)
    # Org2 upload should replicate to: org2-node, org3 (backup), org5 (cross-org)
    ```

17. **Check MinIO storage**:
    ```bash
    open http://localhost:9001  # MinIO web console
    # Login: minioadmin / minioadmin123
    # Should see "archival" bucket with commits/{commit_id}/ directories
    ```

---

## Verification Checklist

After implementation, confirm:

- [ ] 5 UI instances accessible at http://localhost:3001-3005
- [ ] 5 API instances respond at http://localhost:8001-8005
- [ ] Keys directory contains 10 files (5 signing keys + 5 encryption keys)
- [ ] Config directory contains 6 files (5 org TOMLs + 1 CCS YAML)
- [ ] CCS config has real peer IDs populated (not empty strings)
- [ ] Peer IDs match between CCS config and cluster `/id` endpoints
- [ ] Upload → Catalog → Archive workflow completes without errors
- [ ] Database commits table shows real merkle_root (64 hex chars)
- [ ] Database commits table shows real commit_cid (bafybei...)
- [ ] Staging contains packaged commits: chunks, par2, manifest.json
- [ ] manifest.json contains valid Ed25519 signature (88 base64 chars)
- [ ] manifest.json contains per-file metadata with merkle_proof inline
- [ ] manifest.json.ots file exists and is valid OTS proof
- [ ] **IPFS cluster shows exactly 3 replicas per commit_cid** (not 2, not 4-5)
- [ ] Replicas are on different nodes (check role tags match allocation strategy)
- [ ] MinIO console shows uploaded commits (if S3 backup enabled)
- [ ] No errors in docker logs: `docker compose logs -f`
- [ ] Cluster peers all show "trusted" status: `curl http://localhost:9091/peers | jq`

---

## Trade-offs: Local Dev vs Production

### Simplifications

1. **Keys**: Stored in plaintext files (production uses encrypted USB drives, never on disk)
2. **Database**: Single shared PostgreSQL (production has per-org isolation)
3. **Network**: Docker bridge (production uses Headscale/WireGuard VPN)
4. **Batch size**: 100 MB (production uses 1-5 GB)
5. **Filelister**: Simplified scan (production uses parallel GNU find with staging tables)
6. **S3**: MinIO mock (production uses real rclone → SpaceTime)

### Production Parity Achieved

- Full cryptographic operations (XChaCha20-Poly1305 encryption, LZ4 compression)
- Real BLAKE3 content hashing
- Real Merkle tree construction with proofs
- Real Ed25519 signatures
- Real OpenTimestamps (Bitcoin anchoring via public calendars)
- Real IPFS cluster uploads with 3-replica replication
- Role-based allocation (primary/backup/cross-org tags)
- Profile-based CCS configuration (matching production org setup)
- Decoupled workflow (UI stages → API triggers → ntx orchestrates)
- **Commit packaging (tar+split+par2) matching v2 architecture**

---

## Replication Strategy Details

**Goal**: Ensure exactly 3 replicas per commit across different organizations

**Configuration**:
```yaml
# docker-compose.yml per node:
environment:
  - CLUSTER_REPLICATIONFACTORMIN=3
  - CLUSTER_REPLICATIONFACTORMAX=3
  - CLUSTER_DISABLEREPINNING=false
  - CLUSTER_INFORMER_TAGS_TAGS={"role":"primary","org":"hrdag"}
```

**How It Works**:
1. When HRDAG uploads via `ccs add --profile hrdag`:
   - CCS reads profile config: `primary: hrdag-nas`
   - ntx calls `ipfs.upload(commit_dir, profile="hrdag", ccs_config)`
   - CCS determines explicit allocation: `[hrdag-nas-peer-id]`
   - Sends to cluster REST API: `POST /add?allocations=12D3KooW...`

2. Cluster allocator (with `replication_factor_min=3, max=3`):
   - Pins to hrdag-nas (explicit allocation)
   - Queries all peers for informer tags
   - Filters by role tags:
     - Needs 2 more replicas
     - Prefers `role=backup` for replica 2
     - Prefers `role=cross-org` for replica 3
     - Avoids same org (uses `org` tag)
   - Selects org3-node (backup) and org5-node (cross-org)
   - Pins to all 3 nodes

3. Result: 3 replicas across 3 different organizations
   - Redundancy: Survives 2 node failures
   - Privacy: Data not on public IPFS network
   - Trust: All nodes within trusted NGO network

**Verification**:
```bash
curl http://localhost:9091/pins/<commit_cid> | jq '.peer_map | length'
# Should return: 3

curl http://localhost:9091/pins/<commit_cid> | jq '.peer_map | keys'
# Should return: ["12D3KooW...", "12D3KooW...", "12D3KooW..."]
# Three different peer IDs
```

---

## Summary

This plan transforms the prototype into a production-grade 5-organization archival system with:
- **8-stage ntx v2 pipeline** with commit packaging (tar+split+par2)
- **5 separate org instances** (HRDAG + 4 partners) demonstrating realistic multi-tenant deployment
- **Real cryptography** (encryption, compression, signatures, Merkle trees, OpenTimestamps)
- **IPFS cluster integration** via CCS with role-based replication ensuring exactly 3 replicas
- **Decoupled architecture** (UI stages → API triggers → ntx orchestrates IPFS+S3)
- **Docker Compose simplicity** for easy local development

**Implementation time**: ~8 days (1-2 days per phase + 2 days testing)

**Next steps**: Approve plan and begin Phase 1 (Foundation)

---

## Changes from v1 Draft

This document was amended to align with ntx v2 architecture. Key changes:

| Section | v1 (Original) | v2 (Amended) |
|---------|---------------|--------------|
| Stage 1 query | `cid_enc IS NULL` | `commit_id IS NULL` |
| Stage 5 | Write Sidecars (*.sidecar files) | Package (tar+split+par2) |
| Stage 6 manifest | References external sidecars | All per-file metadata inline |
| Stage 8 upload | Per-file CIDs tracked | Single commit_cid per commit |
| Output structure | Hundreds of .enc/.sidecar files | ~24 files (chunks + par2 + manifest) |
| DB columns | `cid_enc`, `cid_sidecar` per file | `commit_cid` per commit only |
| Backend modules | `upload.py`, `rclone.py` | `ipfs.py`, `s3.py` |
| Dockerfile | No par2 | Includes par2 package |

**Why v2?** IPFS cluster multipart uploads stall with >300 files. The v2 packaging
approach reduces files-per-upload from hundreds to ~24, solving this issue while
adding par2 error correction for data durability.

See `ntx/docs/design-v2-commit-packaging.md` for full design rationale.

---

## Questions for Author

1. **ntx v2 migration**: The ntx codebase is undergoing a v2 restructuring (see `ntx/TODO.md`).
   This should stabilize by Monday evening. Should this local dev environment wait for v2,
   or proceed with current ntx and plan to update later?

2. **filelister integration**: The plan mentions simplified filelister-like scanning.
   Should we use actual filelister with `--path` flag (per `ntx/docs/architecture-multi-source-ingest.md`),
   or keep a simplified implementation for local dev?

3. **Database schema**: ntx v2 drops `cid_enc`, `cid_sidecar`, `encrypted_size` columns
   from paths table (see `ntx/TODO.md` Phase 1).

4. **PostgreSQL topology**: The prototype uses a single shared PostgreSQL instance.
   In production, each organization decides where to run their PostgreSQL—on `ben` or
   locally. We don't yet know what to recommend (depends on `ben`'s latency, which we
   won't know for months). How should the prototype model this—5 separate databases?
