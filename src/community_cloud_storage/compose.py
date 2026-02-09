import json
import os
import shlex
import socket
import subprocess
from datetime import datetime, timezone
from io import TextIOWrapper
from pathlib import Path

import yaml

from community_cloud_storage import config as config_module


DEFAULT_CONFIG_PATH = config_module.DEFAULT_CONFIG


def load_config(config_path: Path = None) -> dict:
    """
    Load cluster config from toml files.
    Default: /etc/tfc/common.toml + /etc/tfc/ccs.toml

    Returns dict with basic_auth_user, basic_auth_password, etc.
    This is a backward-compatible wrapper around config_module.load_config().

    For new code, use config_module.load_config() directly to get a CCSConfig object.
    """
    ccs_config = config_module.load_config(config_path=config_path)

    # Flatten for backward compatibility
    result = {}
    if ccs_config.auth:
        result["basic_auth_user"] = ccs_config.auth.user
        result["basic_auth_password"] = ccs_config.auth.password
    if ccs_config.default_node:
        result["default_node"] = ccs_config.default_node

    # Also include new fields for code that wants them
    result["_ccs_config"] = ccs_config

    return result


def get_basic_auth_string(config: dict) -> str:
    """Build basic auth string from config dict."""
    # Check for new-style config object first
    if "_ccs_config" in config:
        return config["_ccs_config"].get_basic_auth_string()

    # Fall back to old-style dict
    user = config.get("basic_auth_user")
    password = config.get("basic_auth_password")
    if user and password:
        return f"{user}:{password}"
    return None


def _get_env_value(env_list: list, prefix: str) -> str:
    """Extract value from environment list by prefix."""
    for item in env_list:
        if item.startswith(prefix):
            return item
    raise ValueError(f"No environment variable starting with {prefix}")


def create(
    output: TextIOWrapper,
    cluster_peername: str,
    cluster_secret: str = None,  # these will be generated if not passed in
    ipfs_swarm_key: str = None,  # but are useful to define when testing
    node_role: str = None,  # e.g., "primary", "backup", "overflow"
    node_org: str = None,  # e.g., "hrdag", "test-orgB"
) -> None:
    """
    Create a new compose.yml for a new cluster. This node will act as a
    bootstrap node for subsequent nodes in the cluster.
    """

    # generate secret keys if needed
    ipfs_swarm_key = ipfs_swarm_key or os.urandom(32).hex()
    cluster_secret = cluster_secret or os.urandom(32).hex()

    output.write(
        compose_text(
            cluster_peername=cluster_peername,
            ipfs_swarm_key=ipfs_swarm_key,
            cluster_secret=cluster_secret,
            node_role=node_role,
            node_org=node_org,
        )
    )


