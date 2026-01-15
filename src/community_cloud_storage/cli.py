# Author: PB and Claude
# Date: 2026-01-14
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/community_cloud_storage/cli.py

"""
CCS Command Line Interface

Thin wrapper around the operations module.
"""

from io import TextIOWrapper
from pathlib import Path
import re
import sys

import click
import requests

from community_cloud_storage import compose
from community_cloud_storage.cluster_api import ClusterAPIError
from community_cloud_storage import config as config_module
from community_cloud_storage import operations
from community_cloud_storage.operations import CCSError


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
        except CCSError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
        except requests.exceptions.ConnectionError as e:
            msg = str(e)
            click.echo(f"Error: Could not connect to cluster", err=True)
            if "host=" in msg:
                match = re.search(r"host='([^']+)'", msg)
                if match:
                    click.echo(f"  Host: {match.group(1)}", err=True)
            click.echo("  Check --cluster-peername value or config", err=True)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            click.echo(f"Error: Network error: {e}", err=True)
            sys.exit(1)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


@click.group()
def cli():
    """Community Cloud Storage CLI."""
    pass


# =============================================================================
# New library-first commands
# =============================================================================

@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--profile",
    required=True,
    help="Organization profile (e.g., hrdag). Determines primary node for allocation.",
)
@click.option(
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file path (default: ~/.ccs/config.yml)",
)
@click.option(
    "--host",
    callback=validate_peername,
    help="Override cluster host to talk to (default: from config)",
)
@click.option(
    "--output-json",
    type=click.Path(path_type=Path),
    help="Write full result as JSON to this file",
)
@handle_api_error
def add(path: Path, profile: str, config_file: Path, host: str, output_json: Path) -> None:
    """
    Add a file or directory to the cluster.

    Uses --profile to determine allocation: content is pinned to the profile's
    primary node, the backup node, and one additional replica chosen by the
    cluster allocator.

    Examples:

        ccs add /path/to/file --profile hrdag

        ccs add /path/to/directory --profile hrdag --output-json manifest.json
    """
    config = config_module.load_config(config_file)
    result = operations.add(path, profile=profile, config=config, host=host)

    if result.complete:
        click.echo(f"added {path} with profile {profile}")
        click.echo(f"root CID: {result.root_cid}")
        click.echo(f"entries: {len(result.entries)}")
        click.echo(f"allocations: {', '.join(result.allocations[:2])}...")  # Show first 2
    else:
        click.echo(f"add failed: {result.error}", err=True)
        sys.exit(1)

    if output_json:
        with open(output_json, "w") as f:
            f.write(result.to_json())
        click.echo(f"manifest written to: {output_json}")


@cli.command()
@click.argument("cid", required=True)
@click.option(
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file path (default: ~/.ccs/config.yml)",
)
@click.option(
    "--host",
    callback=validate_peername,
    help="Override cluster host to talk to (default: from config)",
)
@handle_api_error
def status(cid: str, config_file: Path, host: str) -> None:
    """
    Get status of a CID in the cluster.
    """
    config = config_module.load_config(config_file)
    result = operations.status(cid, config=config, host=host)
    click.echo(result.to_json())


@cli.command()
@click.option(
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file path (default: ~/.ccs/config.yml)",
)
@click.option(
    "--host",
    callback=validate_peername,
    help="Override cluster host to talk to (default: from config)",
)
@handle_api_error
def peers(config_file: Path, host: str) -> None:
    """
    List all peers in the cluster.
    """
    import json

    config = config_module.load_config(config_file)
    result = operations.peers(config=config, host=host)
    output = [p.to_dict() for p in result]
    click.echo(json.dumps(output, indent=2))


@cli.command()
@click.option(
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file path (default: ~/.ccs/config.yml)",
)
@click.option(
    "--host",
    callback=validate_peername,
    help="Override cluster host to talk to (default: from config)",
)
@handle_api_error
def ls(config_file: Path, host: str) -> None:
    """
    List all pinned CIDs in the cluster.
    """
    import json

    config = config_module.load_config(config_file)
    result = operations.ls(config=config, host=host)
    output = [p.to_dict() for p in result]
    click.echo(json.dumps(output, indent=2))


