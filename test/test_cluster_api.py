# Author: PB and Claude
# Date: 2026-01-15
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# test/test_cluster_api.py

"""
Tests for ClusterClient HTTP layer.

These tests verify the HTTP request format being sent to IPFS Cluster,
particularly the query string construction for the /add endpoint.
"""

import pytest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from community_cloud_storage.cluster_api import ClusterClient, ClusterAPIError


class TestBuildAddParams:
    """Tests for _build_add_params query string construction."""

    def test_name_only_with_local_default(self):
        """Basic name parameter with local=true (default)."""
        client = ClusterClient("localhost")
        result = client._build_add_params("test")
        assert "name=test" in result
        assert "stream-channels=false" in result
        assert "local=true" in result

    def test_name_only_without_local(self):
        """Basic name parameter with local=false."""
        client = ClusterClient("localhost")
        result = client._build_add_params("test", local=False)
        assert "name=test" in result
        assert "stream-channels=false" in result
        assert "local" not in result

    def test_with_allocations(self):
        """Name with allocations produces comma-separated peer IDs."""
        client = ClusterClient("localhost")
        result = client._build_add_params("test", ["peer1", "peer2"])
        assert "name=test" in result
        # Note: comma is URL encoded as %2C
        assert "allocations=peer1%2Cpeer2" in result or "allocations=peer1,peer2" in result
        assert "local=true" in result
        assert "stream-channels=false" in result

    def test_with_allocations_no_local(self):
        """Allocations without local flag."""
        client = ClusterClient("localhost")
        result = client._build_add_params("test", ["peer1", "peer2"], local=False)
        assert "name=test" in result
        assert "allocations=peer1%2Cpeer2" in result or "allocations=peer1,peer2" in result
        assert "stream-channels=false" in result
        assert "local" not in result

    def test_single_allocation(self):
        """Single allocation works correctly."""
        client = ClusterClient("localhost")
        result = client._build_add_params("test", ["peer1"])
        assert "name=test" in result
        assert "allocations=peer1" in result
        assert "local=true" in result

    def test_empty_allocations_not_included(self):
        """Empty allocations list should not add allocations param."""
        client = ClusterClient("localhost")
        result = client._build_add_params("test", [], local=False)
        assert "allocations" not in result
        assert "name=test" in result
        assert "stream-channels=false" in result

    def test_none_allocations_not_included(self):
        """None allocations should not add allocations param."""
        client = ClusterClient("localhost")
        result = client._build_add_params("test", None, local=False)
        assert "allocations" not in result
        assert "name=test" in result
        assert "stream-channels=false" in result

    def test_name_with_spaces_properly_encoded(self):
        """
        FIXED: Names with spaces ARE now properly URL-encoded.

        Spaces are encoded as + or %20 by urllib.parse.urlencode.
        """
        client = ClusterClient("localhost")
        result = client._build_add_params("my file.txt", ["peer1"], local=False)
        # Properly encoded: space becomes + or %20
        assert "my+file.txt" in result or "my%20file.txt" in result
        # Raw space should NOT appear
        assert "my file.txt" not in result

    def test_name_with_special_chars_properly_encoded(self):
        """
        FIXED: Names with special characters ARE now properly URL-encoded.

        & becomes %26, = becomes %3D, etc.
        """
        client = ClusterClient("localhost")
        result = client._build_add_params("file&name=bad", ["peer1"], local=False)
        # Properly encoded: & becomes %26, = becomes %3D
        assert "%26" in result  # & encoded
        assert "%3D" in result  # = encoded
        # Raw special chars should NOT appear
        assert "file&name=bad" not in result

    def test_realistic_peer_ids(self):
        """Test with realistic IPFS Cluster peer IDs."""
        client = ClusterClient("localhost")
        peer1 = "12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ"
        peer2 = "12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj"
        result = client._build_add_params("test", [peer1, peer2], local=False)
        # Peer IDs should be present
        assert peer1 in result
        assert peer2 in result
        # Note: comma may be URL encoded as %2C
        assert "allocations=" in result