def clone(
    input: TextIOWrapper,
    output: TextIOWrapper,
    cluster_peername: str,
    bootstrap_host: str,
    basic_auth: str = None,
    ipfs_peer_id: str = None,
    cluster_peer_id: str = None,
    node_role: str = None,
    node_org: str = None,
) -> None:
    """
    Clone a new node based on the compose file of a bootstrap node.

    We need to be given:
    - an existing compose.yml file as input
    - an output handle to write the new compose text
    - a new cluster peer name for the clone
    - optional basic auth credentials for cluster API
    - optional ipfs_peer_id (skips network call if provided)
    - optional cluster_peer_id (skips network call if provided)
    - optional node_role for allocation tags (e.g., "primary", "backup")
    - optional node_org for allocation tags (e.g., "hrdag", "test-orgB")

    We read these values from the existing compose.yaml file since they are
    carried through unchanged:
    - IPFS_SWARM_KEY
    - CLUSTER_SECRET

    And we generate these new environment variables by talking to the running
    bootstrap host to get its IP and the IPFS IDs:
    - IPFS_BOOTSTRAP
    - IPFS_CLUSTER_BOOTSTRAP
    """

    # load the existing compose doc
    bootstrap_doc = yaml.load(input, Loader=yaml.Loader)

    # get IP of bootstrap host
    bootstrap_ip = socket.gethostbyname(bootstrap_host)

    # get IPFS peer ID - use provided value or query the node via HTTP API
    if ipfs_peer_id:
        ipfs_id = ipfs_peer_id
    else:
        ipfs_client = _get_ipfs_client(bootstrap_host)
        ipfs_info = ipfs_client.id()
        ipfs_id = ipfs_info["ID"]

    # get cluster peer ID - use provided value or query the node via HTTP API
    if cluster_peer_id:
        ipfs_cluster_id = cluster_peer_id
    else:
        cluster_client = _get_cluster_client(bootstrap_host, basic_auth)
        cluster_info = cluster_client.id()
        ipfs_cluster_id = cluster_info["id"]

    # construct multiaddr for bootstrapping ipfs and ipfs cluster
    ipfs_cluster_bootstrap = f"/ip4/{bootstrap_ip}/tcp/9096/ipfs/{ipfs_cluster_id}"
    ipfs_bootstrap = f"/ip4/{bootstrap_ip}/tcp/4001/ipfs/{ipfs_id}"

    # write out the compose text for the clone!
    output.write(
        compose_text(
            cluster_peername=cluster_peername,
            ipfs_swarm_key=_get_env_value(
                bootstrap_doc["services"]["ipfs"]["environment"], "IPFS_SWARM_KEY="
            ),
            cluster_secret=bootstrap_doc["services"]["ipfs-cluster"]["environment"][
                "CLUSTER_SECRET"
            ],
            ipfs_bootstrap=ipfs_bootstrap,
            ipfs_cluster_bootstrap=ipfs_cluster_bootstrap,
            node_role=node_role,
            node_org=node_org,
        )
    )


def reset_bootstrap_peers(host: str) -> None:
    """
    When IPFS nodes start up they should have bootstrap peers removed.
    """
    run(f"ipfs --api /dns/{host}/tcp/5001 bootstrap rm all")


def set_bootstrap_peer(cluster_peername: str, bootstrap_host: str) -> None:
    """
    When IPFS nodes start up they may need to be given the bootstrap node explicitly.
    """

    # ensure we have a blank slate
    reset_bootstrap_peers(cluster_peername)

    # determine the IP of the bootstrap node
    tailscale_ip = socket.gethostbyname(bootstrap_host)

    # tell the cluster node to use bootstrap IP for bootstrapping
    run(
        f"""ipfs --api /dns/{cluster_peername}/tcp/5001 config --json Addresses.Swarm ["/ip4/0.0.0.0/tcp/4001","/ip6/::/tcp/4001"]"""
    )
    run(
        f"""ipfs --api /dns/{cluster_peername}/tcp/5001 config --json Addresses.Announce ["/ip4/{tailscale_ip}/tcp/4001"]"""
    )

    # create multiaddr format for bootstrap node
    ipfs_id = run(f"ipfs --api /dns/{bootstrap_host}/tcp/5001 id -f <id>")
    ipfs_bootstrap_multi = f"/ip4/{tailscale_ip}/tcp/4001/ipfs/{ipfs_id}"

    # add the bootstrap node
    run(
        f"ipfs --api /dns/{cluster_peername}/tcp/5001 bootstrap add {ipfs_bootstrap_multi}"
    )