@cli.command()
@click.option(
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file path (default: ~/.ccs/config.yml)",
)
@click.option(
    "--validate-only",
    is_flag=True,
    help="Only validate config, don't display it",
)
@click.option(
    "--output-json",
    type=click.Path(path_type=Path),
    help="Write config as JSON to this file",
)
def config(config_file: Path, validate_only: bool, output_json: Path) -> None:
    """
    Display and validate CCS configuration.

    Shows current config settings and checks for errors/warnings.

    Examples:

        ccs config                    # Display config with validation

        ccs config --validate-only    # Just check for errors

        ccs config --output-json config.json   # Export as JSON
    """
    import json

    config_path = config_file or config_module.DEFAULT_CONFIG_PATH

    try:
        cfg = config_module.load_config(config_file)
    except FileNotFoundError:
        click.echo(f"Error: Config file not found: {config_path}", err=True)
        click.echo(f"Create config at {config_path} or use --config-file", err=True)
        sys.exit(1)

    errors, warnings = cfg.validate()

    if validate_only:
        # Just show validation results
        if errors:
            click.echo("Errors:", err=True)
            for e in errors:
                click.echo(f"  ✗ {e}", err=True)
        if warnings:
            click.echo("Warnings:")
            for w in warnings:
                click.echo(f"  ⚠ {w}")
        if not errors and not warnings:
            click.echo("✓ Config is valid")
        sys.exit(1 if errors else 0)

    # Display config
    click.echo(f"Config file: {config_path}")
    click.echo()

    click.echo("Settings:")
    click.echo(f"  default_node: {cfg.default_node or '(not set)'}")
    click.echo(f"  backup_node: {cfg.backup_node or '(not set)'}")
    click.echo(f"  auth: {'configured' if cfg.auth else '(not set)'}")
    click.echo()

    if cfg.profiles:
        click.echo("Profiles:")
        for name, profile in cfg.profiles.items():
            click.echo(f"  {name}: primary={profile.primary}")
        click.echo()

    if cfg.nodes:
        click.echo("Nodes:")
        for name, node in cfg.nodes.items():
            peer_id = node.peer_id[:16] + "..." if node.peer_id else "(no peer_id)"
            click.echo(f"  {name}: host={node.host}, peer_id={peer_id}")
        click.echo()

    # Validation results
    if errors:
        click.echo("Errors:", err=True)
        for e in errors:
            click.echo(f"  ✗ {e}", err=True)
    if warnings:
        click.echo("Warnings:")
        for w in warnings:
            click.echo(f"  ⚠ {w}")
    if not errors and not warnings:
        click.echo("✓ Config is valid")

    # Write JSON if requested
    if output_json:
        # Don't include secrets in JSON output
        output_data = {
            "config_path": str(config_path),
            "default_node": cfg.default_node,
            "backup_node": cfg.backup_node,
            "has_auth": cfg.auth is not None,
            "profiles": {name: p.to_dict() for name, p in cfg.profiles.items()},
            "nodes": {name: {"host": n.host, "has_peer_id": n.peer_id is not None}
                      for name, n in cfg.nodes.items()},
            "errors": errors,
            "warnings": warnings,
            "valid": len(errors) == 0,
        }
        with open(output_json, "w") as f:
            json.dump(output_data, f, indent=2)
        click.echo(f"Config written to: {output_json}")

    sys.exit(1 if errors else 0)


# =============================================================================
# Legacy commands (for backward compatibility)
# =============================================================================

@cli.command("add-legacy")
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
def add_legacy(cluster_peername: str, basic_auth_file: Path, cid_manifest: Path, path: Path) -> None:
    """
    [Legacy] Add a file or directory without profile-based allocation.

    Use 'ccs add --profile <name>' instead for proper allocation.
    """
    config = compose.load_config(basic_auth_file)
    basic_auth = compose.get_basic_auth_string(config)

    click.echo(f"adding {path} to {cluster_peername}")
    result = compose.add(path, host=cluster_peername, basic_auth=basic_auth, cid_manifest=cid_manifest)

    if result.get("complete"):
        click.echo(f"root CID: {result['root_cid']}")
        click.echo(f"entries: {len(result['entries'])}")
        if cid_manifest:
            click.echo(f"manifest written to: {cid_manifest}")
    else:
        click.echo(f"add failed or incomplete: {result.get('error', 'unknown error')}")
        if result["entries"]:
            click.echo(f"partial entries: {len(result['entries'])}")


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option(
    "--basic-auth-file",
    type=click.Path(exists=True, path_type=Path),
    help="Config file with basic auth credentials",
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
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.argument("cid", required=True)
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option("--output", type=click.Path(exists=False, path_type=Path), required=True)
@handle_api_error
def get(cid: str, cluster_peername: str, output: Path) -> None:
    """
    Get contents of a file and write to a file.
    """
    compose.get(cid, host=cluster_peername, output=output)


# =============================================================================
# Compose management commands (deprecated - use ansible)
# =============================================================================

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
    [Deprecated] Create a new Docker Compose file. Use ansible instead.
    """
    click.echo("Warning: 'ccs create' is deprecated. Use ansible for deployment.", err=True)
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
@click.option("--basic-auth", help="Basic auth credentials (user:password)")
@click.option("--ipfs-peer-id", help="IPFS peer ID of bootstrap node")
@click.option("--cluster-peer-id", help="Cluster peer ID of bootstrap node")
@click.option("--node-role", type=click.Choice(["primary", "backup", "overflow"]))
@click.option("--node-org", help="Organization tag")
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
    [Deprecated] Clone a compose file from existing node. Use ansible instead.
    """
    click.echo("Warning: 'ccs clone' is deprecated. Use ansible for deployment.", err=True)
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
    [Deprecated] Reset bootstrap peers. Use ansible instead.
    """
    click.echo("Warning: 'ccs reset-bootstrap-peers' is deprecated.", err=True)
    compose.reset_bootstrap_peers(cluster_peername)


@cli.command()
@click.option("--cluster-peername", required=True, callback=validate_peername)
@click.option("--bootstrap-host", required=True)
def set_bootstrap_peer(cluster_peername: str, bootstrap_host: str) -> None:
    """
    [Deprecated] Set bootstrap peer. Use ansible instead.
    """
    click.echo("Warning: 'ccs set-bootstrap-peer' is deprecated.", err=True)
    compose.set_bootstrap_peer(cluster_peername, bootstrap_host)
