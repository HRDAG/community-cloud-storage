"""
HTTP client for IPFS Cluster REST API.

This module provides direct HTTP access to the IPFS Cluster API,
eliminating the need for ipfs-cluster-ctl binary.

API Reference: https://ipfscluster.io/documentation/reference/api/
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import requests


class ClusterAPIError(Exception):
    """Raised when cluster API returns an error."""

    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ClusterClient:
    """HTTP client for IPFS Cluster REST API."""

    def __init__(self, host: str, port: int = 9094, basic_auth: tuple = None):
        """
        Initialize cluster client.

        Args:
            host: Hostname or IP of cluster node
            port: Cluster API port (default 9094)
            basic_auth: Tuple of (username, password) or None
        """
        self.base_url = f"http://{host}:{port}"
        self.auth = basic_auth
        self.session = requests.Session()
        if basic_auth:
            self.session.auth = basic_auth

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make HTTP request to cluster API."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(method, url, **kwargs)

        if response.status_code == 401:
            raise ClusterAPIError("Unauthorized: check basic auth credentials", 401)
        if response.status_code >= 400:
            try:
                error_data = response.json()
                msg = error_data.get("message", response.text)
            except Exception:
                msg = response.text
            raise ClusterAPIError(msg, response.status_code)

        return response

    def id(self) -> dict:
        """
        Get cluster peer information.

        Returns dict with: id, addresses, cluster_peers, version, ipfs, peername
        """
        response = self._request("GET", "/id")
        return response.json()

    def pins(self) -> list:
        """
        List all pinned CIDs.

        Returns list of pin status objects.
        """
        response = self._request("GET", "/pins")
        if response.status_code == 204 or not response.text:
            return []
        return response.json()

    def pin_status(self, cid: str) -> dict:
        """
        Get status of a specific CID.

        Returns dict with pin status across all peers.
        """
        response = self._request("GET", f"/pins/{cid}")
        return response.json()

    def unpin(self, cid: str) -> dict:
        """
        Remove a pin from the cluster.

        Returns the removed pin info.
        """
        response = self._request("DELETE", f"/pins/{cid}")
        return response.json()

    def add(self, path: Path, recursive: bool = True, name: str = None) -> list:
        """
        Add a file or directory to the cluster.

        Args:
            path: Path to file or directory
            recursive: If True and path is directory, add recursively
            name: Pin name for cluster metadata (defaults to filename/dirname)

        Returns:
            List of dicts with 'name' and 'cid' for each added item.
            Last item is the root CID.
        """
        if name is None:
            name = path.name

        if path.is_file():
            return self._add_file(path, name)
        elif path.is_dir() and recursive:
            return self._add_directory(path, name)
        else:
            raise ValueError(f"Path {path} is not a file or directory")

    def _add_file(self, path: Path, name: str) -> list:
        """Add a single file."""
        with open(path, "rb") as f:
            files = {"file": (path.name, f)}
            response = self._request("POST", f"/add?name={name}", files=files)

        # Response is newline-delimited JSON
        results = []
        for line in response.text.strip().split("\n"):
            if line:
                import json
                results.append(json.loads(line))
        return results

    def _add_directory(self, path: Path, name: str) -> list:
        """Add a directory recursively using multipart form."""
        # Collect all files with their relative paths
        files_to_add = []
        base_path = path.parent

        for file_path in path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(base_path)
                files_to_add.append((file_path, str(rel_path)))

        # Build multipart form with all files
        # IPFS Cluster expects files with path info in the filename
        files = []
        file_handles = []

        try:
            for file_path, rel_path in files_to_add:
                fh = open(file_path, "rb")
                file_handles.append(fh)
                files.append(("file", (rel_path, fh)))

            response = self._request("POST", f"/add?name={name}", files=files)
        finally:
            for fh in file_handles:
                fh.close()

        # Parse newline-delimited JSON response
        results = []
        for line in response.text.strip().split("\n"):
            if line:
                import json
                results.append(json.loads(line))

        return results


class IPFSClient:
    """HTTP client for IPFS (kubo) API."""

    def __init__(self, host: str, port: int = 5001):
        """
        Initialize IPFS client.

        Args:
            host: Hostname or IP of IPFS node
            port: IPFS API port (default 5001)
        """
        self.base_url = f"http://{host}:{port}/api/v0"
        self.session = requests.Session()

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make HTTP request to IPFS API."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(method, url, **kwargs)

        if response.status_code >= 400:
            try:
                error_data = response.json()
                msg = error_data.get("Message", response.text)
            except Exception:
                msg = response.text
            raise ClusterAPIError(msg, response.status_code)

        return response

    def id(self) -> dict:
        """
        Get IPFS peer information.

        Returns dict with: ID, PublicKey, Addresses, AgentVersion, etc.
        """
        response = self._request("POST", "/id")
        return response.json()

    def cat(self, cid: str) -> bytes:
        """
        Get file contents by CID.

        Returns file content as bytes.
        """
        response = self._request("POST", f"/cat?arg={cid}")
        return response.content

    def get(self, cid: str, output: Path) -> None:
        """
        Download file or directory by CID.

        Writes to output path.
        """
        response = self._request("POST", f"/get?arg={cid}", stream=True)

        # Response is a tar archive
        import tarfile
        import io

        tar_data = io.BytesIO(response.content)
        with tarfile.open(fileobj=tar_data, mode="r") as tar:
            tar.extractall(path=output.parent)


def create_manifest(
    path: Path,
    cluster_peername: str,
    entries: list,
    complete: bool,
    error: str = None,
) -> dict:
    """
    Create a CID manifest dict.

    Args:
        path: Original path that was added
        cluster_peername: Cluster node used
        entries: List of {name, cid} dicts from add
        complete: Whether add fully succeeded
        error: Error message if failed

    Returns:
        Manifest dict ready for JSON serialization
    """
    manifest = {
        "root_cid": entries[-1]["cid"] if entries else None,
        "root_path": path.name,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "cluster_peername": cluster_peername,
        "entries": [{"path": e.get("name", ""), "cid": e.get("cid", "")} for e in entries],
        "complete": complete,
    }
    if error:
        manifest["error"] = error
    return manifest
