# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/community_cloud_storage/operations.py

"""
CCS Operations

High-level operations for interacting with the CCS cluster.
These functions use the config to determine allocation and return typed results.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from community_cloud_storage.cluster_api import ClusterClient, ClusterAPIError
from community_cloud_storage.config import CCSConfig
from community_cloud_storage.types import (
    AddResult,
    CIDEntry,
    PeerInfo,
    PinStatus,
    RC_SUCCESS,
    RC_FAILED,
    RC_CONFIG_ERROR,
)


class CCSError(Exception):
    """Base exception for CCS operations."""
    pass


class ConfigError(CCSError):
    """Raised when config is missing required fields."""
    pass


class AllocationError(CCSError):
    """Raised when allocation cannot be determined."""
    pass


def _get_client(config: CCSConfig, host: str = None) -> ClusterClient:
    """Create a ClusterClient from config."""
    if host is None:
        host = config.default_node
    if host is None:
        raise ConfigError("No host specified and no default_node in config")

    node = config.get_node(host)
    if node:
        host = node.host

    auth = config.auth.to_tuple() if config.auth else None
    return ClusterClient(host=host, port=9094, basic_auth=auth)


def _get_allocations(profile: str, config: CCSConfig) -> list[str]:
    """
    Determine explicit allocations for a profile.

    Returns peer IDs for: [primary, backup]
    The cluster allocator will pick additional replicas up to replication_max.
    """
    # Get primary for this profile
    primary = config.get_primary_for_profile(profile)
    if not primary:
        raise AllocationError(f"Profile '{profile}' not found in config")
    if not primary.peer_id:
        raise AllocationError(f"Primary node '{primary.name}' has no peer_id in config")

    # Get backup node
    backup = config.get_backup_node()
    if not backup:
        raise AllocationError("No backup_node configured")
    if not backup.peer_id:
        raise AllocationError(f"Backup node '{backup.name}' has no peer_id in config")

    return [primary.peer_id, backup.peer_id]


def add(
    path: Path,
    profile: str,
    config: CCSConfig,
    recursive: bool = True,
    host: str = None,
) -> AddResult:
    """
    Add file or directory to the cluster with explicit allocations.

    The content is added to IPFS and pinned to:
    1. The profile's primary node
    2. The backup node
    3. Additional replicas chosen by the cluster allocator (up to replication_max)

    Args:
        path: Path to file or directory to add
        profile: Profile name (e.g., "hrdag") - determines primary node
        config: CCSConfig with auth, profiles, and nodes
        recursive: If True and path is directory, add recursively (default True)
        host: Override which cluster node to talk to (default: config.default_node)

    Returns:
        AddResult with root CID, all entries, and allocation info.
        Never raises exceptions - check returncode for success:
        - 0 (RC_SUCCESS): All entries added successfully
        - 2 (RC_FAILED): No entries added (API/network error)
        - 3 (RC_CONFIG_ERROR): Configuration error (missing profile, peer_id, etc.)
    """
    # Default to profile's primary node - enables local=true to include it in allocations
    # Fall back to config.default_node if profile not found (will error later)
    profile_config = config.profiles.get(profile)
    profile_primary = profile_config.primary if profile_config else None
    target_host = host or profile_primary or config.default_node

    # Check path exists
    if not path.exists():
        return AddResult(
            root_cid="",
            root_path=str(path),
            entries=[],
            allocations=[],
            profile=profile,
            added_at=datetime.now(timezone.utc),
            cluster_host=target_host or "",
            returncode=RC_FAILED,
            error=f"Path not found: {path}",
        )

    # Determine allocations - config errors
    try:
        allocations = _get_allocations(profile, config)
    except (ConfigError, AllocationError) as e:
        return AddResult(
            root_cid="",
            root_path=str(path),
            entries=[],
            allocations=[],
            profile=profile,
            added_at=datetime.now(timezone.utc),
            cluster_host=target_host or "",
            returncode=RC_CONFIG_ERROR,
            error=str(e),
        )

    # Get client - config errors
    try:
        client = _get_client(config, target_host)
    except ConfigError as e:
        return AddResult(
            root_cid="",
            root_path=str(path),
            entries=[],
            allocations=allocations,
            profile=profile,
            added_at=datetime.now(timezone.utc),
            cluster_host=target_host or "",
            returncode=RC_CONFIG_ERROR,
            error=str(e),
        )

    # Add to cluster with allocations
    try:
        entries_raw = client.add(
            path,
            recursive=recursive,
            name=path.name,
            allocations=allocations,
        )
    except ClusterAPIError as e:
        return AddResult(
            root_cid="",
            root_path=str(path),
            entries=[],
            allocations=allocations,
            profile=profile,
            added_at=datetime.now(timezone.utc),
            cluster_host=target_host,
            returncode=RC_FAILED,
            error=str(e),
        )
    except Exception as e:
        # Catch any unexpected errors
        return AddResult(
            root_cid="",
            root_path=str(path),
            entries=[],
            allocations=allocations,
            profile=profile,
            added_at=datetime.now(timezone.utc),
            cluster_host=target_host,
            returncode=RC_FAILED,
            error=f"Unexpected error: {e}",
        )

    # Validate entries_raw is not empty (safety net)
    # This should never happen after Step 2 error detection, but provides defense in depth
    if not entries_raw:
        return AddResult(
            root_cid="",
            root_path=str(path),
            entries=[],
            allocations=allocations,
            profile=profile,
            added_at=datetime.now(timezone.utc),
            cluster_host=target_host,
            returncode=RC_FAILED,
            error="No entries returned from cluster (possible server error)",
        )

    # Root is the last entry from IPFS
    root_cid = entries_raw[-1].get("cid", "") if entries_raw else ""

    # Convert raw entries to CIDEntry objects, marking the root
    entries = []
    for raw in entries_raw:
        cid = raw.get("cid", "")
        entries.append(CIDEntry(
            path=raw.get("name", ""),
            cid=cid,
            size=raw.get("size", 0),
            is_root=(cid == root_cid),
        ))

    return AddResult(
        root_cid=root_cid,
        root_path=str(path),
        entries=entries,
        allocations=allocations,
        profile=profile,
        added_at=datetime.now(timezone.utc),
        cluster_host=target_host,
        returncode=RC_SUCCESS,
        error=None,
    )


def status(
    cid: str,
    config: CCSConfig,
    host: str = None,
) -> PinStatus:
    """
    Get status of a pinned CID.

    Args:
        cid: The CID to check
        config: CCSConfig with auth
        host: Override which cluster node to talk to

    Returns:
        PinStatus with replication info across all peers

    Raises:
        ClusterAPIError: If cluster API returns an error
    """
    client = _get_client(config, host)
    raw = client.pin_status(cid)
    return PinStatus.from_cluster_status(raw)


def peers(
    config: CCSConfig,
    host: str = None,
) -> list[PeerInfo]:
    """
    List all peers in the cluster.

    Args:
        config: CCSConfig with auth
        host: Override which cluster node to talk to

    Returns:
        List of PeerInfo for each cluster peer

    Raises:
        ClusterAPIError: If cluster API returns an error
    """
    client = _get_client(config, host)

    # Get peers from /peers endpoint
    response = client._request("GET", "/peers")

    # Parse NDJSON response
    results = []
    for line in response.text.strip().split('\n'):
        if line:
            import json
            peer_data = json.loads(line)
            results.append(PeerInfo.from_cluster_peer(peer_data))

    return results


def ls(
    config: CCSConfig,
    host: str = None,
) -> list[PinStatus]:
    """
    List all pinned CIDs in the cluster.

    Args:
        config: CCSConfig with auth
        host: Override which cluster node to talk to

    Returns:
        List of PinStatus for each pinned CID

    Raises:
        ClusterAPIError: If cluster API returns an error
    """
    client = _get_client(config, host)
    raw_pins = client.pins()

    return [PinStatus.from_cluster_status(p) for p in raw_pins]
