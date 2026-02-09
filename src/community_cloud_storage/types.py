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
