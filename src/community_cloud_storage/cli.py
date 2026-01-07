from io import TextIOWrapper
from pathlib import Path

import click

from community_cloud_storage import compose


@click.group()
def cli():
    pass


@cli.command()
@click.option("--cluster-peername", required=True)
@click.option(
    "--ts-authkey-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to file containing Tailscale auth key",
)
@click.option("--output", type=click.File("w"), default="-")
def create(output: TextIOWrapper, cluster_peername: str, ts_authkey_file: Path):
    """
    Create a new community-cloud-storage Docker Compose file.
    """
    ts_authkey = ts_authkey_file.read_text().strip()
    compose.create(output, cluster_peername=cluster_peername, ts_authkey=ts_authkey)


@cli.command()
@click.option("--cluster-peername", required=True)
@click.option("--input", type=click.File("r"), required=True)
@click.option("--output", type=click.File("w"), default="-")
@click.option("--bootstrap-host", required=True)
@click.option(
    "--ts-authkey-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to file containing Tailscale auth key",
)
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
def clone(
    cluster_peername: str,
    input: TextIOWrapper,
    output: TextIOWrapper,
    bootstrap_host: str,
    ts_authkey_file: Path,
    basic_auth: str,
    ipfs_peer_id: str,
    cluster_peer_id: str,
):
    """
    Use an existing compose file, and running containers, to generate a
    configuration for a new node in the cluster.
    """
    ts_authkey = ts_authkey_file.read_text().strip()
    compose.clone(
        input,
        output,
        cluster_peername=cluster_peername,
        bootstrap_host=bootstrap_host,
        ts_authkey=ts_authkey,
        basic_auth=basic_auth,
        ipfs_peer_id=ipfs_peer_id,
        cluster_peer_id=cluster_peer_id,
    )


@cli.command()
@click.option("--cluster-peername", required=True)
def reset_bootstrap_peers(cluster_peername: str) -> None:
    """
    Reset the bootstrap peers for a given node in the cluster. Useful on first
    setup of a node to ensure it isn't trying to talk to other peers.
    """
    compose.reset_bootstrap_peers(cluster_peername)


@cli.command()
@click.option("--cluster-peername", required=True)
@click.option("--bootstrap-host", required=True)
def set_bootstrap_peer(cluster_peername: str, bootstrap_host: str) -> None:
    """
    Add the bootstrap host as a peer to the IPFS container in the cluster node.
    This is useful when first setting up a new node in the cluster to ensure it
    can talk to the bootstrap node.
    """
    compose.set_bootstrap_peer(cluster_peername, bootstrap_host)


@cli.command()
@click.option("--cluster-peername", required=True)
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
@click.option("--cluster-peername", required=True)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials (default: ~/.ccs/config.yml)",
)
@click.argument("cid", required=True)
def status(cid: str, cluster_peername: str, basic_auth_file: Path) -> None:
    """
    Output the status of a CID in the cluster.
    """
    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)
    print(compose.status(cid, host=cluster_peername, basic_auth=basic_auth))


@cli.command()
@click.option("--cluster-peername", required=True)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials (default: ~/.ccs/config.yml)",
)
def ls(cluster_peername: str, basic_auth_file: Path) -> None:
    """
    List CIDs that are pinned in the cluster.
    """
    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)
    print(compose.ls(host=cluster_peername, basic_auth=basic_auth))


@cli.command()
@click.option("--cluster-peername", required=True)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials (default: ~/.ccs/config.yml)",
)
@click.argument("cid", required=True)
def rm(cid: str, cluster_peername: str, basic_auth_file: Path) -> None:
    """
    Remove a CID from the cluster.
    """
    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)
    print(compose.rm(cid, host=cluster_peername, basic_auth=basic_auth))


@cli.command()
@click.argument("cid", required=True)
@click.option("--cluster-peername", required=True)
@click.option("--output", type=click.Path(exists=False, path_type=Path), required=True)
def get(cid: str, cluster_peername: str, output: Path) -> None:
    """
    Get contents of a file and write to STDOUT or a file.
    """
    compose.get(cid, host=cluster_peername, output=output)