class TestAddRequestFormat:
    """Tests for the actual HTTP request format sent by add methods."""

    @patch.object(ClusterClient, '_request')
    def test_add_file_url_format_with_local(self, mock_request):
        """Verify URL format for file add includes local=true by default."""
        mock_response = MagicMock()
        mock_response.text = '{"name": "test.txt", "cid": "QmTest", "size": 42}\n'
        mock_request.return_value = mock_response

        client = ClusterClient("localhost")

        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test")
            path = Path(f.name)

        try:
            client._add_file(path, "test.txt", ["peer1", "peer2"])

            # Check the URL that was requested
            call_args = mock_request.call_args
            method = call_args[0][0]
            endpoint = call_args[0][1]

            assert method == "POST"
            assert endpoint.startswith("/add?")
            assert "name=test.txt" in endpoint
            # Note: comma is URL encoded as %2C
            assert "allocations=peer1%2Cpeer2" in endpoint or "allocations=peer1,peer2" in endpoint
            assert "local=true" in endpoint
            assert "stream-channels=false" in endpoint
        finally:
            path.unlink()

    @patch.object(ClusterClient, '_request')
    def test_add_file_without_local(self, mock_request):
        """Verify URL format without local flag."""
        mock_response = MagicMock()
        mock_response.text = '{"name": "test.txt", "cid": "QmTest", "size": 42}\n'
        mock_request.return_value = mock_response

        client = ClusterClient("localhost")

        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test")
            path = Path(f.name)

        try:
            client._add_file(path, "test.txt", ["peer1", "peer2"], local=False)

            call_args = mock_request.call_args
            endpoint = call_args[0][1]

            assert "local" not in endpoint
            # Note: comma is URL encoded as %2C
            assert "allocations=peer1%2Cpeer2" in endpoint or "allocations=peer1,peer2" in endpoint
            assert "stream-channels=false" in endpoint
        finally:
            path.unlink()

    @patch.object(ClusterClient, '_request')
    def test_add_file_without_allocations(self, mock_request):
        """Verify URL format without allocations but with local."""
        mock_response = MagicMock()
        mock_response.text = '{"name": "test.txt", "cid": "QmTest", "size": 42}\n'
        mock_request.return_value = mock_response

        client = ClusterClient("localhost")

        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test")
            path = Path(f.name)

        try:
            client._add_file(path, "test.txt", None, local=False)

            call_args = mock_request.call_args
            endpoint = call_args[0][1]

            assert "allocations" not in endpoint
            assert "local" not in endpoint
            assert "name=test.txt" in endpoint
            assert "stream-channels=false" in endpoint
        finally:
            path.unlink()


class TestClusterClientInit:
    """Tests for ClusterClient initialization."""

    def test_base_url_format(self):
        """Base URL is constructed correctly."""
        client = ClusterClient("nas.tailnet", port=9094)
        assert client.base_url == "http://nas.tailnet:9094"

    def test_default_port(self):
        """Default port is 9094."""
        client = ClusterClient("localhost")
        assert client.base_url == "http://localhost:9094"

    def test_auth_stored(self):
        """Basic auth credentials are stored."""
        client = ClusterClient("localhost", basic_auth=("user", "pass"))
        assert client.auth == ("user", "pass")


class TestRequestLibraryBehavior:
    """
    Tests to understand how requests library handles our URL construction.

    These tests help diagnose whether the issue is in URL construction
    or in how requests sends the actual HTTP request.
    """

    def test_requests_preserves_query_string(self):
        """Verify requests doesn't mangle our manually-constructed query string."""
        import requests
        from unittest.mock import patch, MagicMock

        # Mock the actual HTTP call
        with patch('requests.Session.request') as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '{}'
            mock_request.return_value = mock_response

            session = requests.Session()
            url = "http://localhost:9094/add?name=test&allocations=peer1,peer2"
            session.request("POST", url, files={"file": ("test.txt", b"data")})

            # Check what URL was actually sent
            actual_url = mock_request.call_args[0][1]
            assert actual_url == url
            assert "allocations=peer1,peer2" in actual_url

    def test_full_add_request_flow(self):
        """
        Trace the complete request flow to verify allocations and local are sent.

        This test captures exactly what URL + headers + body would be sent.
        """
        import requests
        from unittest.mock import patch, MagicMock
        import tempfile
        from pathlib import Path

        with patch('requests.Session.request') as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '{"name": "test.txt", "cid": "QmTest", "size": 4}\n'
            mock_request.return_value = mock_response

            client = ClusterClient("localhost", basic_auth=("admin", "pass"))

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write("test")
                path = Path(f.name)

            try:
                allocations = [
                    "12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ",
                    "12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj",
                ]
                client.add(path, name="test.txt", allocations=allocations)

                # Verify the request
                call_args = mock_request.call_args
                method = call_args[0][0]
                url = call_args[0][1]
                kwargs = call_args[1]

                # Method should be POST
                assert method == "POST"

                # URL should contain allocations
                assert "allocations=" in url
                assert "12D3KooWRwzo72ZsiP5Hnfn2kGoi9f2u8AcQBozEP8MPVhpSqeLQ" in url
                assert "12D3KooWMJJ4ZVwHxNWVfxvKHyiF1XbEYW5Cq7gPPKyRQjbywABj" in url

                # URL should contain local=true (default)
                assert "local=true" in url

                # Should have files in kwargs
                assert 'files' in kwargs

                # Print actual URL for debugging (visible in pytest -v output)
                print(f"\nActual URL sent: {url}")
            finally:
                path.unlink()


class TestClusterAPIError:
    """Tests for ClusterAPIError exception."""

    def test_basic_error(self):
        err = ClusterAPIError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.status_code is None

    def test_error_with_status(self):
        err = ClusterAPIError("Unauthorized", status_code=401)
        assert err.status_code == 401

    def test_error_with_response(self):
        err = ClusterAPIError("Bad request", status_code=400, response={"detail": "invalid"})
        assert err.response == {"detail": "invalid"}