def compose_text(
    cluster_peername,
    ipfs_swarm_key,
    cluster_secret,
    ipfs_bootstrap=None,
    ipfs_cluster_bootstrap=None,
    node_role=None,
    node_org=None,
):
    # read in the compose template
    template_path = Path(__file__).parent / "compose.yml"
    doc = yaml.load(template_path.open("r"), Loader=yaml.Loader)

    doc["services"]["ipfs-cluster"]["environment"]["CLUSTER_PEERNAME"] = (
        cluster_peername
    )
    doc["services"]["ipfs-cluster"]["environment"]["CLUSTER_SECRET"] = cluster_secret

    # The IPFS Swarm Key is a bit difficult because it needs to be packaged as a multiline string for the
    # environment, simulating a file on disk.
    if "IPFS_SWARM_KEY=" not in ipfs_swarm_key:
        ipfs_swarm_key = (
            f"IPFS_SWARM_KEY=/key/swarm/psk/1.0.0/\n/base16/\n{ipfs_swarm_key}"
        )
    doc["services"]["ipfs"]["environment"] = [ipfs_swarm_key]

    # if we've been given the ipfs bootstrap info add that to the ipfs environment
    if ipfs_bootstrap:
        env_list = doc["services"]["ipfs"]["environment"]
        env_str = f"IPFS_BOOTSTRAP={ipfs_bootstrap}"
        if env_str not in env_list:
            # not sure why but the qnap yaml parser doesn't like it if this
            # environment variable shows up after the multiline IPFS_SWARM_KEY
            env_list.insert(0, env_str)

    # similarly if we've been given the ipfs cluster bootstrap info, we can add
    # that to the ipfs cluster environment
    if ipfs_cluster_bootstrap:
        doc["services"]["ipfs-cluster"]["environment"]["CLUSTER_PEERADDRESSES"] = (
            ipfs_cluster_bootstrap
        )

    # add node tags for allocation (role and org)
    if node_role or node_org:
        tags = {}
        if node_role:
            tags["role"] = node_role
        if node_org:
            tags["org"] = node_org
        # IPFS Cluster expects tags as JSON string in this env var
        import json
        doc["services"]["ipfs-cluster"]["environment"]["CLUSTER_INFORMER_TAGS_TAGS"] = (
            json.dumps(tags)
        )

    # return the serialized yaml
    return yaml.dump(doc)


def _get_cluster_client(host: str, basic_auth: str = None):
    """Create a ClusterClient instance."""
    from community_cloud_storage.cluster_api import ClusterClient

    auth_tuple = None
    if basic_auth and ":" in basic_auth:
        user, password = basic_auth.split(":", 1)
        auth_tuple = (user, password)

    return ClusterClient(host=host, port=9094, basic_auth=auth_tuple)


def _get_ipfs_client(host: str):
    """Create an IPFSClient instance."""
    from community_cloud_storage.cluster_api import IPFSClient

    return IPFSClient(host=host, port=5001)


def add(path: Path, host: str, basic_auth: str = None, cid_manifest: Path = None) -> dict:
    """
    Add a given file or directory to the cluster via HTTP API.

    Returns dict with:
    - root_cid: CID of the top-level item
    - root_path: original path name
    - added_at: ISO timestamp
    - cluster_peername: host used
    - entries: list of {path, cid} dicts
    - complete: bool indicating if add fully succeeded
    """
    from community_cloud_storage.cluster_api import create_manifest

    client = _get_cluster_client(host, basic_auth)

    try:
        entries = client.add(path, recursive=True)
        result = create_manifest(
            path=path,
            cluster_peername=host,
            entries=entries,
            complete=True,
        )
    except Exception as e:
        # Partial failure - return what we have
        result = create_manifest(
            path=path,
            cluster_peername=host,
            entries=[],
            complete=False,
            error=str(e),
        )

    # Write manifest if requested
    if cid_manifest:
        with open(cid_manifest, "w") as f:
            json.dump(result, f, indent=2)

    return result


def status(cid: str, host: str, basic_auth: str = None) -> dict:
    """
    Get status of a CID in the cluster via HTTP API.

    Returns dict with pin status.
    """
    client = _get_cluster_client(host, basic_auth)
    return client.pin_status(cid)


def ls(host: str, basic_auth: str = None) -> list:
    """
    List CIDs that are pinned in the cluster via HTTP API.

    Returns list of pin status objects.
    """
    client = _get_cluster_client(host, basic_auth)
    return client.pins()


def rm(cid: str, host: str, basic_auth: str = None) -> dict:
    """
    Remove a CID from the cluster via HTTP API.

    Returns removed pin info.
    """
    client = _get_cluster_client(host, basic_auth)
    return client.unpin(cid)


def get(cid: str, host: str, output: Path) -> None:
    """
    Get a CID from IPFS gateway and write to output path.
    """
    import requests
    url = f"http://{host}:8080/ipfs/{cid}"
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(output, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def run(cmd, parse_json=False) -> str:
    """
    Run a system command and return the output, optionally parsing JSON output.
    """
    try:
        out = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf8").strip() if e.stderr else ""
        raise RuntimeError(f"Command failed: {cmd}\n{stderr}") from e

    if parse_json:
        return json.loads(out.stdout.decode("utf8"))
    else:
        return out.stdout.decode("utf8").strip()
