# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/community_cloud_storage/config.py

"""
CCS Configuration Management

Config file location: ~/.ccs/config.yml

Schema:
    cluster:
      basic_auth_user: admin
      basic_auth_password: <secret>

    backup_node: chll          # Shared backup node name

    profiles:                  # Org -> primary node mapping
      hrdag:
        primary: nas
      test-orgB:
        primary: meerkat

    nodes:                     # Node info (populated by ansible)
      nas:
        host: nas              # Hostname for API calls
        peer_id: 12D3KooW...   # Cluster peer ID for allocations
      meerkat:
        host: meerkat
        peer_id: 12D3KooW...
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".ccs" / "config.yml"


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

    def to_dict(self) -> dict:
        """Serialize config to dict (for saving)."""
        result = {}

        if self.auth:
            result["cluster"] = {
                "basic_auth_user": self.auth.user,
                "basic_auth_password": self.auth.password,
            }

        if self.backup_node:
            result["backup_node"] = self.backup_node

        if self.default_node:
            result["default_node"] = self.default_node

        if self.profiles:
            result["profiles"] = {
                name: profile.to_dict() for name, profile in self.profiles.items()
            }

        if self.nodes:
            result["nodes"] = {
                name: node.to_dict() for name, node in self.nodes.items()
            }

        return result


def load_config(config_path: Path = None) -> CCSConfig:
    """
    Load CCS configuration from YAML file.

    Args:
        config_path: Path to config file. Default: ~/.ccs/config.yml

    Returns:
        CCSConfig object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raw = {}

    return parse_config(raw)


def parse_config(raw: dict) -> CCSConfig:
    """
    Parse raw config dict into CCSConfig object.

    Args:
        raw: Dict from yaml.safe_load()

    Returns:
        CCSConfig object
    """
    # Parse auth
    auth = None
    if "cluster" in raw:
        cluster = raw["cluster"]
        if cluster.get("basic_auth_user") and cluster.get("basic_auth_password"):
            auth = ClusterAuth(
                user=cluster["basic_auth_user"],
                password=cluster["basic_auth_password"],
            )

    # Parse profiles
    profiles = {}
    if "profiles" in raw:
        for name, data in raw["profiles"].items():
            profiles[name] = ProfileConfig.from_dict(name, data)

    # Parse nodes
    nodes = {}
    if "nodes" in raw:
        for name, data in raw["nodes"].items():
            nodes[name] = NodeConfig.from_dict(name, data)

    return CCSConfig(
        auth=auth,
        backup_node=raw.get("backup_node"),
        default_node=raw.get("default_node"),
        profiles=profiles,
        nodes=nodes,
    )


def save_config(config: CCSConfig, config_path: Path = None) -> None:
    """
    Save CCS configuration to YAML file.

    Args:
        config: CCSConfig object to save
        config_path: Path to save to. Default: ~/.ccs/config.yml
    """
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False, sort_keys=False)

    # Set restrictive permissions (config contains secrets)
    path.chmod(0o600)
