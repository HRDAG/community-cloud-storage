"""
HTTP client for IPFS Cluster REST API.

This module provides direct HTTP access to the IPFS Cluster API,
eliminating the need for ipfs-cluster-ctl binary.

API Reference: https://ipfscluster.io/documentation/reference/api/

Debug logging:
    Enable with: CCS_DEBUG=1 or by setting log level to DEBUG
    Example: CCS_DEBUG=1 ccs add --profile hrdag /path/to/file
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests_toolbelt import MultipartEncoder

# HACKY WORKAROUND: Use curl subprocess for large uploads
# Python's requests library (even with MultipartEncoder) stalls on multipart
# uploads with >300 files - TCP send buffer fills to ~2.5MB and hangs indefinitely.
# Curl handles the same uploads fine. This is a workaround, not a proper fix.
# TODO: Investigate root cause - possibly requests not using chunked encoding,
# or MultipartEncoder buffering despite claiming to stream.
CURL_THRESHOLD_FILES = 250

# Configure logger for this module
logger = logging.getLogger(__name__)

# Enable debug logging via environment variable
if os.environ.get("CCS_DEBUG"):
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    logger.setLevel(logging.DEBUG)


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

        # Debug logging for request
        logger.debug(f"Request: {method} {url}")
        if "files" in kwargs:
            file_info = [(name, getattr(f[1], 'name', str(f[1])[:50]))
                         for name, f in (kwargs["files"] if isinstance(kwargs["files"], list)
                                         else kwargs["files"].items())]
            logger.debug(f"Request files: {file_info}")

        response = self.session.request(method, url, **kwargs)

        # Debug logging for response
        logger.debug(f"Response status: {response.status_code}")
        logger.debug(f"Response headers: {dict(response.headers)}")
        # Truncate body for logging (first 2000 chars)
        body_preview = response.text[:2000] if response.text else "(empty)"
        logger.debug(f"Response body: {body_preview}")

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
        Note: Cluster API returns NDJSON (newline-delimited JSON).
        """
        response = self._request("GET", "/pins")
        if response.status_code == 204 or not response.text:
            return []
        # Parse NDJSON - each line is a separate JSON object
        results = []
        for line in response.text.strip().split('\n'):
            if line:
                results.append(json.loads(line))
        return results

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

    def add(
        self,
        path: Path,
        recursive: bool = True,
        name: str = None,
        allocations: list[str] = None,
        local: bool = True,
    ) -> list:
        """
        Add a file or directory to the cluster.

        Args:
            path: Path to file or directory
            recursive: If True and path is directory, add recursively
            name: Pin name for cluster metadata (defaults to filename/dirname)
            allocations: List of peer IDs for explicit allocation (optional)
            local: If True, always include the connected node in allocations
                   (default True - ensures primary node is allocated)

        Returns:
            List of dicts with 'name', 'cid', and 'allocations' for each added item.
            Last item is the root CID. The 'allocations' field contains the actual
            peer IDs assigned by the cluster (may differ from requested allocations).
        """
        if name is None:
            name = path.name

        logger.debug(f"add() called: path={path}, name={name}, allocations={allocations}, local={local}")

        if path.is_file():
            return self._add_file(path, name, allocations, local)
        elif path.is_dir() and recursive:
            # Count files to decide which method to use
            file_count = sum(1 for f in path.rglob("*") if f.is_file())
            if file_count > CURL_THRESHOLD_FILES:
                logger.info(f"Using curl for {file_count} files (threshold: {CURL_THRESHOLD_FILES})")
                return self._add_directory_curl(path, name, allocations, local)
            else:
                return self._add_directory(path, name, allocations, local)
        else:
            raise ValueError(f"Path {path} is not a file or directory")

    def _build_add_params(
        self, name: str, allocations: list[str] = None, local: bool = True
    ) -> str:
        """Build query string for /add endpoint.

        Uses buffered mode (stream-channels=false) for reliable error handling.
        Errors are returned as proper HTTP status codes with JSON body instead
        of being hidden in HTTP trailer headers.
        """
        from urllib.parse import urlencode

        params = {
            "name": name,
            "stream-channels": "false",  # Enable buffered mode for reliable errors
        }

        if allocations:
            params["allocations"] = ",".join(allocations)

        if local:
            params["local"] = "true"

        return urlencode(params)

    def _add_file(
        self, path: Path, name: str, allocations: list[str] = None, local: bool = True
    ) -> list:
        """Add a single file."""
        query = self._build_add_params(name, allocations, local)
        logger.debug(f"_add_file: query string = {query}")

        with open(path, "rb") as f:
            files = {"file": (path.name, f)}
            response = self._request("POST", f"/add?{query}", files=files)

        # Response is newline-delimited JSON
        results = []
        for line in response.text.strip().split("\n"):
            if line:
                entry = json.loads(line)
                results.append(entry)
                logger.debug(f"_add_file: parsed entry = {entry}")

        logger.debug(f"_add_file: total entries = {len(results)}")
        return results

    def _add_directory(
        self, path: Path, name: str, allocations: list[str] = None, local: bool = True
    ) -> list:
        """Add a directory recursively using streaming multipart form.

        Uses MultipartEncoder from requests_toolbelt to stream data
        instead of buffering entire form in memory. This is critical
        for large directories (>300 files or >500MB).
        """
        # Collect all files with their relative paths
        files_to_add = []
        base_path = path.parent

        for file_path in path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(base_path)
                files_to_add.append((file_path, str(rel_path)))

        logger.debug(f"_add_directory: found {len(files_to_add)} files")

        query = self._build_add_params(name, allocations, local)
        logger.debug(f"_add_directory: query string = {query}")

        # Build streaming multipart encoder
        # Each field is ("file", (filename, file_handle, content_type))
        file_handles = []
        fields = []

        try:
            for file_path, rel_path in files_to_add:
                fh = open(file_path, "rb")
                file_handles.append(fh)
                fields.append(("file", (rel_path, fh, "application/octet-stream")))

            # Create streaming encoder
            encoder = MultipartEncoder(fields=fields)
            logger.debug(f"_add_directory: encoder content_length = {encoder.len}")

            # Make request with streaming body
            url = f"{self.base_url}/add?{query}"
            response = self.session.post(
                url,
                data=encoder,
                headers={"Content-Type": encoder.content_type},
            )

            # Check for errors
            if response.status_code == 401:
                raise ClusterAPIError("Unauthorized: check basic auth credentials", 401)
            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    msg = error_data.get("message", response.text)
                except Exception:
                    msg = response.text
                raise ClusterAPIError(msg, response.status_code)

        finally:
            for fh in file_handles:
                fh.close()

        # Parse newline-delimited JSON response
        results = []
        for line in response.text.strip().split("\n"):
            if line:
                entry = json.loads(line)
                results.append(entry)
                logger.debug(f"_add_directory: parsed entry = {entry}")

        logger.debug(f"_add_directory: total entries = {len(results)}")
        return results

    def _add_directory_curl(
        self, path: Path, name: str, allocations: list[str] = None, local: bool = True
    ) -> list:
        """Add a directory using curl subprocess.

        Python's requests library buffers multipart forms in memory and stalls
        on large uploads (>300 files). Curl handles streaming correctly.
        """
        # Collect all files with their relative paths
        files_to_add = []
        base_path = path.parent

        for file_path in path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(base_path)
                files_to_add.append((file_path, str(rel_path)))

        logger.debug(f"_add_directory_curl: found {len(files_to_add)} files")

        # Build query string
        query = self._build_add_params(name, allocations, local)

        # Build curl command
        url = f"{self.base_url}/add?{query}"
        cmd = ["curl", "-s", "-X", "POST"]

        # Add auth if configured
        if self.auth:
            cmd.extend(["-u", f"{self.auth[0]}:{self.auth[1]}"])

        # Add each file with -F flag
        for file_path, rel_path in files_to_add:
            cmd.extend(["-F", f"file=@{file_path};filename={rel_path}"])

        cmd.append(url)

        logger.debug(f"_add_directory_curl: executing curl with {len(files_to_add)} files")
        logger.debug(f"_add_directory_curl: url = {url}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout for very large uploads
            )

            logger.debug(f"_add_directory_curl: returncode = {result.returncode}")
            logger.debug(f"_add_directory_curl: stdout len = {len(result.stdout)}")
            logger.debug(f"_add_directory_curl: stderr = {result.stderr[:200] if result.stderr else '(empty)'}")
            if result.stdout:
                logger.debug(f"_add_directory_curl: stdout first 500 = {result.stdout[:500]}")

            if result.returncode != 0:
                raise ClusterAPIError(
                    f"curl failed: {result.stderr}",
                    status_code=result.returncode
                )

            # Check for HTTP errors in response
            if "unauthorized" in result.stdout.lower():
                raise ClusterAPIError("Unauthorized: check basic auth credentials", 401)

            # Parse NDJSON response
            results = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    entry = json.loads(line)
                    results.append(entry)
                    logger.debug(f"_add_directory_curl: parsed entry = {entry}")

            logger.debug(f"_add_directory_curl: total entries = {len(results)}")
            return results

        except subprocess.TimeoutExpired:
            raise ClusterAPIError("curl timeout after 1 hour", status_code=408)
        except json.JSONDecodeError as e:
            raise ClusterAPIError(f"Invalid JSON response: {e}", status_code=500)


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
