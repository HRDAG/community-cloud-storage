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
    health,
    peers,
    repair,
    status,
    tag_pins,
    _get_allocations,
    AllocationError,
    ConfigError,
    CCSError,
)
from community_cloud_storage.types import (
    RC_FAILED,
    RC_CONFIG_ERROR,
    RC_REPAIR_CLEAN,
    RC_REPAIR_FIXED,
    RC_REPAIR_LOST,
)
from community_cloud_storage.cluster_api import ClusterAPIError


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


class TestGet:
    """Tests for get() operation."""

    @patch("community_cloud_storage.operations.status")
    def test_get_nonexistent_cid_raises(self, mock_status, sample_config):
        """Should raise ClusterAPIError for non-existent CID."""
        from community_cloud_storage.operations import get

        # Mock status to raise ClusterAPIError (CID not found)
        mock_status.side_effect = ClusterAPIError("CID not found", 404)

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "output"
            with pytest.raises(ClusterAPIError, match="not found"):
                get(cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                    dest=dest, config=sample_config)

    @patch("community_cloud_storage.operations.status")
    def test_get_unknown_profile_raises(self, mock_status, sample_config):
        """Should raise ConfigError for unknown profile."""
        from community_cloud_storage.operations import get
        from community_cloud_storage.types import PinStatus, PeerPinStatus

        # Mock status to return a valid pin status (so we reach profile check)
        mock_status.return_value = PinStatus(
            cid="QmTEST", name="test", allocations=["12D3KooWNAS"],
            peer_map={"12D3KooWNAS": PeerPinStatus("nas", "pinned", None)},
            replication_factor_min=2, replication_factor_max=4,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "output"
            with pytest.raises(ConfigError, match="Profile.*not found"):
                get(cid="QmTEST", dest=dest, config=sample_config, profile="nonexistent")

    def test_get_no_pinned_peers_raises(self, sample_config):
        """Should raise error if no peers have pinned the content."""
        from community_cloud_storage.operations import get
        from community_cloud_storage.types import PinStatus, PeerPinStatus

        with patch("community_cloud_storage.operations.status") as mock_status:
            mock_status.return_value = PinStatus(
                cid="QmTEST", name=None, allocations=[], peer_map={},
                replication_factor_min=None, replication_factor_max=None,
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "output"
                with pytest.raises(CCSError, match="No peers have pinned"):
                    get(cid="QmTEST", dest=dest, config=sample_config)

    @patch("community_cloud_storage.operations.requests")
    @patch("community_cloud_storage.operations.status")
    def test_get_file_success(self, mock_status, mock_requests, sample_config):
        """Should download file from peer with pinned content."""
        from community_cloud_storage.operations import get
        from community_cloud_storage.types import PinStatus, PeerPinStatus

        mock_status.return_value = PinStatus(
            cid="QmTEST", name="test", allocations=["12D3KooWNAS"],
            peer_map={"12D3KooWNAS": PeerPinStatus("nas", "pinned", None)},
            replication_factor_min=2, replication_factor_max=4,
        )

        # Mock HEAD response (file, not directory)
        mock_head = MagicMock()
        mock_head.headers = {"Content-Type": "application/octet-stream"}
        mock_requests.head.return_value = mock_head

        # Mock GET response
        mock_get = MagicMock()
        mock_get.iter_content.return_value = [b"test content"]
        mock_requests.get.return_value = mock_get

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "test.txt"
            get(cid="QmTEST", dest=dest, config=sample_config)

            # Verify HEAD was called to detect type
            mock_requests.head.assert_called_once_with("http://nas:8080/ipfs/QmTEST", allow_redirects=True)
            # Verify GET was called without format=tar for files
            mock_requests.get.assert_called_once_with("http://nas:8080/ipfs/QmTEST", stream=True)
            assert dest.read_bytes() == b"test content"

    @patch("community_cloud_storage.operations.requests")
    @patch("community_cloud_storage.operations.status")
    def test_get_directory_with_format_tar(self, mock_status, mock_requests, sample_config):
        """Should use format=tar for directories to avoid HTML listing."""
        from community_cloud_storage.operations import get
        from community_cloud_storage.types import PinStatus, PeerPinStatus

        mock_status.return_value = PinStatus(
            cid="QmDIR", name="test",
            allocations=["12D3KooWNAS"],
            peer_map={"12D3KooWNAS": PeerPinStatus("nas", "pinned", None)},
            replication_factor_min=2, replication_factor_max=4,
        )

        # Mock HEAD response (directory - returns text/html)
        mock_head = MagicMock()
        mock_head.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_requests.head.return_value = mock_head

        # Mock GET response
        mock_get = MagicMock()
        mock_get.iter_content.return_value = [b"tar archive content"]
        mock_requests.get.return_value = mock_get

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "archive.tar"
            get(cid="QmDIR", dest=dest, config=sample_config)

            # Verify HEAD was called to detect directory
            mock_requests.head.assert_called_once_with("http://nas:8080/ipfs/QmDIR", allow_redirects=True)
            # Verify GET was called with format=tar for directories
            mock_requests.get.assert_called_once_with("http://nas:8080/ipfs/QmDIR?format=tar", stream=True)
            assert dest.read_bytes() == b"tar archive content"

    @patch("community_cloud_storage.operations.requests")
    @patch("community_cloud_storage.operations.status")
    def test_get_with_profile_prefers_primary(self, mock_status, mock_requests, sample_config):
        """Should prefer profile's primary node when available."""
        from community_cloud_storage.operations import get
        from community_cloud_storage.types import PinStatus, PeerPinStatus

        mock_status.return_value = PinStatus(
            cid="QmTEST", name="test",
            allocations=["12D3KooWNAS", "12D3KooWCHLL"],
            peer_map={
                "12D3KooWNAS": PeerPinStatus("nas", "pinned", None),
                "12D3KooWCHLL": PeerPinStatus("chll", "pinned", None),
            },
            replication_factor_min=2, replication_factor_max=4,
        )

        # Mock HEAD response (file)
        mock_head = MagicMock()
        mock_head.headers = {"Content-Type": "application/octet-stream"}
        mock_requests.head.return_value = mock_head

        # Mock GET response
        mock_get = MagicMock()
        mock_get.iter_content.return_value = [b"test content"]
        mock_requests.get.return_value = mock_get

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "test.txt"
            get(cid="QmTEST", dest=dest, config=sample_config, profile="hrdag")

            # hrdag profile has nas as primary - should use nas host
            mock_requests.head.assert_called_once_with("http://nas:8080/ipfs/QmTEST", allow_redirects=True)
            mock_requests.get.assert_called_once_with("http://nas:8080/ipfs/QmTEST", stream=True)

    @patch("community_cloud_storage.operations.requests")
    @patch("community_cloud_storage.operations.status")
    def test_get_fallback_to_backup(self, mock_status, mock_requests, sample_config):
        """Should fallback to backup if primary doesn't have content."""
        from community_cloud_storage.operations import get
        from community_cloud_storage.types import PinStatus, PeerPinStatus

        mock_status.return_value = PinStatus(
            cid="QmTEST", name="test",
            allocations=["12D3KooWCHLL"],  # Only backup has it
            peer_map={"12D3KooWCHLL": PeerPinStatus("chll", "pinned", None)},
            replication_factor_min=2, replication_factor_max=4,
        )

        # Mock HEAD response (file)
        mock_head = MagicMock()
        mock_head.headers = {"Content-Type": "text/plain"}
        mock_requests.head.return_value = mock_head

        # Mock GET response
        mock_get = MagicMock()
        mock_get.iter_content.return_value = [b"test content"]
        mock_requests.get.return_value = mock_get

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "test.txt"
            get(cid="QmTEST", dest=dest, config=sample_config, profile="hrdag")

            # Should use chll (backup) since nas doesn't have it
            mock_requests.head.assert_called_once_with("http://chll:8080/ipfs/QmTEST", allow_redirects=True)
            mock_requests.get.assert_called_once_with("http://chll:8080/ipfs/QmTEST", stream=True)


def _make_peers_ndjson(peer_list):
    """Build NDJSON text from list of (name, peer_id, error) tuples."""
    import json as _json
    lines = []
    for name, peer_id, error in peer_list:
        obj = {"peername": name, "id": peer_id, "addresses": []}
        if error:
            obj["error"] = error
        lines.append(_json.dumps(obj))
    return "\n".join(lines)


def _make_pin(cid, peer_statuses):
    """Build a raw pin dict from cid and {peer_id: (peername, status, error)}."""
    peer_map = {}
    for peer_id, (peername, st, err) in peer_statuses.items():
        peer_map[peer_id] = {"peername": peername, "status": st, "error": err or ""}
    return {
        "cid": cid,
        "name": "",
        "allocations": list(peer_statuses.keys()),
        "peer_map": peer_map,
        "replication_factor_min": 2,
        "replication_factor_max": 4,
    }


class TestHealth:
    """Tests for health() operation."""

    @patch("community_cloud_storage.operations._get_client")
    def test_health_all_ok(self, mock_get_client, sample_config):
        """All peers up, all pins pinned -> status ok."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock /peers
        mock_response = MagicMock()
        mock_response.text = _make_peers_ndjson([
            ("nas", "12D3KooWNAS", None),
            ("chll", "12D3KooWCHLL", None),
            ("meerkat", "12D3KooWMEER", None),
        ])
        mock_client._request.return_value = mock_response

        # Mock /pins - all pinned on nas+chll, remote on meerkat
        mock_client.pins.return_value = [
            _make_pin("QmAAA", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pinned", None),
                "12D3KooWMEER": ("meerkat", "remote", None),
            }),
            _make_pin("QmBBB", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pinned", None),
                "12D3KooWMEER": ("meerkat", "remote", None),
            }),
        ]

        result = health(config=sample_config)

        assert result.status == "ok"
        assert result.exit_code == 0
        assert result.peers_total == 3
        assert result.peers_online == 3
        assert result.pins_total == 2
        assert result.pin_errors == []

        # Check per-node counts
        by_name = {n.name: n for n in result.nodes}
        assert by_name["nas"].pinned == 2
        assert by_name["nas"].remote == 0
        assert by_name["meerkat"].remote == 2
        assert by_name["meerkat"].pinned == 0

    @patch("community_cloud_storage.operations._get_client")
    def test_health_degraded(self, mock_get_client, sample_config):
        """All peers up but pin errors -> status degraded."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = _make_peers_ndjson([
            ("nas", "12D3KooWNAS", None),
            ("chll", "12D3KooWCHLL", None),
        ])
        mock_client._request.return_value = mock_response

        mock_client.pins.return_value = [
            _make_pin("QmAAA", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]

        result = health(config=sample_config)

        assert result.status == "degraded"
        assert result.exit_code == 1
        assert result.peers_online == 2
        assert len(result.pin_errors) == 1
        assert result.pin_errors[0]["node"] == "chll"
        assert "context canceled" in result.pin_errors[0]["error"]

    @patch("community_cloud_storage.operations._get_client")
    def test_health_error_peer_offline(self, mock_get_client, sample_config):
        """Peer offline -> status error."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = _make_peers_ndjson([
            ("nas", "12D3KooWNAS", None),
            ("chll", "12D3KooWCHLL", "dial backoff"),
        ])
        mock_client._request.return_value = mock_response

        mock_client.pins.return_value = []

        result = health(config=sample_config)

        assert result.status == "error"
        assert result.exit_code == 2
        assert result.peers_online == 1
        assert result.peers_total == 2

        by_name = {n.name: n for n in result.nodes}
        assert by_name["chll"].online is False
        assert by_name["chll"].status == "error"

    @patch("community_cloud_storage.operations._get_client")
    def test_health_json_output(self, mock_get_client, sample_config):
        """to_dict/to_json produce valid structure."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = _make_peers_ndjson([
            ("nas", "12D3KooWNAS", None),
        ])
        mock_client._request.return_value = mock_response
        mock_client.pins.return_value = []

        result = health(config=sample_config)
        d = result.to_dict()

        assert "status" in d
        assert "checked_at" in d
        assert d["peers"]["total"] == 1
        assert d["peers"]["online"] == 1
        assert d["peers"]["offline"] == 0
        assert d["pins"]["total"] == 0

        # Verify to_json is valid JSON
        import json
        parsed = json.loads(result.to_json())
        assert parsed["status"] == "ok"


