# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# test/test_config.py

"""Tests for CCS config module."""

import tempfile
from pathlib import Path

import pytest
import yaml

from community_cloud_storage.config import (
    CCSConfig,
    ClusterAuth,
    NodeConfig,
    ProfileConfig,
    load_config,
    parse_config,
    save_config,
)


class TestNodeConfig:
    def test_from_dict_simple(self):
        node = NodeConfig.from_dict("nas", "nas.example.com")
        assert node.name == "nas"
        assert node.host == "nas.example.com"
        assert node.peer_id is None

    def test_from_dict_full(self):
        node = NodeConfig.from_dict(
            "nas",
            {"host": "nas.example.com", "peer_id": "12D3KooW123"},
        )
        assert node.name == "nas"
        assert node.host == "nas.example.com"
        assert node.peer_id == "12D3KooW123"

    def test_to_dict(self):
        node = NodeConfig(name="nas", host="nas", peer_id="12D3KooW123")
        assert node.to_dict() == {"host": "nas", "peer_id": "12D3KooW123"}


class TestProfileConfig:
    def test_from_dict(self):
        profile = ProfileConfig.from_dict("hrdag", {"primary": "nas"})
        assert profile.name == "hrdag"
        assert profile.primary == "nas"

    def test_to_dict(self):
        profile = ProfileConfig(name="hrdag", primary="nas")
        assert profile.to_dict() == {"primary": "nas"}


class TestClusterAuth:
    def test_to_auth_string(self):
        auth = ClusterAuth(user="admin", password="secret")
        assert auth.to_auth_string() == "admin:secret"

    def test_to_tuple(self):
        auth = ClusterAuth(user="admin", password="secret")
        assert auth.to_tuple() == ("admin", "secret")


class TestCCSConfig:
    def test_empty_config(self):
        cfg = CCSConfig()
        assert cfg.auth is None
        assert cfg.backup_node is None
        assert cfg.profiles == {}
        assert cfg.nodes == {}

    def test_get_node(self):
        cfg = CCSConfig(
            nodes={"nas": NodeConfig(name="nas", host="nas", peer_id="12D3")}
        )
        assert cfg.get_node("nas").host == "nas"
        assert cfg.get_node("missing") is None

    def test_get_profile(self):
        cfg = CCSConfig(
            profiles={"hrdag": ProfileConfig(name="hrdag", primary="nas")}
        )
        assert cfg.get_profile("hrdag").primary == "nas"
        assert cfg.get_profile("missing") is None

    def test_get_primary_for_profile(self):
        cfg = CCSConfig(
            profiles={"hrdag": ProfileConfig(name="hrdag", primary="nas")},
            nodes={"nas": NodeConfig(name="nas", host="nas", peer_id="12D3")},
        )
        node = cfg.get_primary_for_profile("hrdag")
        assert node.name == "nas"

    def test_get_backup_node(self):
        cfg = CCSConfig(
            backup_node="chll",
            nodes={"chll": NodeConfig(name="chll", host="chll", peer_id="12D3")},
        )
        assert cfg.get_backup_node().name == "chll"

    def test_get_peer_id(self):
        cfg = CCSConfig(
            nodes={"nas": NodeConfig(name="nas", host="nas", peer_id="12D3KooW123")}
        )
        assert cfg.get_peer_id("nas") == "12D3KooW123"
        assert cfg.get_peer_id("missing") is None

    def test_validate_ok(self):
        cfg = CCSConfig(
            backup_node="chll",
            profiles={"hrdag": ProfileConfig(name="hrdag", primary="nas")},
            nodes={
                "nas": NodeConfig(name="nas", host="nas", peer_id="12D3A"),
                "chll": NodeConfig(name="chll", host="chll", peer_id="12D3B"),
            },
            auth=ClusterAuth(user="admin", password="secret"),
        )
        errors, warnings = cfg.validate()
        assert errors == []
        assert warnings == []

    def test_validate_missing_backup_node(self):
        cfg = CCSConfig(
            backup_node="missing",
            nodes={"nas": NodeConfig(name="nas", host="nas")},
        )
        errors, warnings = cfg.validate()
        assert len(errors) == 1
        assert "missing" in errors[0]

    def test_validate_missing_profile_primary(self):
        cfg = CCSConfig(
            backup_node="nas",
            profiles={"hrdag": ProfileConfig(name="hrdag", primary="missing")},
            nodes={"nas": NodeConfig(name="nas", host="nas")},
        )
        errors, warnings = cfg.validate()
        assert len(errors) == 1
        assert "missing" in errors[0]

    def test_validate_warnings_for_missing_peer_id(self):
        cfg = CCSConfig(
            backup_node="chll",
            nodes={
                "nas": NodeConfig(name="nas", host="nas"),  # no peer_id
                "chll": NodeConfig(name="chll", host="chll", peer_id="12D3"),
            },
        )
        errors, warnings = cfg.validate()
        assert errors == []
        assert any("nas" in w and "peer_id" in w for w in warnings)


