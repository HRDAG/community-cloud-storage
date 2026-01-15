# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/community_cloud_storage/__init__.py

"""
Community Cloud Storage (CCS) Library

A Python library for managing files in a private IPFS cluster with
automatic replication across organizations.

Basic usage:
    from community_cloud_storage import add, load_config

    config = load_config()
    result = add("/path/to/file", profile="hrdag", config=config)
    print(result.root_cid)

For more control:
    from community_cloud_storage.config import CCSConfig, load_config
    from community_cloud_storage.types import AddResult, CIDEntry
    from community_cloud_storage.operations import add, status, peers
"""

# Config
from community_cloud_storage.config import (
    CCSConfig,
    ClusterAuth,
    NodeConfig,
    ProfileConfig,
    load_config,
    save_config,
)

# Types
from community_cloud_storage.types import (
    AddResult,
    CIDEntry,
    PeerInfo,
    PeerPinStatus,
    PinStatus,
    RC_SUCCESS,
    RC_PARTIAL,
    RC_FAILED,
    RC_CONFIG_ERROR,
)

# Operations
from community_cloud_storage.operations import (
    add,
    ls,
    peers,
    status,
    AllocationError,
    CCSError,
    ConfigError,
)

# CLI (for backward compatibility)
from community_cloud_storage.cli import cli

__all__ = [
    # Config
    "CCSConfig",
    "ClusterAuth",
    "NodeConfig",
    "ProfileConfig",
    "load_config",
    "save_config",
    # Types
    "AddResult",
    "CIDEntry",
    "PeerInfo",
    "PeerPinStatus",
    "PinStatus",
    # Return codes
    "RC_SUCCESS",
    "RC_PARTIAL",
    "RC_FAILED",
    "RC_CONFIG_ERROR",
    # Operations
    "add",
    "ls",
    "peers",
    "status",
    # Errors
    "AllocationError",
    "CCSError",
    "ConfigError",
    # CLI
    "cli",
]
