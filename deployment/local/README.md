# Local Archival Pipeline Prototype

Complete local development environment for the community archival system, including PostgreSQL, 3-node IPFS Cluster, archival API, and web UI.

> **⚠️ IMPORTANT**: This is a **prototype for development and testing**. It uses **mock CIDs** and does not include production features like encryption, OpenTimestamps, or Ed25519 signatures. See [Limitations](#limitations) for details.

## Quick Start

New here? Start with **[START-HERE.md](START-HERE.md)** for a 3-command setup.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│         Web UI + API (Single Container)             │
│  http://localhost:8000                              │
│  - Vue.js UI with drag & drop upload               │
│  - Browse archived files and commits                │
│  - FastAPI backend serving both UI and API          │
│  - Accept uploads and run archival workflow         │
└─────────────┬───────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────┐
│  PostgreSQL (scottfiles database)                   │
│  localhost:5432                                     │
│  - paths table (filelister schema)                  │
│  - commits table (ntx schema)                       │
└─────────────────────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────┐
│  CCS Cluster (3 nodes)                              │
│  - node1: localhost:9094 (test-org1 primary)       │
│  - node2: localhost:9095 (shared backup)           │
│  - node3: localhost:9098 (test-org2 primary)       │
│  Replication: min=2, max=3                         │
└─────────────────────────────────────────────────────┘
```

## What This Prototype Includes

### ✅ Included (Functional)
- **PostgreSQL**: Full filelister + ntx schema
- **3-node IPFS Cluster**: Private network with automatic replication
- **Archival API**: REST API for upload, catalog, archive
- **Web UI**: Dropbox-like interface for file management
- **File Upload**: Drag & drop or browse
- **Cataloging**: Scan filesystem and add to database
- **Simplified Archival**: Mock commit creation (for demonstration)

### ⚠️ Simplified (Prototype Only)
- **ntx archival**: Mock implementation (no encryption, signatures, or OpenTimestamps)
- **filelister**: Simplified scan (no parallel processing or advanced filtering)
- **CCS integration**: Mock CIDs (not actual IPFS upload)

### ❌ Not Included (Production Only)
- **Encryption**: XChaCha20-Poly1305
- **Merkle trees**: Cryptographic binding of content + metadata
- **Ed25519 signatures**: Organizational attribution
- **OpenTimestamps**: Bitcoin-anchored existence proofs
- **S3 backup**: Redundant storage
- **Real IPFS upload**: Actual content-addressed storage

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- Node.js 20+ (for web UI development)
- OpenSSL (for secret generation)

### 2. Setup

```bash
cd deployment/local
./setup.sh
```

This will:
- Generate IPFS cluster secrets
- Generate swarm key for private IPFS network
- Install web UI dependencies
- Create `.env` file

### 3. Start the Stack

```bash
# From community-cloud-storage directory
docker compose up -d
```

Wait ~30 seconds for all services to start.

### 4. Access the UI

Open your browser to: **http://localhost:8000**

### 5. Test the Workflow

1. **Upload Files**: Drag & drop files into the web UI
2. **Run Catalog**: Click "Run Catalog" to scan uploaded files into database
3. **Check Status**: See pending files count update
4. **Run Archive**: Click "Run Archive" to create a commit and mock archive
5. **View Files**: Browse cataloged files, see CIDs and commit IDs

## API Endpoints

Base URL: `http://localhost:8000`

### Status & Info
- `GET /` - API health check
- `GET /status` - System status (pending files, commits)
- `GET /files?limit=100&offset=0&archived_only=false` - List files
- `GET /commits?limit=50` - List commits

### Actions
- `POST /upload` - Upload file (multipart/form-data)
- `POST /catalog` - Run filelister scan
- `POST /archive?size_limit_gb=0.1&dry_run=false` - Run archival

Example:
```bash
# Upload a file
curl -X POST http://localhost:8000/upload \
  -F "file=@test.pdf"

# Run catalog
curl -X POST http://localhost:8000/catalog

# Check status
curl http://localhost:8000/status | jq

# Run archive (dry run)
curl -X POST http://localhost:8000/archive?dry_run=true | jq

# Run archive (real)
curl -X POST http://localhost:8000/archive | jq
```

## Database Access

Connect to PostgreSQL:

```bash
# Using psql
docker exec -it archival-postgres psql -U archival -d scottfiles

# Example queries
SELECT COUNT(*) FROM paths WHERE commit_id IS NULL;  -- Pending files
SELECT * FROM commits ORDER BY sequence DESC LIMIT 5;  -- Recent commits
SELECT encode(path, 'escape') as path, size, commit_id FROM paths LIMIT 10;
```

## IPFS Cluster Access

Check cluster status:

```bash
# Node 1 peer ID
curl http://localhost:9094/id | jq

# List all cluster peers
curl http://localhost:9094/peers | jq

# Check pins
curl http://localhost:9094/pins | jq
```

## Directory Structure

```
local-dev/
├── README.md                    # This file
├── setup.sh                     # Setup script
├── init-db/
│   └── 01-create-schema.sql    # PostgreSQL schema
├── ccs-config/
│   ├── cluster-secret.txt      # Generated by setup.sh
│   └── swarm.key               # Generated by setup.sh
├── archival-api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                  # FastAPI application
└── web-ui/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.js
        └── App.vue             # Vue.js app
```

## Development

### Run API in Development Mode

```bash
cd ../../api

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://archival:dev-password-change-in-production@localhost:5432/scottfiles"
export UPLOAD_DIR="/tmp/uploads"
export STAGING_DIR="/tmp/staging"

# Run API
python -m uvicorn app:app --reload --port 8000
```

### Run Web UI in Development Mode

```bash
cd ../../ui

# Install dependencies
npm install

# Run dev server (UI only, API must be running separately)
npm run dev
```

Access at: http://localhost:5173 (API at http://localhost:8000)

## Stopping the Stack

```bash
# Stop all services
docker compose down

# Stop and remove volumes (⚠️ deletes all data)
docker compose down -v
```

## Troubleshooting

### Services won't start

Check logs:
```bash
docker compose logs -f
```

### Database connection errors

Ensure PostgreSQL is healthy:
```bash
docker compose ps postgres
```

### IPFS cluster not forming

Check cluster logs:
```bash
docker logs node1-cluster
docker logs node2-cluster
docker logs node3-cluster
```

### Web UI can't connect to API

Check CORS settings in `archival-api/app.py` and ensure API is running:
```bash
curl http://localhost:8000
```

## Next Steps: Production Integration

To integrate with real production tools:

### 1. Real filelister Integration

Replace simplified catalog with actual filelister:

```python
# In archival-api/app.py
import subprocess
subprocess.run([
    "filelister", "scan",
    "--config", "/etc/filelister/config.toml"
])
```

### 2. Real ntx Integration

Replace mock archive with actual ntx:

```python
# In archival-api/app.py
import subprocess
subprocess.run([
    "ntx", "scan",
    "--config", "/etc/ntx/ntx.toml"
])
```

### 3. Real CCS Upload

Use actual CCS library for IPFS upload:

```python
from community_cloud_storage.operations import add as ccs_add
result = ccs_add(commit_dir, profile="hrdag", config=ccs_config)
```

### 4. Add Encryption

Integrate XChaCha20-Poly1305 encryption from ntx.

### 5. Add OpenTimestamps

Integrate Bitcoin anchoring from ntx.

### 6. Add Ed25519 Signatures

Sign commits with organizational keys from ntx.

## Architecture Comparison: Prototype vs Production

| Component | Prototype | Production |
|-----------|-----------|------------|
| Database | PostgreSQL (Docker) | PostgreSQL (scott) |
| Filelister | Simplified scan | Full parallel scan with exclusions |
| ntx | Mock commits | Full: encryption, Merkle trees, OTS, signatures |
| CCS | Mock CIDs | Real IPFS cluster with replication |
| Backup | None | S3 via rclone |
| Network | Docker bridge | Tailscale VPN |
| Keys | None | LUKS-encrypted USB drive |
| Monitoring | None | Prometheus, hrdag-monitor |

## Resources

- [community-cloud-storage](../) - CCS library and CLI
- [filelister](../../filelister/) - Filesystem cataloging
- [ntx](../../ntx/) - Archival with cryptographic proofs
- [server-documentation](../../server-documentation/) - Infrastructure docs

## License

GPL-2 or newer (same as parent project)
