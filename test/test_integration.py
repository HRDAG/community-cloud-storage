# Author: PB and Claude
# Date: 2026-01-30
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# test/test_integration.py

"""Integration tests requiring running IPFS Cluster."""

import pytest
import tempfile
import time
from pathlib import Path

from community_cloud_storage.config import load_config
from community_cloud_storage.operations import add, get, status


@pytest.mark.integration
def test_add_and_get_file():
    """End-to-end: add file, then retrieve it."""
    config = load_config()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test content for get operation")
        test_file = Path(f.name)

    try:
        result = add(test_file, profile="hrdag", config=config)
        cid = result.root_cid

        # Add may return incomplete if still pinning - wait for at least one peer to pin
        if not result.ok:
            print(f"Add incomplete: {result.error}")
            print(f"Waiting for content to be pinned on at least one node...")

            for attempt in range(10):
                time.sleep(1)
                pin_status = status(cid, config)
                if pin_status.pinned_count() > 0:
                    print(f"Content pinned on {pin_status.pinned_count()} node(s)")
                    break
            else:
                pytest.fail(f"Content never pinned after 10 seconds: {result.error}")

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "downloaded.txt"
            get(cid, dest, config)

            assert dest.exists(), "Downloaded file not found"
            assert dest.read_text() == "test content for get operation"
    finally:
        test_file.unlink()
