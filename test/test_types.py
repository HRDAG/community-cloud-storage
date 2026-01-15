# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# test/test_types.py

"""Tests for CCS type definitions."""

from datetime import datetime, timezone

import pytest

from community_cloud_storage.types import (
    AddResult,
    CIDEntry,
    PeerInfo,
    PeerPinStatus,
    PinStatus,
    RC_SUCCESS,
    RC_FAILED,
)


class TestCIDEntry:
    def test_to_dict(self):
        entry = CIDEntry(path="file.txt", cid="Qm123", size=100, is_root=False)
        d = entry.to_dict()
        assert d == {"path": "file.txt", "cid": "Qm123", "size": 100, "is_root": False, "error": None}

    def test_from_dict(self):
        d = {"path": "dir/", "cid": "Qm456", "size": 0, "is_root": True}
        entry = CIDEntry.from_dict(d)
        assert entry.path == "dir/"
        assert entry.cid == "Qm456"
        assert entry.is_root is True

    def test_from_ipfs_entry(self):
        raw = {"name": "archive/file.txt", "cid": "Qm789", "size": 500}
        entry = CIDEntry.from_ipfs_entry(raw, is_root=False)
        assert entry.path == "archive/file.txt"
        assert entry.cid == "Qm789"
        assert entry.size == 500
        assert entry.is_root is False

    def test_from_ipfs_entry_root(self):
        raw = {"name": "archive", "cid": "QmABC", "size": 231}
        entry = CIDEntry.from_ipfs_entry(raw, is_root=True)
        assert entry.is_root is True

    def test_round_trip(self):
        original = CIDEntry(path="test.txt", cid="Qm123", size=42, is_root=False)
        restored = CIDEntry.from_dict(original.to_dict())
        assert original.path == restored.path
        assert original.cid == restored.cid
        assert original.size == restored.size
        assert original.is_root == restored.is_root

    def test_ok_success(self):
        entry = CIDEntry(path="file.txt", cid="Qm123", size=100)
        assert entry.ok is True

    def test_ok_with_error(self):
        entry = CIDEntry(path="file.txt", cid="", size=0, error="Failed to add")
        assert entry.ok is False

    def test_ok_empty_cid(self):
        entry = CIDEntry(path="file.txt", cid="", size=0)
        assert entry.ok is False


class TestAddResult:
    @pytest.fixture
    def sample_result(self):
        return AddResult(
            root_cid="QmRoot",
            root_path="/path/to/archive",
            entries=[
                CIDEntry(path="archive/file1.txt", cid="Qm1", size=100, is_root=False),
                CIDEntry(path="archive/file2.txt", cid="Qm2", size=200, is_root=False),
                CIDEntry(path="archive", cid="QmRoot", size=300, is_root=True),
            ],
            allocations=["12D3KooW1", "12D3KooW2"],
            profile="hrdag",
            added_at=datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc),
            cluster_host="nas",
            returncode=RC_SUCCESS,
            error=None,
        )

    def test_to_dict(self, sample_result):
        d = sample_result.to_dict()
        assert d["root_cid"] == "QmRoot"
        assert d["profile"] == "hrdag"
        assert len(d["entries"]) == 3
        assert d["returncode"] == RC_SUCCESS
        assert d["allocations"] == ["12D3KooW1", "12D3KooW2"]

    def test_to_json(self, sample_result):
        json_str = sample_result.to_json()
        assert '"root_cid": "QmRoot"' in json_str
        assert '"profile": "hrdag"' in json_str

    def test_from_dict(self, sample_result):
        d = sample_result.to_dict()
        restored = AddResult.from_dict(d)
        assert restored.root_cid == sample_result.root_cid
        assert restored.profile == sample_result.profile
        assert len(restored.entries) == len(sample_result.entries)

    def test_from_json(self, sample_result):
        json_str = sample_result.to_json()
        restored = AddResult.from_json(json_str)
        assert restored.root_cid == sample_result.root_cid

    def test_root_entry(self, sample_result):
        root = sample_result.root_entry()
        assert root is not None
        assert root.cid == "QmRoot"
        assert root.is_root is True

    def test_child_entries(self, sample_result):
        children = sample_result.child_entries()
        assert len(children) == 2
        assert all(not e.is_root for e in children)

    def test_total_size(self, sample_result):
        # Total size is sum of child entries (excludes root to avoid double-counting)
        assert sample_result.total_size() == 300  # 100 + 200

    def test_round_trip(self, sample_result):
        restored = AddResult.from_json(sample_result.to_json())
        assert restored.root_cid == sample_result.root_cid
        assert restored.root_path == sample_result.root_path
        assert restored.profile == sample_result.profile
        assert restored.returncode == sample_result.returncode
        assert restored.ok == sample_result.ok
        assert len(restored.entries) == len(sample_result.entries)

    def test_ok_success(self, sample_result):
        assert sample_result.ok is True
        assert sample_result.complete is True  # backward compat alias

    def test_ok_failed(self):
        result = AddResult(
            root_cid="",
            root_path="/path/to/file",
            entries=[],
            allocations=[],
            profile="hrdag",
            added_at=datetime(2026, 1, 14, tzinfo=timezone.utc),
            cluster_host="nas",
            returncode=RC_FAILED,
            error="Connection refused",
        )
        assert result.ok is False
        assert result.complete is False


