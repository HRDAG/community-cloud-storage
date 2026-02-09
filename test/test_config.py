# Author: PB and Claude
# Date: 2026-02-08
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# test/test_config.py

"""Tests for CCS config module (toml-based)."""

import tempfile
from pathlib import Path

import pytest

from community_cloud_storage.config import (
    CCSConfig,
    ClusterAuth,
    NodeConfig,
    ProfileConfig,
    _deep_merge,
    _load_auth,
    load_config,
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


class TestDeepMerge:
    def test_non_overlapping_sections(self):
        base = {"org": {"name": "hrdag"}, "postgres": {"database": "scottfiles"}}
        override = {"cluster": {"backup_node": "chll"}}
        result = _deep_merge(base, override)
        assert result["org"]["name"] == "hrdag"
        assert result["cluster"]["backup_node"] == "chll"

    def test_section_level_merge(self):
        base = {"cluster": {"default_node": "nas"}}
        override = {"cluster": {"backup_node": "chll"}}
        result = _deep_merge(base, override)
        assert result["cluster"]["default_node"] == "nas"
        assert result["cluster"]["backup_node"] == "chll"

    def test_override_wins_on_conflict(self):
        base = {"cluster": {"default_node": "nas"}}
        override = {"cluster": {"default_node": "chll"}}
        result = _deep_merge(base, override)
        assert result["cluster"]["default_node"] == "chll"

    def test_scalar_override(self):
        base = {"version": 1}
        override = {"version": 2}
        result = _deep_merge(base, override)
        assert result["version"] == 2

    def test_empty_base(self):
        result = _deep_merge({}, {"cluster": {"node": "x"}})
        assert result == {"cluster": {"node": "x"}}

    def test_empty_override(self):
        base = {"cluster": {"node": "x"}}
        result = _deep_merge(base, {})
        assert result == {"cluster": {"node": "x"}}


class TestLoadAuth:
    def test_valid_auth_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".auth", delete=False) as f:
            f.write("admin:secretpass")
            path = Path(f.name)

        try:
            auth = _load_auth(path)
            assert auth.user == "admin"
            assert auth.password == "secretpass"
        finally:
            path.unlink()

    def test_auth_file_with_colon_in_password(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".auth", delete=False) as f:
            f.write("admin:pass:with:colons")
            path = Path(f.name)

        try:
            auth = _load_auth(path)
            assert auth.user == "admin"
            assert auth.password == "pass:with:colons"
        finally:
            path.unlink()

    def test_auth_file_with_trailing_newline(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".auth", delete=False) as f:
            f.write("admin:secret\n")
            path = Path(f.name)

        try:
            auth = _load_auth(path)
            assert auth.user == "admin"
            assert auth.password == "secret"
        finally:
            path.unlink()

    def test_missing_auth_file(self):
        with pytest.raises(FileNotFoundError):
            _load_auth(Path("/nonexistent/auth"))

    def test_malformed_auth_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".auth", delete=False) as f:
            f.write("no-colon-here")
            path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Invalid auth file format"):
                _load_auth(path)
        finally:
            path.unlink()


class TestLoadConfig:
    def _write_toml(self, tmpdir: Path, name: str, content: str) -> Path:
        path = tmpdir / name
        path.write_text(content)
        return path

    def test_load_full_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            auth_file = tmpdir / "auth"
            auth_file.write_text("admin:pw")

            common = self._write_toml(tmpdir, "common.toml", """
[org]
name = "hrdag"
""")
            config = self._write_toml(tmpdir, "ccs.toml", f"""
[cluster]
backup_node = "chll"
default_node = "nas"
auth_file = "{auth_file}"

[profiles.hrdag]
primary = "nas"

[nodes.nas]
host = "nas"
peer_id = "12D3A"

[nodes.chll]
host = "chll"
peer_id = "12D3B"
""")
            cfg = load_config(common_path=common, config_path=config)
            assert cfg.auth.user == "admin"
            assert cfg.backup_node == "chll"
            assert cfg.default_node == "nas"
            assert "hrdag" in cfg.profiles
            assert "nas" in cfg.nodes
            assert "chll" in cfg.nodes

    def test_load_config_missing_ccs_toml(self):
        with pytest.raises(FileNotFoundError):
            load_config(
                common_path=Path("/nonexistent/common.toml"),
                config_path=Path("/nonexistent/ccs.toml"),
            )

    def test_load_config_missing_common_is_ok(self):
        """common.toml is optional — missing file should not error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            config = self._write_toml(tmpdir, "ccs.toml", """
[cluster]
backup_node = "chll"

[nodes.chll]
host = "chll"
peer_id = "12D3"
""")
            cfg = load_config(
                common_path=tmpdir / "no-such-common.toml",
                config_path=config,
            )
            assert cfg.backup_node == "chll"
            assert cfg.auth is None

    def test_deep_merge_with_common(self):
        """common.toml org section should survive merge with ccs.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            common = self._write_toml(tmpdir, "common.toml", """
[org]
name = "hrdag"

[postgres]
database = "scottfiles"
""")
            config = self._write_toml(tmpdir, "ccs.toml", """
[cluster]
backup_node = "chll"

[nodes.chll]
host = "chll"
peer_id = "12D3"
""")
            cfg = load_config(common_path=common, config_path=config)
            assert cfg.backup_node == "chll"

    def test_config_no_auth_file(self):
        """Config without auth_file should have auth=None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            config = self._write_toml(tmpdir, "ccs.toml", """
[cluster]
backup_node = "chll"

[nodes.chll]
host = "chll"
peer_id = "12D3"
""")
            cfg = load_config(
                common_path=tmpdir / "missing.toml",
                config_path=config,
            )
            assert cfg.auth is None

    def test_config_missing_auth_file_raises(self):
        """auth_file pointing to nonexistent file should raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            config = self._write_toml(tmpdir, "ccs.toml", """
[cluster]
auth_file = "/nonexistent/auth"
backup_node = "chll"
""")
            with pytest.raises(FileNotFoundError, match="Auth file"):
                load_config(
                    common_path=tmpdir / "missing.toml",
                    config_path=config,
                )

    def test_load_from_system_defaults(self):
        """Loading from /etc/tfc/ defaults should work on this machine."""
        cfg = load_config()
        assert cfg.auth is not None
        assert cfg.auth.user == "admin"
        assert cfg.backup_node == "chll"
        assert "hrdag" in cfg.profiles
        assert "nas" in cfg.nodes
        assert cfg.nodes["nas"].peer_id is not None
