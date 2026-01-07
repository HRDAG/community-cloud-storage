import os
import re
import socket
from unittest.mock import Mock

import pytest
import yaml

from community_cloud_storage import compose


def test_create(tmp_path):
    compose_path = tmp_path / "compose.yml"

    compose.create(
        output=compose_path.open("w"),
        cluster_peername="bootstrap",
        ts_authkey="abc123def",
    )

    assert compose_path.is_file()
    doc = yaml.load(compose_path.open("r"), Loader=yaml.Loader)

    assert doc["name"] == "community-cloud-storage"
    assert doc["services"]["tailscale"]["hostname"] == "bootstrap"
    assert doc["services"]["tailscale"]["environment"]["TS_AUTHKEY"] == "abc123def"

    m = re.match(
        "IPFS_SWARM_KEY=/key/swarm/psk/1.0.0/\n/base16/\n(.+)",
        doc["services"]["ipfs"]["environment"][0],
        flags=re.MULTILINE,
    )
    assert m
    assert len(m.group(1)) == 64

    assert len(doc["services"]["ipfs-cluster"]["environment"]["CLUSTER_SECRET"]) == 64


def test_clone(tmp_path, monkeypatch):
    # generate some known secrets so we can test that they show correctly in the
    # generated compose file
    ipfs_swarm_key = os.urandom(32).hex()
    cluster_secret = os.urandom(32).hex()

    # first create a compose file
    compose_path = tmp_path / "compose.yml"
    compose.create(
        output=compose_path.open("w"),
        cluster_peername="bootstrap",
        ts_authkey="abc123def",
        ipfs_swarm_key=ipfs_swarm_key,
        cluster_secret=cluster_secret,
    )
    assert compose_path.is_file()

    # mock the lookup of a hostname
    monkeypatch.setattr(socket, "gethostbyname", lambda _: "192.168.1.15")

    # mock the HTTP clients that clone() uses to get peer IDs
    mock_ipfs_client = Mock()
    mock_ipfs_client.id.return_value = {
        "ID": "12D3KooWRy3uoprJ3ijtQHqwS3mUkchBXeqmwk9HhLQYwif9hD2C"
    }

    mock_cluster_client = Mock()
    mock_cluster_client.id.return_value = {
        "id": "12D3KooWHuxBMn6M5dqwhFpaCRpj5BXoomEq8rncbJeXpLG12qs2"
    }

    monkeypatch.setattr(compose, "_get_ipfs_client", lambda host: mock_ipfs_client)
    monkeypatch.setattr(
        compose, "_get_cluster_client", lambda host, basic_auth=None: mock_cluster_client
    )

    # create a clone of the compose file configured for a new node
    new_compose_path = tmp_path / "clone-compose.yml"
    clone_authkey = "clone_xyz789"

    compose.clone(
        input=compose_path.open("r"),
        output=new_compose_path.open("w"),
        cluster_peername="clone",
        bootstrap_host="bootstrap",
        ts_authkey=clone_authkey,
    )

    doc = yaml.load(new_compose_path.open("r"), Loader=yaml.Loader)

    assert doc["name"] == "community-cloud-storage"
    assert doc["services"]["tailscale"]["hostname"] == "clone"
    assert doc["services"]["tailscale"]["environment"]["TS_AUTHKEY"] == clone_authkey
    assert (
        doc["services"]["ipfs-cluster"]["environment"]["CLUSTER_SECRET"]
        == cluster_secret
    )

    assert (
        doc["services"]["ipfs"]["environment"][0]
        == "IPFS_BOOTSTRAP=/ip4/192.168.1.15/tcp/4001/ipfs/12D3KooWRy3uoprJ3ijtQHqwS3mUkchBXeqmwk9HhLQYwif9hD2C"
    )

    m = re.match(
        "IPFS_SWARM_KEY=/key/swarm/psk/1.0.0/\n/base16/\n(.+)",
        doc["services"]["ipfs"]["environment"][1],
        flags=re.MULTILINE,
    )
    assert m.group(1) == ipfs_swarm_key

    assert (
        doc["services"]["ipfs-cluster"]["environment"]["CLUSTER_PEERADDRESSES"]
        == "/ip4/192.168.1.15/tcp/9096/ipfs/12D3KooWHuxBMn6M5dqwhFpaCRpj5BXoomEq8rncbJeXpLG12qs2"
    )


def test_get_env_value():
    env_list = ["FOO=bar", "IPFS_SWARM_KEY=/key/swarm/psk/1.0.0/\n/base16/\nabc123"]
    assert compose._get_env_value(env_list, "FOO=") == "FOO=bar"
    assert compose._get_env_value(env_list, "IPFS_SWARM_KEY=").startswith(
        "IPFS_SWARM_KEY="
    )
    with pytest.raises(ValueError, match="No environment variable"):
        compose._get_env_value(env_list, "MISSING=")


def test_run_error_handling():
    with pytest.raises(RuntimeError, match="Command failed"):
        compose.run("false")


def test_add_returns_manifest(tmp_path, monkeypatch):
    # mock the cluster client
    mock_client = Mock()
    mock_client.add.return_value = [
        {"name": "file.txt", "cid": "QmTestCid123"},
    ]
    monkeypatch.setattr(
        compose, "_get_cluster_client", lambda host, basic_auth=None: mock_client
    )

    # test adding a file
    file_path = tmp_path / "file.txt"
    file_path.write_text("test content")

    result = compose.add(file_path, host="test-host")

    # verify client.add was called with the path
    mock_client.add.assert_called_once_with(file_path, recursive=True)

    # verify manifest structure
    assert result["root_cid"] == "QmTestCid123"
    assert result["root_path"] == "file.txt"
    assert result["cluster_peername"] == "test-host"
    assert result["complete"] is True
    assert len(result["entries"]) == 1
    assert result["entries"][0]["cid"] == "QmTestCid123"


def test_add_directory(tmp_path, monkeypatch):
    # mock the cluster client
    mock_client = Mock()
    mock_client.add.return_value = [
        {"name": "subdir/a.txt", "cid": "QmCidA"},
        {"name": "subdir/b.txt", "cid": "QmCidB"},
        {"name": "subdir", "cid": "QmRootCid"},
    ]
    monkeypatch.setattr(
        compose, "_get_cluster_client", lambda host, basic_auth=None: mock_client
    )

    # test adding a directory
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "a.txt").write_text("a")
    (subdir / "b.txt").write_text("b")

    result = compose.add(subdir, host="test-host")

    # verify client.add was called
    mock_client.add.assert_called_once_with(subdir, recursive=True)

    # verify manifest has all entries with root CID last
    assert result["root_cid"] == "QmRootCid"
    assert result["complete"] is True
    assert len(result["entries"]) == 3


def test_add_error_handling(tmp_path, monkeypatch):
    # mock the cluster client to raise an error
    mock_client = Mock()
    mock_client.add.side_effect = Exception("Connection refused")
    monkeypatch.setattr(
        compose, "_get_cluster_client", lambda host, basic_auth=None: mock_client
    )

    file_path = tmp_path / "file.txt"
    file_path.write_text("test")

    result = compose.add(file_path, host="test-host")

    # verify error is captured in manifest
    assert result["complete"] is False
    assert "Connection refused" in result["error"]
    assert result["entries"] == []