class TestPeerInfo:
    def test_to_dict(self):
        peer = PeerInfo(
            name="nas",
            peer_id="12D3KooW123",
            addresses=["/ip4/100.64.0.31/tcp/9096"],
            error=None,
        )
        d = peer.to_dict()
        assert d["name"] == "nas"
        assert d["peer_id"] == "12D3KooW123"

    def test_from_dict(self):
        d = {"name": "meerkat", "peer_id": "12D3KooW456", "addresses": [], "error": None}
        peer = PeerInfo.from_dict(d)
        assert peer.name == "meerkat"

    def test_from_cluster_peer(self):
        raw = {
            "peername": "nas",
            "id": "12D3KooW789",
            "addresses": ["/ip4/127.0.0.1/tcp/9096"],
            "error": "",
        }
        peer = PeerInfo.from_cluster_peer(raw)
        assert peer.name == "nas"
        assert peer.peer_id == "12D3KooW789"
        assert peer.error is None  # empty string -> None


class TestPinStatus:
    @pytest.fixture
    def sample_status(self):
        return PinStatus(
            cid="QmTest",
            name="test.txt",
            allocations=["12D3A", "12D3B"],
            peer_map={
                "12D3A": PeerPinStatus(peername="nas", status="pinned", error=None),
                "12D3B": PeerPinStatus(peername="meerkat", status="pinning", error=None),
            },
            replication_factor_min=2,
            replication_factor_max=3,
            created=datetime(2026, 1, 14, tzinfo=timezone.utc),
        )

    def test_to_dict(self, sample_status):
        d = sample_status.to_dict()
        assert d["cid"] == "QmTest"
        assert "nas" in str(d["peer_map"])

    def test_to_json(self, sample_status):
        json_str = sample_status.to_json()
        assert "QmTest" in json_str

    def test_is_fully_pinned_false(self, sample_status):
        assert sample_status.is_fully_pinned() is False  # meerkat is "pinning"

    def test_is_fully_pinned_true(self):
        status = PinStatus(
            cid="Qm",
            name=None,
            allocations=["A"],
            peer_map={"A": PeerPinStatus(peername="n", status="pinned", error=None)},
            replication_factor_min=1,
            replication_factor_max=1,
        )
        assert status.is_fully_pinned() is True

    def test_pinned_count(self, sample_status):
        assert sample_status.pinned_count() == 1

    def test_pinned_peers(self, sample_status):
        assert sample_status.pinned_peers() == ["nas"]

    def test_from_cluster_status(self):
        raw = {
            "cid": "QmXYZ",
            "name": "archive",
            "allocations": ["peer1"],
            "peer_map": {
                "peer1": {"peername": "nas", "status": "pinned", "error": ""},
            },
            "replication_factor_min": 2,
            "replication_factor_max": 3,
            "created": "2026-01-14T00:00:00Z",
        }
        status = PinStatus.from_cluster_status(raw)
        assert status.cid == "QmXYZ"
        assert status.pinned_count() == 1
