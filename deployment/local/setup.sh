#!/bin/bash
# Setup script for local archival pipeline prototype

set -e

echo "🚀 Setting up local archival pipeline..."
echo ""

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "❌ Docker is required but not installed. Aborting." >&2; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "❌ Docker Compose is required but not installed. Aborting." >&2; exit 1; }

echo "✅ Prerequisites check passed"
echo ""

# Generate CCS cluster secrets
echo "🔑 Generating CCS cluster secrets..."
mkdir -p ccs-config

# Generate cluster secret (32 random bytes as hex)
if [ ! -f ccs-config/cluster-secret.txt ]; then
    openssl rand -hex 32 > ccs-config/cluster-secret.txt
    echo "✅ Generated cluster secret"
else
    echo "ℹ️  Using existing cluster secret"
fi

# Generate IPFS swarm key
if [ ! -f ccs-config/swarm.key ]; then
    echo "/key/swarm/psk/1.0.0/" > ccs-config/swarm.key
    echo "/base16/" >> ccs-config/swarm.key
    openssl rand -hex 32 >> ccs-config/swarm.key
    echo "✅ Generated IPFS swarm key"
else
    echo "ℹ️  Using existing swarm key"
fi

# Create .env file with cluster secret
CLUSTER_SECRET=$(cat ccs-config/cluster-secret.txt)
echo "CLUSTER_SECRET=$CLUSTER_SECRET" > .env
echo "✅ Created .env file"
echo ""

# Build web UI
echo "📦 Building web UI..."
cd ../../ui
if [ ! -d node_modules ]; then
    npm install
fi
cd ../deployment/local
echo "✅ Web UI dependencies installed"
echo ""

echo "✨ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Start the stack:"
echo "   docker compose up -d"
echo ""
echo "2. Wait for services to start (~30 seconds)"
echo ""
echo "3. Open web UI:"
echo "   http://localhost:3000"
echo ""
echo "4. Check API health:"
echo "   curl http://localhost:8000"
echo ""
echo "5. Check IPFS cluster:"
echo "   curl http://localhost:9094/id"
echo ""
