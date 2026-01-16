# 🚀 Start Here: Local Archival Pipeline

Quick start guide for running the complete archival pipeline locally.

## What Is This?

A **local development environment** that emulates the HRDAG archival system with:
- PostgreSQL database
- 3-node IPFS cluster (private network)
- Archival API (FastAPI)
- Web UI (Vue.js) - **Dropbox-like interface**

## ⚡ Quick Start (3 commands)

```bash
# 1. Setup (one time)
cd deployment/local && ./setup.sh

# 2. Start everything
docker compose up -d

# 3. Open web UI
open http://localhost:3000
```

Wait ~30 seconds for services to start, then use the web interface to:
1. Drag & drop files to upload
2. Click "Run Catalog" to scan files
3. Click "Run Archive" to create commits

## 🧪 Test It Works

```bash
cd deployment/local
./test-workflow.sh
```

Expected output: "✅ All systems operational!"

## 📚 Documentation

See **[README.md](README.md)** for complete documentation, architecture details, and troubleshooting.

## ⚠️ Important Notes

### This is a PROTOTYPE

| Feature | Status |
|---------|--------|
| ✅ File upload | Working |
| ✅ Database catalog | Working |
| ✅ 3-node IPFS cluster | Working |
| ✅ Web UI | Working |
| ⚠️ Archival | **Mock CIDs only** |
| ❌ Encryption | Not implemented |
| ❌ OpenTimestamps | Not implemented |
| ❌ Ed25519 signatures | Not implemented |

### For Production Integration

See [README.md](README.md) "Production Integration" section to integrate with:
- Real ntx (encryption, timestamps, signatures)
- Real filelister (parallel scanning)
- Real CCS uploads (actual IPFS storage)

## 🆘 Need Help?

```bash
# Check what's running
docker compose ps

# View logs
docker compose logs -f

# Reset everything (⚠️ deletes all data)
docker compose down -v
```

## 🎯 What to Do Next

1. **Try the workflow** - Upload files via http://localhost:3000
2. **Explore the API** - http://localhost:8000/docs
3. **Query the database** - `docker exec -it archival-postgres psql -U archival -d scottfiles`
4. **Check the cluster** - `curl http://localhost:9094/peers | jq`

---

**Ready to start?** Run `./setup.sh` and you're off! 🚀
