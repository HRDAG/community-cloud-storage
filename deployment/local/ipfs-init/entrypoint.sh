#!/bin/sh
set -e

# Initialize IPFS if not already initialized
if [ ! -f "/data/ipfs/config" ]; then
    ipfs init --profile=server

    # Disable AutoConf for private network
    ipfs config --json AutoConf.Enabled false

    # Clear auto placeholders for private network
    ipfs config --json Bootstrap '[]'
    ipfs config --json DNS.Resolvers '{}'
    ipfs config --json Routing.DelegatedRouters '[]'
    ipfs config --json Ipns.DelegatedPublishers '[]'

    # Listen on all interfaces for cluster access
    ipfs config Addresses.API /ip4/0.0.0.0/tcp/5001
    ipfs config Addresses.Gateway /ip4/0.0.0.0/tcp/8080
fi

# Start IPFS daemon
exec ipfs daemon --migrate=true --agent-version-suffix=docker
