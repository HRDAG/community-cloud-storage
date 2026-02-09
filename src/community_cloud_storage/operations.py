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

import requests

from community_cloud_storage.cluster_api import ClusterClient, ClusterAPIError, IPFSClient
from community_cloud_storage.config import CCSConfig
from community_cloud_storage.types import (
    AddResult,
    BrokenPin,
    CIDEntry,
    EnsurePinsResult,
    HealthReport,
    NodeHealth,
    PeerInfo,
    PinStatus,
    RepairResult,
    RC_SUCCESS,
    RC_PARTIAL,
    RC_FAILED,
    RC_CONFIG_ERROR,
    RC_REPAIR_CLEAN,
    RC_REPAIR_FIXED,
    RC_REPAIR_LOST,
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


def _get_dag_size(gateway_host: str, cid: str) -> int | None:
    """Get total DAG size for a CID via IPFS gateway dag-json.

    Queries the gateway's dag-json format which includes Tsize
    (cumulative DAG size) for each link in the root node.

    Args:
        gateway_host: Gateway host (IP or hostname), port 8080 assumed
        cid: IPFS CID to measure

    Returns:
        Total size in bytes, or None if lookup fails
    """
    try:
        resp = requests.get(
            f"http://{gateway_host}:8080/ipfs/{cid}?format=dag-json",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        links = data.get("Links", [])
        return sum(link.get("Tsize", 0) for link in links)
    except Exception:
        return None


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
            replica_count=None,
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
            replica_count=None,
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
            replica_count=None,
        )

    # Calculate content size for metadata
    if path.is_file():
        content_size = path.stat().st_size
    else:
        content_size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    # Add to cluster with allocations
    try:
        entries_raw = client.add(
            path,
            recursive=recursive,
            name=path.name,
            allocations=allocations,
            metadata={"org": profile, "size": str(content_size)},
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
            replica_count=None,
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
            replica_count=None,
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
            replica_count=None,
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

    # Query pin status to verify replication
    # Required allocations [primary, backup] were satisfied by cluster allocator
    # Now verify they actually pinned and check total replication
    try:
        pin_status = status(root_cid, config, target_host)

        # Check primary and backup status specifically
        primary_peer_id = allocations[0]  # First allocation is primary
        backup_peer_id = allocations[1]   # Second allocation is backup

        primary_status = pin_status.peer_map.get(primary_peer_id)
        backup_status = pin_status.peer_map.get(backup_peer_id)

        # Check for errors on primary or backup
        if primary_status and primary_status.status in ("error", "pin_error"):
            return AddResult(
                root_cid=root_cid,
                root_path=str(path),
                entries=entries,
                allocations=allocations,
                profile=profile,
                added_at=datetime.now(timezone.utc),
                cluster_host=target_host,
                returncode=RC_FAILED,
                error=f"Primary node pin failed: {primary_status.error or 'unknown error'}",
                replica_count=0,
            )

        if backup_status and backup_status.status in ("error", "pin_error"):
            return AddResult(
                root_cid=root_cid,
                root_path=str(path),
                entries=entries,
                allocations=allocations,
                profile=profile,
                added_at=datetime.now(timezone.utc),
                cluster_host=target_host,
                returncode=RC_FAILED,
                error=f"Backup node pin failed: {backup_status.error or 'unknown error'}",
                replica_count=0,
            )

        # Check if primary or backup still pending
        primary_pinned = primary_status and primary_status.status == "pinned"
        backup_pinned = backup_status and backup_status.status == "pinned"

        if not primary_pinned or not backup_pinned:
            # Primary or backup still pending (pinning, pin_queued, etc)
            pending = []
            if not primary_pinned:
                pending.append(f"primary ({primary_status.status if primary_status else 'unknown'})")
            if not backup_pinned:
                pending.append(f"backup ({backup_status.status if backup_status else 'unknown'})")

            returncode = RC_PARTIAL
            error = f"Pending: {', '.join(pending)} not yet pinned"
            replica_count = None  # Don't count until primary+backup complete
        else:
            # Both primary and backup pinned - count total replicas
            pinned_peers = [
                peer_id for peer_id, peer_status in pin_status.peer_map.items()
                if peer_status.status == "pinned"
            ]
            replica_count = len(pinned_peers)

            # Determine return code based on replica count
            # Required: primary + backup (2) - both pinned ✓
            # Desired minimum: 3 replicas
            # Desired maximum: 4 replicas (replication_max)
            if replica_count < 3:
                returncode = RC_PARTIAL
                error = f"Warning: Only {replica_count}/4 replicas pinned (primary+backup satisfied, but expected ≥3)"
            elif replica_count < 4:
                returncode = RC_SUCCESS
                error = f"Info: {replica_count}/4 replicas pinned (expected 4)"
            else:  # replica_count >= 4
                returncode = RC_SUCCESS
                error = None

    except ClusterAPIError as e:
        # Pin status check failed - content was added but we can't verify replication
        # Return partial with warning
        replica_count = None
        returncode = RC_PARTIAL
        error = f"Warning: Content added but could not verify replication: {e}"

    return AddResult(
        root_cid=root_cid,
        root_path=str(path),
        entries=entries,
        allocations=allocations,
        profile=profile,
        added_at=datetime.now(timezone.utc),
        cluster_host=target_host,
        returncode=returncode,
        error=error,
        replica_count=replica_count,
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


def _select_download_peer(
    pin_status: PinStatus,
    config: CCSConfig,
    profile: Optional[str] = None,
) -> str:
    """
    Select which peer to download from based on pin status and profile.

    Args:
        pin_status: Pin status with peer_map
        config: CCSConfig with nodes
        profile: Optional profile name (prefers primary)

    Returns:
        Host (IP or hostname) of selected peer from config

    Raises:
        CCSError: If no peers have pinned content
        ConfigError: If profile specified but not found
    """
    pinned_peers = [
        peer_id for peer_id, peer_status in pin_status.peer_map.items()
        if peer_status.status == "pinned"
    ]

    if not pinned_peers:
        raise CCSError(f"No peers have pinned CID {pin_status.cid}")

    # Prefer profile's primary node if specified
    if profile:
        primary_node = config.get_primary_for_profile(profile)
        if not primary_node:
            raise ConfigError(f"Profile '{profile}' not found in config")

        if primary_node.peer_id in pinned_peers:
            return primary_node.host

    # Fallback: use first pinned peer, look up host in config
    selected_peer_id = pinned_peers[0]
    for node_config in config.nodes.values():
        if node_config.peer_id == selected_peer_id:
            return node_config.host

    # Last resort: use peername from status (may not resolve)
    return pin_status.peer_map[selected_peer_id].peername


def get(
    cid: str,
    dest: Path,
    config: CCSConfig,
    profile: Optional[str] = None,
    host: str = None,
) -> None:
    """
    Download content from IPFS cluster by CID.

    Queries the cluster to find which peers have the content pinned,
    then downloads from a peer using the IPFS gateway.

    Args:
        cid: IPFS CID to retrieve
        dest: Destination path for downloaded content
        config: CCSConfig with auth and node information
        profile: Optional profile name (prefers profile's primary node)
        host: Override which cluster node to query for status

    Raises:
        ClusterAPIError: If CID not found or download fails
        ConfigError: If profile not found in config
        CCSError: If no peers have pinned content

    Examples:
        # Download using any available peer
        get("QmTEST", Path("output.txt"), config)

        # Download preferring hrdag's primary node
        get("QmTEST", Path("output.txt"), config, profile="hrdag")
    """
    pin_status = status(cid, config, host)
    download_host = _select_download_peer(pin_status, config, profile)

    # Check if CID is a directory by doing HEAD request
    base_url = f"http://{download_host}:8080/ipfs/{cid}"
    head_response = requests.head(base_url, allow_redirects=True)
    content_type = head_response.headers.get("Content-Type", "")

    # If directory (text/html response), use format=tar to get archive instead of HTML
    # If file, download directly without format parameter
    if "text/html" in content_type or "directory" in content_type:
        url = f"{base_url}?format=tar"
    else:
        url = base_url

    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def ensure_pins(
    profile: str,
    config: CCSConfig,
    host: str = None,
    dry_run: bool = False,
    progress_callback=None,
) -> EnsurePinsResult:
    """
    Ensure all pins include required allocations for a profile.

    Scans all cluster pins and re-pins any that are missing the profile's
    required peers (primary + backup).

    WARNING: Re-pinning REPLACES allocations. Cluster v1.1.5 reduces to
    replication_factor_min (2) allocations. Pins currently with 3 replicas
    will be reduced to 2 [primary, backup]. The cluster allocator may add
    a 3rd replica later.

    Args:
        profile: Profile name (e.g., "hrdag")
        config: CCSConfig with auth, profiles, and nodes
        host: Override which cluster node to talk to
        dry_run: If True, report what would change without modifying
        progress_callback: Optional callable(current, total, pin_name, action)

    Returns:
        EnsurePinsResult with counts and error details
    """
    import time

    allocations = _get_allocations(profile, config)
    required_set = set(allocations)

    client = _get_client(config, host)
    all_pins = client.pins()

    total = len(all_pins)
    already_correct = 0
    fixed = 0
    errors = 0
    error_details = []

    for i, pin_data in enumerate(all_pins):
        pin = PinStatus.from_cluster_status(pin_data)
        name = pin.name or ""

        if progress_callback:
            progress_callback(i + 1, total, name, "checking")

        current_allocs = set(pin.allocations)
        if required_set.issubset(current_allocs):
            already_correct += 1
            continue

        if dry_run:
            fixed += 1
            if progress_callback:
                progress_callback(i + 1, total, name, "would fix")
            continue

        try:
            client.pin(pin.cid, name=name, allocations=allocations)
            fixed += 1
            if progress_callback:
                progress_callback(i + 1, total, name, "fixed")
            time.sleep(0.05)
        except (ClusterAPIError, Exception) as e:
            errors += 1
            error_details.append({
                "cid": pin.cid,
                "name": name,
                "error": str(e),
            })

    return EnsurePinsResult(
        total=total,
        already_correct=already_correct,
        fixed=fixed,
        errors=errors,
        dry_run=dry_run,
        required_peers=allocations,
        error_details=error_details,
    )


def health(
    config: CCSConfig,
    host: str = None,
) -> HealthReport:
    """
    Get cluster health summary.

    Queries peers and all pin statuses, aggregates per-node health,
    and determines overall cluster status.

    Args:
        config: CCSConfig with auth
        host: Override which cluster node to talk to

    Returns:
        HealthReport with overall status, per-node stats, and pin errors

    Raises:
        ClusterAPIError: If cluster API is unreachable
    """
    # 1. Get peer list + online status
    peer_list = peers(config, host)

    # Build node map: peer_id -> NodeHealth
    node_map = {}
    for peer in peer_list:
        node_map[peer.peer_id] = NodeHealth(
            name=peer.name,
            peer_id=peer.peer_id,
            online=peer.error is None,
            error=peer.error,
        )

    # 2. Get all pin statuses
    client = _get_client(config, host)
    raw_pins = client.pins()
    all_pins = [PinStatus.from_cluster_status(p) for p in raw_pins]

    # 3. Aggregate per-node counts from each pin's peer_map
    pin_errors = []
    for pin in all_pins:
        for peer_id, peer_status in pin.peer_map.items():
            node = node_map.get(peer_id)
            if node is None:
                # Peer in pin map but not in /peers (shouldn't happen normally)
                continue

            if peer_status.status == "pinned":
                node.pinned += 1
            elif peer_status.status == "remote":
                node.remote += 1
            elif peer_status.status in ("pin_error", "error"):
                node.pin_errors += 1
                pin_errors.append({
                    "cid": pin.cid[:20] + "...",
                    "node": node.name,
                    "error": peer_status.error or "unknown error",
                })

    # 4. Determine overall status
    nodes = list(node_map.values())
    peers_online = sum(1 for n in nodes if n.online)
    peers_total = len(nodes)

    if peers_online < peers_total:
        overall_status = "error"
    elif pin_errors:
        overall_status = "degraded"
    else:
        overall_status = "ok"

    return HealthReport(
        status=overall_status,
        checked_at=datetime.now(timezone.utc),
        peers_total=peers_total,
        peers_online=peers_online,
        pins_total=len(all_pins),
        nodes=nodes,
        pin_errors=pin_errors,
    )


def repair(
    config: CCSConfig,
    host: str = None,
    dry_run: bool = False,
) -> RepairResult:
    """Detect and recover broken pins in the cluster.

    Scans all pins for error statuses, classifies each as recoverable
    (data exists on at least one node) or lost (no node has the data),
    and triggers cluster recovery for recoverable pins.

    Uses POST /pins/{cid}/recover which retries using existing allocations,
    preserving name, metadata, and allocations automatically.

    Args:
        config: CCSConfig with auth
        host: Override which cluster node to talk to
        dry_run: If True, report what would be recovered without modifying

    Returns:
        RepairResult with counts and broken pin details
    """
    client = _get_client(config, host)
    raw_pins = client.pins()

    error_statuses = {"pin_error", "error"}
    healthy_statuses = {"pinned", "remote", "pinning", "pin_queued"}

    broken_pins = []
    for pin in raw_pins:
        peer_map = pin.get("peer_map", {})

        error_nodes = []
        healthy_nodes = []
        for peer_id, peer_info in peer_map.items():
            st = peer_info.get("status", "")
            if st in error_statuses:
                error_nodes.append({
                    "node": peer_info.get("peername", peer_id),
                    "error": peer_info.get("error") or "unknown error",
                })
            elif st in healthy_statuses:
                healthy_nodes.append(peer_info.get("peername", peer_id))

        if not error_nodes:
            continue

        bp = BrokenPin(
            cid=pin["cid"],
            name=pin.get("name") or None,
            recoverable=len(healthy_nodes) > 0,
            error_nodes=error_nodes,
            healthy_nodes=healthy_nodes,
        )
        broken_pins.append(bp)

    # Attempt recovery for recoverable pins
    recovered = 0
    recover_errors = 0
    for bp in broken_pins:
        if not bp.recoverable:
            continue
        if dry_run:
            continue
        try:
            client.recover(bp.cid)
            bp.recovered = True
            recovered += 1
        except Exception as e:
            bp.recover_error = str(e)
            recover_errors += 1

    recoverable_count = sum(1 for bp in broken_pins if bp.recoverable)
    lost_count = sum(1 for bp in broken_pins if not bp.recoverable)

    return RepairResult(
        checked_at=datetime.now(timezone.utc),
        total_pins=len(raw_pins),
        broken=len(broken_pins),
        recoverable=recoverable_count,
        lost=lost_count,
        recovered=recovered,
        recover_errors=recover_errors,
        dry_run=dry_run,
        broken_pins=broken_pins,
    )


def tag_pins(
    profile: str,
    config: CCSConfig,
    host: str = None,
    dry_run: bool = False,
) -> dict:
    """Tag all pins with org and size metadata.

    Reads all pins, sets metadata={"org": profile, "size": bytes} on
    each that doesn't already have both. Size is fetched from the IPFS
    gateway's dag-json endpoint.

    Args:
        profile: Organization profile name (e.g., "hrdag")
        config: CCSConfig with auth
        host: Override which cluster node to talk to
        dry_run: If True, report what would change without modifying

    Returns:
        Dict with counts: total, tagged, skipped, errors, dry_run
    """
    client = _get_client(config, host)
    all_pins = client.pins()

    # Resolve gateway host (same node, port 8080)
    gateway_host = host or config.default_node
    node = config.get_node(gateway_host)
    if node:
        gateway_host = node.host

    tagged = 0
    skipped = 0
    errors = 0

    for pin in all_pins:
        existing_meta = pin.get("metadata") or {}
        has_org = existing_meta.get("org") == profile
        has_size = "size" in existing_meta

        if has_org and has_size:
            skipped += 1
            continue

        # Fetch size if not already known
        if has_size:
            size_str = existing_meta["size"]
        else:
            size_val = _get_dag_size(gateway_host, pin["cid"])
            size_str = str(size_val) if size_val is not None else None

        # Build metadata
        meta = {"org": profile}
        if size_str is not None:
            meta["size"] = size_str

        tagged += 1
        if not dry_run:
            try:
                client.pin(
                    pin["cid"],
                    name=pin.get("name"),
                    metadata=meta,
                )
            except Exception:
                errors += 1
                tagged -= 1

    return {
        "total": len(all_pins),
        "tagged": tagged,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }