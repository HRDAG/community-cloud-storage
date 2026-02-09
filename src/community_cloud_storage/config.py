# Author: PB and Claude
# Date: 2026-02-08
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/community_cloud_storage/config.py

"""
CCS Configuration Management

Reads TFC toml convention:
  /etc/tfc/common.toml  -- shared config (org name, postgres, ipfs endpoints)
  /etc/tfc/ccs.toml     -- CCS-specific config (nodes, profiles, auth file path)

Auth credentials live in a separate file referenced by [cluster].auth_file.
Deep merge: common.toml is base, ccs.toml overrides at section level.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_COMMON = Path("/etc/tfc/common.toml")
DEFAULT_CONFIG = Path("/etc/tfc/ccs.toml")


@dataclass
class NodeConfig:
    """Configuration for a single cluster node."""
    name: str
    host: str
    peer_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {"host": self.host, "peer_id": self.peer_id}

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "NodeConfig":
        if isinstance(data, str):
            # Simple format: just a hostname
            return cls(name=name, host=data)
        return cls(
            name=name,
            host=data.get("host", name),
            peer_id=data.get("peer_id"),
        )


@dataclass
class ProfileConfig:
    """Configuration for an organization profile."""
    name: str
    primary: str  # Name of primary node

    def to_dict(self) -> dict:
        return {"primary": self.primary}

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "ProfileConfig":
        return cls(name=name, primary=data["primary"])


@dataclass
class ClusterAuth:
    """Authentication credentials for cluster API."""
    user: str
    password: str

    def to_auth_string(self) -> str:
        return f"{self.user}:{self.password}"

    def to_tuple(self) -> tuple:
        return (self.user, self.password)


@dataclass
class CCSConfig:
    """Complete CCS configuration."""
    auth: Optional[ClusterAuth] = None
    backup_node: Optional[str] = None
    default_node: Optional[str] = None
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)
    nodes: dict[str, NodeConfig] = field(default_factory=dict)

    def get_node(self, name: str) -> Optional[NodeConfig]:
        """Get node config by name."""
        return self.nodes.get(name)

    def get_profile(self, name: str) -> Optional[ProfileConfig]:
        """Get profile config by name."""
        return self.profiles.get(name)

    def get_primary_for_profile(self, profile_name: str) -> Optional[NodeConfig]:
        """Get the primary node for a given profile/org."""
        profile = self.get_profile(profile_name)
        if not profile:
            return None
        return self.get_node(profile.primary)

    def get_backup_node(self) -> Optional[NodeConfig]:
        """Get the backup node config."""
        if not self.backup_node:
            return None
        return self.get_node(self.backup_node)

    def get_peer_id(self, node_name: str) -> Optional[str]:
        """Get peer ID for a node by name."""
        node = self.get_node(node_name)
        return node.peer_id if node else None

    def get_basic_auth_string(self) -> Optional[str]:
        """Get basic auth string for API calls."""
        return self.auth.to_auth_string() if self.auth else None

    def validate(self) -> tuple[list[str], list[str]]:
        """
        Validate configuration, return (errors, warnings).
        Empty errors list means config is valid for operations.
        """
        errors = []
        warnings = []

        # Check backup_node is set
        if not self.backup_node:
            errors.append("backup_node is not set")
        elif self.backup_node not in self.nodes:
            errors.append(f"backup_node '{self.backup_node}' not found in nodes")

        # Check default_node
        if self.default_node and self.default_node not in self.nodes:
            errors.append(f"default_node '{self.default_node}' not found in nodes")

        # Check each profile's primary references a known node
        for name, profile in self.profiles.items():
            if profile.primary not in self.nodes:
                errors.append(
                    f"profile '{name}' references unknown node '{profile.primary}'"
                )

        # Check nodes have peer_ids (warning - needed for allocations)
        for name, node in self.nodes.items():
            if not node.peer_id:
                warnings.append(f"node '{name}' has no peer_id (run ansible to populate)")

        # Check auth is set (warning - needed for most operations)
        if not self.auth:
            warnings.append("no cluster auth configured")

        return errors, warnings


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base at section level.

    For top-level keys that are both dicts (TOML sections), merge their
    contents with override winning on key conflict.
    For non-dict values, override replaces base.
    """
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return merged


def _load_auth(auth_file: Path) -> ClusterAuth:
    """Read auth file containing 'user:password'.

    Raises:
        FileNotFoundError: If auth file doesn't exist
        ValueError: If auth file format is invalid
    """
    if not auth_file.exists():
        raise FileNotFoundError(f"Auth file not found: {auth_file}")

    text = auth_file.read_text().strip()
    if ":" not in text:
        raise ValueError(f"Invalid auth file format (expected 'user:password'): {auth_file}")

    user, password = text.split(":", 1)
    return ClusterAuth(user=user, password=password)


def load_config(
    common_path: Path = None, config_path: Path = None
) -> CCSConfig:
    """Load config from common.toml + ccs.toml. Returns CCSConfig.

    Args:
        common_path: Path to common.toml. Default: /etc/tfc/common.toml
        config_path: Path to ccs.toml. Default: /etc/tfc/ccs.toml

    Returns:
        CCSConfig object

    Raises:
        FileNotFoundError: If config files or auth file don't exist
        ValueError: If config files are invalid
    """
    common_file = common_path or DEFAULT_COMMON
    config_file = config_path or DEFAULT_CONFIG

    # Load common.toml (optional — may not exist on minimal installs)
    common = {}
    if common_file.exists():
        with open(common_file, "rb") as f:
            common = tomllib.load(f)

    # Load ccs.toml (required)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file, "rb") as f:
        specific = tomllib.load(f)

    config = _deep_merge(common, specific)

    # Parse cluster section
    cluster = config.get("cluster", {})

    # Parse auth from file
    auth = None
    if "auth_file" in cluster:
        auth = _load_auth(Path(cluster["auth_file"]))

    # Parse profiles
    profiles = {}
    for name, data in config.get("profiles", {}).items():
        profiles[name] = ProfileConfig.from_dict(name, data)

    # Parse nodes
    nodes = {}
    for name, data in config.get("nodes", {}).items():
        nodes[name] = NodeConfig.from_dict(name, data)

    return CCSConfig(
        auth=auth,
        backup_node=cluster.get("backup_node"),
        default_node=cluster.get("default_node"),
        profiles=profiles,
        nodes=nodes,
    )
