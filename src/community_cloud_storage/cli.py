from io import TextIOWrapper
from pathlib import Path
import re
import sys

import click
import requests

from community_cloud_storage import compose
from community_cloud_storage.cluster_api import ClusterAPIError


def validate_peername(ctx, param, value):
    """Validate that cluster-peername looks like a valid hostname."""
    if value is None:
        return value
    if value.startswith("--"):
        raise click.BadParameter(
            f"'{value}' looks like a flag, not a hostname. "
            f"Did you forget to provide a value for --cluster-peername?"
        )
    # Basic hostname validation (alphanumeric, hyphens, dots)
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-\.]*$", value):
        raise click.BadParameter(
            f"'{value}' doesn't look like a valid hostname"
        )
    return value


def handle_api_error(func):
    """Decorator to catch API and connection errors."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClusterAPIError as e:
            click.echo(f"Error: Cluster API error: {e}", err=True)
            sys.exit(1)
        except requests.exceptions.ConnectionError as e:
            # Extract host from error message if possible
            msg = str(e)
            click.echo(f"Error: Could not connect to cluster", err=True)
            if "host=" in msg:
                import re
                match = re.search(r"host='([^']+)'", msg)
                if match:
                    click.echo(f"  Host: {match.group(1)}", err=True)
            click.echo("  Check --cluster-peername value (e.g., nas-ccs, meerkat-ccs)", err=True)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            click.echo(f"Error: Network error: {e}", err=True)
            sys.exit(1)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


@click.group()
def cli():
    pass


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option("--output", type=click.File("w"), default="-")
@click.option(
    "--node-role",
    type=click.Choice(["primary", "backup", "overflow"]),
    help="Node role for allocation (primary, backup, overflow)",
)
@click.option(
    "--node-org",
    help="Organization tag for allocation (e.g., hrdag, test-orgB)",
)
def create(output: TextIOWrapper, cluster_peername: str, node_role: str, node_org: str):
    """
    Create a new community-cloud-storage Docker Compose file.
    """
    compose.create(
        output,
        cluster_peername=cluster_peername,
        node_role=node_role,
        node_org=node_org,
    )


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option("--input", type=click.File("r"), required=True)
@click.option("--output", type=click.File("w"), default="-")
@click.option("--bootstrap-host", required=True)
@click.option(
    "--basic-auth",
    help="Basic auth credentials (user:password) for cluster API",
)
@click.option(
    "--ipfs-peer-id",
    help="IPFS peer ID of bootstrap node (skips network call if provided)",
)
@click.option(
    "--cluster-peer-id",
    help="Cluster peer ID of bootstrap node (skips network call if provided)",
)
@click.option(
    "--node-role",
    type=click.Choice(["primary", "backup", "overflow"]),
    help="Node role for allocation (primary, backup, overflow)",
)
@click.option(
    "--node-org",
    help="Organization tag for allocation (e.g., hrdag, test-orgB)",
)
def clone(
    cluster_peername: str,
    input: TextIOWrapper,
    output: TextIOWrapper,
    bootstrap_host: str,
    basic_auth: str,
    ipfs_peer_id: str,
    cluster_peer_id: str,
    node_role: str,
    node_org: str,
):
    """
    Use an existing compose file, and running containers, to generate a
    configuration for a new node in the cluster.
    """
    compose.clone(
        input,
        output,
        cluster_peername=cluster_peername,
        bootstrap_host=bootstrap_host,
        basic_auth=basic_auth,
        ipfs_peer_id=ipfs_peer_id,
        cluster_peer_id=cluster_peer_id,
        node_role=node_role,
        node_org=node_org,
    )


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
def reset_bootstrap_peers(cluster_peername: str) -> None:
    """
    Reset the bootstrap peers for a given node in the cluster. Useful on first
    setup of a node to ensure it isn't trying to talk to other peers.
    """
    compose.reset_bootstrap_peers(cluster_peername)


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option("--bootstrap-host", required=True)
def set_bootstrap_peer(cluster_peername: str, bootstrap_host: str) -> None:
    """
    Add the bootstrap host as a peer to the IPFS container in the cluster node.
    This is useful when first setting up a new node in the cluster to ensure it
    can talk to the bootstrap node.
    """
    compose.set_bootstrap_peer(cluster_peername, bootstrap_host)


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials (default: ~/.ccs/config.yml)",
)
@click.option(
    "--cid-manifest",
    type=click.Path(path_type=Path),
    help="Write CID manifest JSON to this file",
)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=True)
@handle_api_error
def add(cluster_peername: str, basic_auth_file: Path, cid_manifest: Path, path: Path) -> None:
    """
    Add a file or directory to the storage cluster using a peer hostname.
    """
    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)

    print(f"adding {path} to {cluster_peername}")
    result = compose.add(path, host=cluster_peername, basic_auth=basic_auth, cid_manifest=cid_manifest)

    if result.get("complete"):
        print(f"root CID: {result['root_cid']}")
        print(f"entries: {len(result['entries'])}")
        if cid_manifest:
            print(f"manifest written to: {cid_manifest}")
    else:
        print(f"add failed or incomplete: {result.get('error', 'unknown error')}")
        if result["entries"]:
            print(f"partial entries: {len(result['entries'])}")


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials (default: ~/.ccs/config.yml)",
)
@click.argument("cid", required=True)
@handle_api_error
def status(cid: str, cluster_peername: str, basic_auth_file: Path) -> None:
    """
    Output the status of a CID in the cluster.
    """
    import json

    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)
    result = compose.status(cid, host=cluster_peername, basic_auth=basic_auth)
    print(json.dumps(result, indent=2))


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials (default: ~/.ccs/config.yml)",
)
@handle_api_error
def ls(cluster_peername: str, basic_auth_file: Path) -> None:
    """
    List CIDs that are pinned in the cluster.
    """
    import json

    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)
    result = compose.ls(host=cluster_peername, basic_auth=basic_auth)
    print(json.dumps(result, indent=2))


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials (default: ~/.ccs/config.yml)",
)
@click.argument("cid", required=True)
@handle_api_error
def rm(cid: str, cluster_peername: str, basic_auth_file: Path) -> None:
    """
    Remove a CID from the cluster.
    """
    import json

    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)
    result = compose.rm(cid, host=cluster_peername, basic_auth=basic_auth)
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("cid", required=True)
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option("--output", type=click.Path(exists=False, path_type=Path), required=True)
@handle_api_error
def get(cid: str, cluster_peername: str, output: Path) -> None:
    """
    Get contents of a file and write to STDOUT or a file.
    """
    compose.get(cid, host=cluster_peername, output=output)
