# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# test/test_operations.py

"""Tests for CCS operations module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from community_cloud_storage.config import (
    CCSConfig,
    ClusterAuth,
    NodeConfig,
    ProfileConfig,
)
from community_cloud_storage.operations import (
    add,
    peers,
    status,
    _get_allocations,
    AllocationError,
    ConfigError,
)
from community_cloud_storage.types import RC_FAILED, RC_CONFIG_ERROR


@pytest.fixture
def sample_config():
    """Create a sample config for testing."""
    return CCSConfig(
        auth=ClusterAuth(user="admin", password="secret"),
        backup_node="chll",
        default_node="nas",
        profiles={
            "hrdag": ProfileConfig(name="hrdag", primary="nas"),
            "orgB": ProfileConfig(name="orgB", primary="meerkat"),
        },
        nodes={
            "nas": NodeConfig(name="nas", host="nas", peer_id="12D3KooWNAS"),
            "meerkat": NodeConfig(name="meerkat", host="meerkat", peer_id="12D3KooWMEER"),
            "chll": NodeConfig(name="chll", host="chll", peer_id="12D3KooWCHLL"),
        },
    )


class TestGetAllocations:
    def test_returns_primary_and_backup(self, sample_config):
        allocs = _get_allocations("hrdag", sample_config)
        assert allocs == ["12D3KooWNAS", "12D3KooWCHLL"]

    def test_different_profile(self, sample_config):
        allocs = _get_allocations("orgB", sample_config)
        assert allocs == ["12D3KooWMEER", "12D3KooWCHLL"]

    def test_unknown_profile_raises(self, sample_config):
        with pytest.raises(AllocationError, match="not found"):
            _get_allocations("unknown", sample_config)

    def test_missing_peer_id_raises(self, sample_config):
        sample_config.nodes["nas"].peer_id = None
        with pytest.raises(AllocationError, match="no peer_id"):
            _get_allocations("hrdag", sample_config)

    def test_missing_backup_raises(self, sample_config):
        sample_config.backup_node = None
        with pytest.raises(AllocationError, match="No backup_node"):
            _get_allocations("hrdag", sample_config)


class TestAdd:
    @patch("community_cloud_storage.operations.ClusterClient")
    def test_add_file_success(self, mock_client_class, sample_config):
        # Setup mock
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.add.return_value = [
            {"name": "test.txt", "cid": "QmTEST", "size": 42},
        ]
        # Mock pin_status to return 4 replicas (success case)
        mock_client.pin_status.return_value = {
            "cid": "QmTEST",
            "name": "test",
            "allocations": ["12D3KooWNAS", "12D3KooWCHLL"],
            "peer_map": {
                "12D3KooWNAS": {"peername": "nas", "status": "pinned", "error": ""},
                "12D3KooWCHLL": {"peername": "chll", "status": "pinned", "error": ""},
                "12D3KooWPeer3": {"peername": "peer3", "status": "pinned", "error": ""},
                "12D3KooWPeer4": {"peername": "peer4", "status": "pinned", "error": ""},
            },
            "replication_factor_min": 2,
            "replication_factor_max": 4,
        }

        # Create temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            path = Path(f.name)

        try:
            result = add(path, profile="hrdag", config=sample_config)

            assert result.complete is True
            assert result.root_cid == "QmTEST"
            assert result.profile == "hrdag"
            assert len(result.entries) == 1
            assert result.allocations == ["12D3KooWNAS", "12D3KooWCHLL"]
            assert result.replica_count == 4
            assert result.error is None

            # Verify client was called with allocations
            mock_client.add.assert_called_once()
            call_kwargs = mock_client.add.call_args[1]
            assert call_kwargs["allocations"] == ["12D3KooWNAS", "12D3KooWCHLL"]
        finally:
            path.unlink()

    @patch("community_cloud_storage.operations.ClusterClient")
    def test_add_directory_success(self, mock_client_class, sample_config):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.add.return_value = [
            {"name": "dir/file1.txt", "cid": "Qm1", "size": 10},
            {"name": "dir/file2.txt", "cid": "Qm2", "size": 20},
            {"name": "dir", "cid": "QmDIR", "size": 0},
        ]
        # Mock pin_status to return 4 replicas
        mock_client.pin_status.return_value = {
            "cid": "QmDIR",
            "name": "dir",
            "allocations": ["12D3KooWNAS", "12D3KooWCHLL"],
            "peer_map": {
                "12D3KooWNAS": {"peername": "nas", "status": "pinned", "error": ""},
                "12D3KooWCHLL": {"peername": "chll", "status": "pinned", "error": ""},
                "12D3KooWPeer3": {"peername": "peer3", "status": "pinned", "error": ""},
                "12D3KooWPeer4": {"peername": "peer4", "status": "pinned", "error": ""},
            },
            "replication_factor_min": 2,
            "replication_factor_max": 4,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "file1.txt").write_text("content1")
            (path / "file2.txt").write_text("content2")

            result = add(path, profile="hrdag", config=sample_config)

            assert result.complete is True
            assert result.root_cid == "QmDIR"
            assert len(result.entries) == 3
            assert result.total_size() == 30
            assert result.replica_count == 4

    def test_add_nonexistent_path_returns_error(self, sample_config):
        result = add(Path("/nonexistent/path"), profile="hrdag", config=sample_config)
        assert result.ok is False
        assert result.returncode == RC_FAILED
        assert "not found" in result.error.lower()

    @patch("community_cloud_storage.operations.ClusterClient")
    def test_add_api_error_returns_incomplete(self, mock_client_class, sample_config):
        from community_cloud_storage.cluster_api import ClusterAPIError

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.add.side_effect = ClusterAPIError("Connection failed", 500)

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            path = Path(f.name)

        try:
            result = add(path, profile="hrdag", config=sample_config)

            assert result.ok is False
            assert result.returncode == RC_FAILED
            assert "Connection failed" in result.error
            assert result.entries == []
        finally:
            path.unlink()

    def test_add_unknown_profile_returns_config_error(self, sample_config):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            path = Path(f.name)

        try:
            result = add(path, profile="nonexistent", config=sample_config)

            assert result.ok is False
            assert result.returncode == RC_CONFIG_ERROR
            assert "nonexistent" in result.error.lower()
        finally:
            path.unlink()


class TestStatus:
    @patch("community_cloud_storage.operations._get_client")
    def test_status_success(self, mock_get_client, sample_config):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.pin_status.return_value = {
            "cid": "QmTEST",
            "name": "test",
            "allocations": ["peer1"],
            "peer_map": {
                "peer1": {"peername": "nas", "status": "pinned", "error": ""},
            },
            "replication_factor_min": 2,
            "replication_factor_max": 3,
        }

        result = status("QmTEST", config=sample_config)

        assert result.cid == "QmTEST"
        assert result.pinned_count() == 1


class TestPeers:
    @patch("community_cloud_storage.operations._get_client")
    def test_peers_success(self, mock_get_client, sample_config):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock the _request method for NDJSON response
        mock_response = MagicMock()
        mock_response.text = '{"peername": "nas", "id": "12D3A", "addresses": []}\n{"peername": "meerkat", "id": "12D3B", "addresses": []}\n'
        mock_client._request.return_value = mock_response

        result = peers(config=sample_config)

        assert len(result) == 2
        assert result[0].name == "nas"
        assert result[1].name == "meerkat"