class TestRepair:
    """Tests for repair() operation."""

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_no_broken_pins(self, mock_get_client, sample_config):
        """All pins healthy -> broken=0, exit_code=0."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmAAA", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pinned", None),
            }),
        ]

        result = repair(config=sample_config)

        assert result.broken == 0
        assert result.total_pins == 1
        assert result.exit_code == RC_REPAIR_CLEAN
        mock_client.recover.assert_not_called()

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_recoverable_pin(self, mock_get_client, sample_config):
        """Pin with error on one node, pinned on another -> recoverable."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmBROKEN", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]
        mock_client.recover.return_value = {}

        result = repair(config=sample_config)

        assert result.broken == 1
        assert result.recoverable == 1
        assert result.lost == 0
        assert result.recovered == 1
        assert result.exit_code == RC_REPAIR_FIXED
        mock_client.recover.assert_called_once_with("QmBROKEN")

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_lost_pin(self, mock_get_client, sample_config):
        """Pin with error on ALL nodes -> lost, no recovery attempted."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmLOST", {
                "12D3KooWNAS": ("nas", "pin_error", "context canceled"),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]

        result = repair(config=sample_config)

        assert result.broken == 1
        assert result.recoverable == 0
        assert result.lost == 1
        assert result.exit_code == RC_REPAIR_LOST
        mock_client.recover.assert_not_called()

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_mixed(self, mock_get_client, sample_config):
        """One recoverable + one lost -> exit_code=2 (lost trumps)."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmRECOVER", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
            _make_pin("QmLOST", {
                "12D3KooWNAS": ("nas", "error", "gone"),
                "12D3KooWCHLL": ("chll", "pin_error", "gone"),
            }),
        ]
        mock_client.recover.return_value = {}

        result = repair(config=sample_config)

        assert result.broken == 2
        assert result.recoverable == 1
        assert result.lost == 1
        assert result.recovered == 1
        assert result.exit_code == RC_REPAIR_LOST
        mock_client.recover.assert_called_once_with("QmRECOVER")

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_dry_run(self, mock_get_client, sample_config):
        """Dry run reports but does not recover."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmBROKEN", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]

        result = repair(config=sample_config, dry_run=True)

        assert result.broken == 1
        assert result.recoverable == 1
        assert result.dry_run is True
        mock_client.recover.assert_not_called()

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_recover_error_handled(self, mock_get_client, sample_config):
        """Recovery failure is caught, not propagated."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmBROKEN", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]
        mock_client.recover.side_effect = Exception("connection refused")

        result = repair(config=sample_config)

        assert result.recovered == 0
        assert result.recover_errors == 1
        assert result.broken_pins[0].recover_error == "connection refused"

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_pinning_not_lost(self, mock_get_client, sample_config):
        """Pin with error + pinning on another node -> recoverable, NOT lost."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmPINNING", {
                "12D3KooWNAS": ("nas", "pinning", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]
        mock_client.recover.return_value = {}

        result = repair(config=sample_config)

        assert result.broken == 1
        assert result.recoverable == 1
        assert result.lost == 0

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_pin_queued_not_lost(self, mock_get_client, sample_config):
        """Pin with error + pin_queued on another node -> recoverable, NOT lost."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmQUEUED", {
                "12D3KooWNAS": ("nas", "pin_queued", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]
        mock_client.recover.return_value = {}

        result = repair(config=sample_config)

        assert result.broken == 1
        assert result.recoverable == 1
        assert result.lost == 0

    @patch("community_cloud_storage.operations._get_client")
    def test_repair_json_output(self, mock_get_client, sample_config):
        """RepairResult.to_json() produces valid JSON with all keys."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            _make_pin("QmBROKEN", {
                "12D3KooWNAS": ("nas", "pinned", None),
                "12D3KooWCHLL": ("chll", "pin_error", "context canceled"),
            }),
        ]
        mock_client.recover.return_value = {}

        result = repair(config=sample_config)

        import json
        parsed = json.loads(result.to_json())
        assert "checked_at" in parsed
        assert parsed["total_pins"] == 1
        assert parsed["broken"] == 1
        assert parsed["recoverable"] == 1
        assert parsed["lost"] == 0
        assert parsed["recovered"] == 1
        assert parsed["dry_run"] is False
        assert len(parsed["broken_pins"]) == 1
        bp = parsed["broken_pins"][0]
        assert bp["cid"] == "QmBROKEN"
        assert bp["recoverable"] is True
        assert bp["recovered"] is True


class TestAddOrgMetadata:
    """Tests for add() setting org and size metadata on pins."""

    @patch("community_cloud_storage.operations.ClusterClient")
    def test_add_passes_org_and_size_metadata(self, mock_client_class, sample_config):
        """add() should pass metadata with org and size to client.add()."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.add.return_value = [
            {"name": "test.txt", "cid": "QmTEST", "size": 42},
        ]
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            path = Path(f.name)

        try:
            result = add(path, profile="hrdag", config=sample_config)
            assert result.ok

            # Verify metadata includes both org and size
            call_kwargs = mock_client.add.call_args[1]
            assert call_kwargs["metadata"]["org"] == "hrdag"
            assert "size" in call_kwargs["metadata"]
            # Size should be the file size as a string
            assert call_kwargs["metadata"]["size"] == str(path.stat().st_size)
        finally:
            path.unlink()

    @patch("community_cloud_storage.operations.ClusterClient")
    def test_add_orgB_metadata(self, mock_client_class, sample_config):
        """add() with orgB profile sets metadata org=orgB with size."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.add.return_value = [
            {"name": "test.txt", "cid": "QmTEST", "size": 42},
        ]
        mock_client.pin_status.return_value = {
            "cid": "QmTEST",
            "allocations": ["12D3KooWMEER", "12D3KooWCHLL"],
            "peer_map": {
                "12D3KooWMEER": {"peername": "meerkat", "status": "pinned", "error": ""},
                "12D3KooWCHLL": {"peername": "chll", "status": "pinned", "error": ""},
                "12D3KooWPeer3": {"peername": "peer3", "status": "pinned", "error": ""},
                "12D3KooWPeer4": {"peername": "peer4", "status": "pinned", "error": ""},
            },
            "replication_factor_min": 2,
            "replication_factor_max": 4,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test")
            path = Path(f.name)

        try:
            add(path, profile="orgB", config=sample_config)
            call_kwargs = mock_client.add.call_args[1]
            assert call_kwargs["metadata"]["org"] == "orgB"
            assert "size" in call_kwargs["metadata"]
        finally:
            path.unlink()


class TestTagPins:
    """Tests for tag_pins() migration operation (org + size metadata)."""

    @patch("community_cloud_storage.operations._get_dag_size")
    @patch("community_cloud_storage.operations._get_client")
    def test_tag_pins_tags_untagged(self, mock_get_client, mock_dag_size, sample_config):
        """tag_pins tags pins with both org and size metadata."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_dag_size.side_effect = [500000, 1000000]  # sizes for 2 pins

        mock_client.pins.return_value = [
            {
                "cid": "QmAAA", "name": "fileA",
                "allocations": ["12D3KooWNAS"],
                "metadata": None,
                "peer_map": {},
                "replication_factor_min": 2, "replication_factor_max": 3,
            },
            {
                "cid": "QmBBB", "name": "fileB",
                "allocations": ["12D3KooWNAS"],
                "metadata": None,
                "peer_map": {},
                "replication_factor_min": 2, "replication_factor_max": 3,
            },
        ]
        mock_client.pin.return_value = {}

        result = tag_pins(profile="hrdag", config=sample_config)

        assert result["total"] == 2
        assert result["tagged"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert mock_client.pin.call_count == 2

        # Verify both org and size metadata were set
        call1 = mock_client.pin.call_args_list[0][1]
        assert call1["metadata"] == {"org": "hrdag", "size": "500000"}
        call2 = mock_client.pin.call_args_list[1][1]
        assert call2["metadata"] == {"org": "hrdag", "size": "1000000"}

    @patch("community_cloud_storage.operations._get_dag_size")
    @patch("community_cloud_storage.operations._get_client")
    def test_tag_pins_skips_fully_tagged(self, mock_get_client, mock_dag_size, sample_config):
        """tag_pins skips pins that already have both org and size."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.pins.return_value = [
            {
                "cid": "QmAAA", "name": "fileA",
                "allocations": ["12D3KooWNAS"],
                "metadata": {"org": "hrdag", "size": "500000"},
                "peer_map": {},
                "replication_factor_min": 2, "replication_factor_max": 3,
            },
        ]

        result = tag_pins(profile="hrdag", config=sample_config)

        assert result["total"] == 1
        assert result["tagged"] == 0
        assert result["skipped"] == 1
        mock_client.pin.assert_not_called()
        mock_dag_size.assert_not_called()

    @patch("community_cloud_storage.operations._get_dag_size")
    @patch("community_cloud_storage.operations._get_client")
    def test_tag_pins_adds_missing_size(self, mock_get_client, mock_dag_size, sample_config):
        """tag_pins re-pins when org is correct but size is missing."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_dag_size.return_value = 750000

        mock_client.pins.return_value = [
            {
                "cid": "QmAAA", "name": "fileA",
                "allocations": ["12D3KooWNAS"],
                "metadata": {"org": "hrdag"},
                "peer_map": {},
                "replication_factor_min": 2, "replication_factor_max": 3,
            },
        ]
        mock_client.pin.return_value = {}

        result = tag_pins(profile="hrdag", config=sample_config)

        assert result["total"] == 1
        assert result["tagged"] == 1
        assert result["skipped"] == 0
        call_kwargs = mock_client.pin.call_args[1]
        assert call_kwargs["metadata"] == {"org": "hrdag", "size": "750000"}

    @patch("community_cloud_storage.operations._get_dag_size")
    @patch("community_cloud_storage.operations._get_client")
    def test_tag_pins_dry_run(self, mock_get_client, mock_dag_size, sample_config):
        """tag_pins dry run reports but doesn't modify."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_dag_size.return_value = 500000

        mock_client.pins.return_value = [
            {
                "cid": "QmAAA", "name": "fileA",
                "allocations": ["12D3KooWNAS"],
                "metadata": None,
                "peer_map": {},
                "replication_factor_min": 2, "replication_factor_max": 3,
            },
        ]

        result = tag_pins(profile="hrdag", config=sample_config, dry_run=True)

        assert result["total"] == 1
        assert result["tagged"] == 1  # would tag
        assert result["dry_run"] is True
        mock_client.pin.assert_not_called()

    @patch("community_cloud_storage.operations._get_dag_size")
    @patch("community_cloud_storage.operations._get_client")
    def test_tag_pins_preserves_name(self, mock_get_client, mock_dag_size, sample_config):
        """tag_pins preserves existing pin name when re-pinning."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_dag_size.return_value = 999999

        mock_client.pins.return_value = [
            {
                "cid": "QmAAA", "name": "commit_2026-01-21",
                "allocations": ["12D3KooWNAS"],
                "metadata": None,
                "peer_map": {},
                "replication_factor_min": 2, "replication_factor_max": 3,
            },
        ]
        mock_client.pin.return_value = {}

        tag_pins(profile="hrdag", config=sample_config)

        call_kwargs = mock_client.pin.call_args[1]
        assert call_kwargs["name"] == "commit_2026-01-21"
        assert call_kwargs["metadata"]["size"] == "999999"

    @patch("community_cloud_storage.operations._get_dag_size")
    @patch("community_cloud_storage.operations._get_client")
    def test_tag_pins_size_error_still_tags_org(self, mock_get_client, mock_dag_size, sample_config):
        """If gateway size lookup fails, still tags org without size."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_dag_size.return_value = None  # gateway error

        mock_client.pins.return_value = [
            {
                "cid": "QmAAA", "name": "fileA",
                "allocations": ["12D3KooWNAS"],
                "metadata": None,
                "peer_map": {},
                "replication_factor_min": 2, "replication_factor_max": 3,
            },
        ]
        mock_client.pin.return_value = {}

        result = tag_pins(profile="hrdag", config=sample_config)

        assert result["tagged"] == 1
        call_kwargs = mock_client.pin.call_args[1]
        assert call_kwargs["metadata"] == {"org": "hrdag"}