class TestParseConfig:
    def test_minimal_config(self):
        cfg = parse_config({})
        assert cfg.auth is None
        assert cfg.profiles == {}

    def test_full_config(self):
        raw = {
            "cluster": {
                "basic_auth_user": "admin",
                "basic_auth_password": "secret",
            },
            "backup_node": "chll",
            "default_node": "nas",
            "profiles": {
                "hrdag": {"primary": "nas"},
            },
            "nodes": {
                "nas": {"host": "nas", "peer_id": "12D3"},
                "chll": {"host": "chll", "peer_id": "45D6"},
            },
        }
        cfg = parse_config(raw)
        assert cfg.auth.user == "admin"
        assert cfg.backup_node == "chll"
        assert cfg.default_node == "nas"
        assert "hrdag" in cfg.profiles
        assert "nas" in cfg.nodes
        assert "chll" in cfg.nodes


class TestLoadAndSaveConfig:
    def test_load_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(
                {
                    "cluster": {"basic_auth_user": "admin", "basic_auth_password": "pw"},
                    "backup_node": "chll",
                },
                f,
            )
            path = Path(f.name)

        try:
            cfg = load_config(path)
            assert cfg.auth.user == "admin"
            assert cfg.backup_node == "chll"
        finally:
            path.unlink()

    def test_load_config_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent/config.yml"))

    def test_save_config(self):
        cfg = CCSConfig(
            auth=ClusterAuth(user="admin", password="secret"),
            backup_node="chll",
            profiles={"hrdag": ProfileConfig(name="hrdag", primary="nas")},
            nodes={"nas": NodeConfig(name="nas", host="nas", peer_id="12D3")},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yml"
            save_config(cfg, path)

            # Verify file exists and has correct permissions
            assert path.exists()
            assert (path.stat().st_mode & 0o777) == 0o600

            # Reload and verify
            loaded = load_config(path)
            assert loaded.auth.user == "admin"
            assert loaded.backup_node == "chll"
            assert "hrdag" in loaded.profiles
            assert "nas" in loaded.nodes

    def test_round_trip(self):
        """Config survives save/load cycle."""
        original = CCSConfig(
            auth=ClusterAuth(user="admin", password="secret"),
            backup_node="chll",
            default_node="nas",
            profiles={
                "hrdag": ProfileConfig(name="hrdag", primary="nas"),
                "orgB": ProfileConfig(name="orgB", primary="meerkat"),
            },
            nodes={
                "nas": NodeConfig(name="nas", host="nas", peer_id="12D3"),
                "meerkat": NodeConfig(name="meerkat", host="meerkat", peer_id="45D6"),
                "chll": NodeConfig(name="chll", host="chll", peer_id="78E9"),
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yml"
            save_config(original, path)
            loaded = load_config(path)

            assert loaded.auth.user == original.auth.user
            assert loaded.backup_node == original.backup_node
            assert loaded.default_node == original.default_node
            assert set(loaded.profiles.keys()) == set(original.profiles.keys())
            assert set(loaded.nodes.keys()) == set(original.nodes.keys())
            for name in loaded.nodes:
                assert loaded.nodes[name].peer_id == original.nodes[name].peer_id
