# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/community_cloud_storage/types.py

"""
CCS Type Definitions

Dataclasses for library return types with serialization support.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import json


@dataclass
class CIDEntry:
    """A single file or directory entry with its CID."""
    path: str                       # Relative path within the add
    cid: str                        # The IPFS CID (empty string if failed)
    size: int                       # Size in bytes
    is_root: bool = False           # True if this is the root entry (cid == root_cid)
    error: Optional[str] = None     # Error message if this entry failed

    @property
    def ok(self) -> bool:
        """True if this entry was added successfully."""
        return self.error is None and self.cid != ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "cid": self.cid,
            "size": self.size,
            "is_root": self.is_root,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CIDEntry":
        return cls(
            path=data["path"],
            cid=data["cid"],
            size=data["size"],
            is_root=data.get("is_root", False),
            error=data.get("error"),
        )

    @classmethod
    def from_ipfs_entry(cls, entry: dict, is_root: bool = False) -> "CIDEntry":
        """Create from IPFS add response entry."""
        # IPFS returns: {"name": "path", "cid": "Qm...", "size": 123}
        return cls(
            path=entry["name"],
            cid=entry["cid"],
            size=entry.get("size", 0),
            is_root=is_root,
            error=None,
        )


# Return codes for AddResult
RC_SUCCESS = 0          # All entries added successfully
RC_PARTIAL = 1          # Some entries added, some failed
RC_FAILED = 2           # No entries added (API/network error)
RC_CONFIG_ERROR = 3     # Configuration error (missing profile, peer_id, etc.)


@dataclass
class AddResult:
    """Result of adding file(s) to the cluster."""
    root_cid: str                           # CID of the root (top-level item, empty if failed)
    root_path: str                          # Original filesystem path
    entries: list[CIDEntry]                 # All files/dirs with their CIDs
    allocations: list[str]                  # Peer IDs for explicit allocation
    profile: Optional[str]                  # Profile used (e.g., "hrdag")
    added_at: datetime                      # When the add completed
    cluster_host: str                       # Node we talked to
    returncode: int                         # 0=success, 1=partial, 2=failed, 3=config error
    error: Optional[str] = None             # Error message if returncode != 0
    replica_count: Optional[int] = None     # Actual number of peers with successful pin

    @property
    def ok(self) -> bool:
        """True if add fully succeeded (returncode == 0)."""
        return self.returncode == RC_SUCCESS

    @property
    def complete(self) -> bool:
        """Alias for ok, for backward compatibility."""
        return self.ok

    def to_dict(self) -> dict:
        return {
            "root_cid": self.root_cid,
            "root_path": self.root_path,
            "entries": [e.to_dict() for e in self.entries],
            "allocations": self.allocations,
            "profile": self.profile,
            "added_at": self.added_at.isoformat(),
            "cluster_host": self.cluster_host,
            "returncode": self.returncode,
            "error": self.error,
            "replica_count": self.replica_count,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "AddResult":
        added_at = data["added_at"]
        if isinstance(added_at, str):
            # Parse ISO format, handle both with and without timezone
            if added_at.endswith("Z"):
                added_at = added_at[:-1] + "+00:00"
            added_at = datetime.fromisoformat(added_at)

        return cls(
            root_cid=data["root_cid"],
            root_path=data["root_path"],
            entries=[CIDEntry.from_dict(e) for e in data["entries"]],
            allocations=data.get("allocations", []),
            profile=data.get("profile"),
            added_at=added_at,
            cluster_host=data["cluster_host"],
            returncode=data.get("returncode", RC_SUCCESS if data.get("complete", True) else RC_FAILED),
            error=data.get("error"),
            replica_count=data.get("replica_count"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AddResult":
        return cls.from_dict(json.loads(json_str))

    def root_entry(self) -> Optional["CIDEntry"]:
        """Return the root entry (where cid == root_cid)."""
        for e in self.entries:
            if e.cid == self.root_cid:
                return e
        return None

    def child_entries(self) -> list["CIDEntry"]:
        """Return all non-root entries."""
        return [e for e in self.entries if e.cid != self.root_cid]

    def total_size(self) -> int:
        """Total size of all child entries (excludes root to avoid double-counting)."""
        return sum(e.size for e in self.child_entries())


@dataclass
class PeerInfo:
    """Information about a cluster peer."""
    name: str                               # Peername (e.g., "nas")
    peer_id: str                            # Cluster peer ID
    addresses: list[str] = field(default_factory=list)  # Multiaddrs
    error: Optional[str] = None             # Error if peer unreachable

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "peer_id": self.peer_id,
            "addresses": self.addresses,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PeerInfo":
        return cls(
            name=data["name"],
            peer_id=data["peer_id"],
            addresses=data.get("addresses", []),
            error=data.get("error"),
        )

    @classmethod
    def from_cluster_peer(cls, peer: dict) -> "PeerInfo":
        """Create from cluster /peers response."""
        return cls(
            name=peer.get("peername", ""),
            peer_id=peer.get("id", ""),
            addresses=peer.get("addresses", []),
            error=peer.get("error") or None,
        )


@dataclass
class PeerPinStatus:
    """Pin status for a single peer."""
    peername: str
    status: str                             # "pinned", "pinning", "error", "remote"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "peername": self.peername,
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PeerPinStatus":
        return cls(
            peername=data["peername"],
            status=data["status"],
            error=data.get("error"),
        )


@dataclass
class PinStatus:
    """Status of a pinned CID in the cluster."""
    cid: str
    name: Optional[str]                     # Pin name if set
    allocations: list[str]                  # Peer IDs allocated to
    peer_map: dict[str, PeerPinStatus]      # peer_id -> status
    replication_factor_min: Optional[int]
    replication_factor_max: Optional[int]
    created: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "cid": self.cid,
            "name": self.name,
            "allocations": self.allocations,
            "peer_map": {k: v.to_dict() for k, v in self.peer_map.items()},
            "replication_factor_min": self.replication_factor_min,
            "replication_factor_max": self.replication_factor_max,
            "created": self.created.isoformat() if self.created else None,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "PinStatus":
        created = data.get("created")
        if created and isinstance(created, str):
            if created.endswith("Z"):
                created = created[:-1] + "+00:00"
            created = datetime.fromisoformat(created)

        peer_map = {}
        for peer_id, status_data in data.get("peer_map", {}).items():
            if isinstance(status_data, dict):
                peer_map[peer_id] = PeerPinStatus(
                    peername=status_data.get("peername", ""),
                    status=status_data.get("status", "unknown"),
                    error=status_data.get("error"),
                )

        return cls(
            cid=data["cid"],
            name=data.get("name"),
            allocations=data.get("allocations", []),
            peer_map=peer_map,
            replication_factor_min=data.get("replication_factor_min"),
            replication_factor_max=data.get("replication_factor_max"),
            created=created,
        )

    @classmethod
    def from_cluster_status(cls, data: dict) -> "PinStatus":
        """Create from cluster /pins/{cid} response."""
        peer_map = {}
        for peer_id, status_data in data.get("peer_map", {}).items():
            peer_map[peer_id] = PeerPinStatus(
                peername=status_data.get("peername", ""),
                status=status_data.get("status", "unknown"),
                error=status_data.get("error") or None,
            )

        created = data.get("created")
        if created and isinstance(created, str):
            if created.endswith("Z"):
                created = created[:-1] + "+00:00"
            created = datetime.fromisoformat(created)

        return cls(
            cid=data.get("cid", ""),
            name=data.get("name"),
            allocations=data.get("allocations", []),
            peer_map=peer_map,
            replication_factor_min=data.get("replication_factor_min"),
            replication_factor_max=data.get("replication_factor_max"),
            created=created,
        )

    def is_fully_pinned(self) -> bool:
        """True if all allocated peers have status 'pinned'."""
        if not self.allocations:
            return False
        for peer_id in self.allocations:
            if peer_id not in self.peer_map:
                return False
            if self.peer_map[peer_id].status != "pinned":
                return False
        return True

    def pinned_count(self) -> int:
        """Number of peers with status 'pinned'."""
        return sum(1 for s in self.peer_map.values() if s.status == "pinned")

    def pinned_peers(self) -> list[str]:
        """List of peernames that have pinned this CID."""
        return [s.peername for s in self.peer_map.values() if s.status == "pinned"]


@dataclass
class EnsurePinsResult:
    """Result of ensure-pins operation."""
    total: int                              # Total pins checked
    already_correct: int                    # Pins already having required allocations
    fixed: int                              # Pins re-pinned with correct allocations
    errors: int                             # Pins that failed to re-pin
    dry_run: bool                           # Whether this was a dry run
    required_peers: list[str]               # Peer IDs that were required
    error_details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "already_correct": self.already_correct,
            "fixed": self.fixed,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "required_peers": self.required_peers,
            "error_details": self.error_details,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# Return codes for HealthReport
HC_OK = 0               # All peers up, no pin errors
HC_DEGRADED = 1         # Some pin errors but cluster functional
HC_ERROR = 2            # Peers offline or API unreachable


@dataclass
class NodeHealth:
    """Health summary for a single cluster node."""
    name: str
    peer_id: str
    online: bool
    pinned: int = 0
    remote: int = 0
    pin_errors: int = 0
    error: Optional[str] = None     # peer-level error from /peers

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "peer_id": self.peer_id,
            "online": self.online,
            "pinned": self.pinned,
            "remote": self.remote,
            "pin_errors": self.pin_errors,
            "error": self.error,
        }

    @property
    def status(self) -> str:
        if not self.online:
            return "error"
        if self.pin_errors > 0:
            return "degraded"
        return "ok"


@dataclass
class HealthReport:
    """Cluster health report."""
    status: str                     # "ok", "degraded", "error"
    checked_at: datetime
    peers_total: int
    peers_online: int
    pins_total: int
    nodes: list[NodeHealth]
    pin_errors: list[dict]          # [{cid, node, error}, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
            "peers": {
                "total": self.peers_total,
                "online": self.peers_online,
                "offline": self.peers_total - self.peers_online,
                "list": [n.to_dict() for n in self.nodes],
            },
            "pins": {
                "total": self.pins_total,
                "by_node": {
                    n.name: {"pinned": n.pinned, "remote": n.remote, "errors": n.pin_errors}
                    for n in self.nodes
                },
                "errors": self.pin_errors,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @property
    def exit_code(self) -> int:
        """Return process exit code: 0=ok, 1=degraded, 2=error."""
        if self.status == "ok":
            return 0
        if self.status == "degraded":
            return 1
        return 2


# Return codes for RepairResult
RC_REPAIR_CLEAN = 0         # No broken pins found
RC_REPAIR_FIXED = 1         # Broken pins found, recovery triggered
RC_REPAIR_LOST = 2          # Lost pins exist (data unrecoverable)


@dataclass
class BrokenPin:
    """A pin with errors in its peer_map."""
    cid: str
    name: Optional[str]
    recoverable: bool
    error_nodes: list[dict]         # [{"node": name, "error": msg}, ...]
    healthy_nodes: list[str]        # Peernames with pinned/remote/pinning/pin_queued
    recovered: bool = False
    recover_error: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "cid": self.cid,
            "name": self.name,
            "recoverable": self.recoverable,
            "error_nodes": self.error_nodes,
            "healthy_nodes": self.healthy_nodes,
        }
        if self.recovered:
            d["recovered"] = True
        if self.recover_error:
            d["recover_error"] = self.recover_error
        return d


@dataclass
class RepairResult:
    """Result of repair operation."""
    checked_at: datetime
    total_pins: int
    broken: int
    recoverable: int
    lost: int
    recovered: int
    recover_errors: int
    dry_run: bool
    broken_pins: list[BrokenPin] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at.isoformat(),
            "total_pins": self.total_pins,
            "broken": self.broken,
            "recoverable": self.recoverable,
            "lost": self.lost,
            "recovered": self.recovered,
            "recover_errors": self.recover_errors,
            "dry_run": self.dry_run,
            "broken_pins": [bp.to_dict() for bp in self.broken_pins],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @property
    def exit_code(self) -> int:
        """0=clean, 1=broken pins found, 2=lost pins exist."""
        if self.lost > 0:
            return RC_REPAIR_LOST
        if self.broken > 0:
            return RC_REPAIR_FIXED
        return RC_REPAIR_CLEAN


# Return codes for RebalanceResult
RC_REBALANCE_NOOP = 0       # All pins already at target replication
RC_REBALANCE_CHANGED = 1    # Some pins were rebalanced
RC_REBALANCE_ERRORS = 2     # Some re-pins failed


@dataclass
class RebalancePinAction:
    """A single pin rebalance action."""
    cid: str
    name: Optional[str]
    action: str                         # "add_replicas", "remove_replicas", "already_correct"
    current_allocations: list[str]      # peer IDs before
    new_allocations: list[str]          # peer IDs after (empty if already_correct)
    added_peers: list[str]              # peer names added
    removed_peers: list[str]            # peer names removed
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "cid": self.cid,
            "name": self.name,
            "action": self.action,
            "current_allocations": self.current_allocations,
            "new_allocations": self.new_allocations,
            "added_peers": self.added_peers,
            "removed_peers": self.removed_peers,
        }
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class RebalanceResult:
    """Result of rebalance operation."""
    checked_at: datetime
    total_pins: int
    already_correct: int
    added_replicas: int                 # pins that got new replicas
    removed_replicas: int               # pins that had excess replicas removed
    errors: int
    dry_run: bool
    replication_min: int
    replication_max: int
    actions: list[RebalancePinAction] = field(default_factory=list)
    node_summary: dict = field(default_factory=dict)  # {node_name: {before: N, after: N}}

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at.isoformat(),
            "total_pins": self.total_pins,
            "already_correct": self.already_correct,
            "added_replicas": self.added_replicas,
            "removed_replicas": self.removed_replicas,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "replication_min": self.replication_min,
            "replication_max": self.replication_max,
            "actions": [a.to_dict() for a in self.actions if a.action != "already_correct"],
            "node_summary": self.node_summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @property
    def exit_code(self) -> int:
        """0=no changes needed, 1=changes made, 2=errors occurred."""
        if self.errors > 0:
            return RC_REBALANCE_ERRORS
        if self.added_replicas > 0 or self.removed_replicas > 0:
            return RC_REBALANCE_CHANGED
        return RC_REBALANCE_NOOP
