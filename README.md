# community-cloud-storage

[![Test](https://github.com/historypin/community-cloud-storage/actions/workflows/test.yml/badge.svg)](https://github.com/historypin/community-cloud-storage/actions/workflows/test.yml)

*community-cloud-storage* gives communities actual data sovereignty. By keeping archival materials on a private, member-run mesh network rather than in corporate clouds, community-cloud-storage prevents AI companies, governments, or third parties from quietly scraping, indexing, or subpoenaing your files from a central host. Because data lives only on physical nodes inside a closed Tailscale/IPFS Cluster, it never leaks into the public IPFS network or any big-tech ecosystem, and is still accessible globally to trusted devices through the user interface.

*community-cloud-storage* is a command line utility that lets you create and manage a [Docker] based, trusted, decentralized storage system for community archives. All the heavy lifting is done by [IPFS Cluster] and [Tailscale] which provides a virtual private mesh network for the cluster participants that the rest of the world can't see. A small static web application is also included which makes it easy to see what files have been added to the cluster, and retrieve them.

This work is part of [Shift Collective]'s [Modeling Sustainable Futures: Exploring Decentralized Digital Storage for Community Based Archives] project, which was funded by the [Filecoin Foundation for the Decentralized Web]. For more details you can read reports linked from the project's homepage.

In a nutshell, the goal of *community-cloud-storage* is to provide an alternative to "big-tech" storage services, that is:

- *Decentralized* instead of *Centralized*: the software is open source and can
  be deployed on infrastructure that is operated by the members in their data centers,
  offices and homes. Members can join at any time to increase the capacity of the
  network, and can leave without disrupting the remaining members.
- *Trustful* instead of *Trustless*: members have shared values and goals in
  order to join the network. It is up to specific communities to decide what this means for them.
- *Mutable* instead of *Immutable*: data doesn't get replicated outside of the
  trusted network, and it's possible to remove data from the entire network at
  any time.
- *Private* instead of *Public*: many peer-to-peer and distributed web systems
  are built around the idea of data being globally available, and easy to
  replicate. Data in *community-cloud-storage* is not made available to the
  wider IPFS network. The use of Tailscale allows peers to communicate
  directly with each other using a virtual private mesh network, that only they
  can see.

*community-cloud-storage* is really just a Docker Compose configuration for reliably bringing up Docker services that allows a network of community-cloud-storage instances to talk to each other. The containers use host networking and assume machines are already on a private network (e.g., Tailscale/Headscale tailnet):

* *ipfs*: an IPFS daemon (kubo) for content storage
* *ipfs-cluster*: an IPFS Cluster daemon for replication and pinning coordination

Of course it's not all rainbows and unicorns, there are tradeoffs to this approach:

* The data in the storage cluster is only as stable as the people and organizations that are helping host it.
* Participants in the cluster can potentially access and delete data that does not belong to them.
* Unlike polished "big-tech" storage platforms (e.g. Google Drive, Box, etc) there are usability challenges to adding and removing content from the storage cluster.
* The IPFS and Tailscale software being used is open source, but the people maintaining it may change their minds, and focus on other things.
* Tailscale makes establishing a virtual private mesh network easy using the open source Wireguard software and some of their own open source code and infrastructure. However, Tailscale are a company and could decide to change how they do things at any time.
* Tailscale doesn't have access to any of the stored data, but they do know the network topology of the IPFS cluster, and could be issued a subpoena in some jurisdictions that forces them to share who is a member of the network. Read more about this [here](https://tailscale.com/blog/tailscale-privacy-anonymity).

In short, community-cloud-storage doesn't solve the Governance Problem. You have to decide who is in your trusted network, and everyone in your network needs to decide what your values are, and specifically what norms are around deleting content, and growing the network.

Thanks to TRANSFERArchive's [DATA.TRUST] project for the example of using IPFS Cluster with Tailscale to help ensure data privacy, and reliable cluster connectivity. We had hoped to use DATA.TRUST directly, however our projects were on slightly different timelines, and community-cloud-storage had no requirements that needed to be satisfied by Filecoin. Also, thank you to the Flickr Foundation's [Data Lifeboat] project for their example of using static site archives in preservation work, which led to Historypin's [pincushion] application for exporting content for import into IPFS Cluster.

## Install

### For Operators (Daily Use)

Install the `ccs` command-line tool to add, list, and retrieve files from an existing cluster.

The preferred way to run `community-cloud-storage` is with the `uvx` utility from [uv]:

```
uvx community-cloud-storage
```

Alternatively, install with pip:

```
pip install community-cloud-storage
```

You'll also need:
1. Access to the Tailscale network (tailnet) where the cluster runs
2. A config file at `~/.ccs/config.yml` with cluster credentials

### For Administrators (Deployment)

Node deployment is managed by Ansible. See:
- `docs/architecture-plan.md` — Overall architecture and implementation phases
- `hrdag-ansible/docs/ccs-role-requirements.md` — Ansible role requirements

The `ccs create` and `ccs clone` commands still exist but are deprecated. Use Ansible for all node deployments.

## Tailscale Setup

Your IPFS Cluster runs in a virtual private mesh network using Tailscale. Tailscale is a service built on open source Wireguard. The free tier is sufficient for most clusters.

**Setup steps:**

1. Create a Tailscale account at [tailscale.com](https://tailscale.com/)
2. Configure access rules to allow cluster nodes to communicate (Access Control → Visual Editor → allow all users/devices)
3. Install Tailscale on each machine that will run a CCS node
4. Install Tailscale on admin workstations that need CLI access

For detailed Tailscale setup, see their [getting started guide](https://www.youtube.com/watch?v=sPdvyR7bLqI).

<img src="https://github.com/historypin/community-cloud-storage/raw/main/images/tailscale-01.png?raw=true">

<img src="https://github.com/historypin/community-cloud-storage/raw/main/images/tailscale-02.png?raw=true">

## Working With Storage

Once your workstation is on the tailnet and you have `~/.ccs/config.yml` configured, you can manage storage on any node in the cluster.

### Configuration

Create `~/.ccs/config.yml`:

```yaml
cluster:
  basic_auth_user: admin
  basic_auth_password: <your-password>
```

### Adding Content

Add a file:

```bash
ccs add --cluster-peername nas --basic-auth-file ~/.ccs/config.yml my-file.pdf
```

Or a directory:

```bash
ccs add --cluster-peername nas --basic-auth-file ~/.ccs/config.yml my-directory/
```

### Listing Pins

List all CIDs pinned in the cluster:

```bash
ccs ls --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
```

### Checking Status

See replication status of a specific CID:

```bash
ccs status <CID> --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
```

### Retrieving Content

Fetch a CID and save to a local file:

```bash
ccs get <CID> --cluster-peername nas --output /path/to/file
```

Note: `get` uses the IPFS gateway (port 8080) and does not require authentication.

### Removing Content

Remove a CID from the cluster:

```bash
ccs rm <CID> --cluster-peername nas --basic-auth-file ~/.ccs/config.yml
```

[uv]: https://docs.astral.sh/uv/getting-started/installation/
[Docker]: https://www.docker.com/get-started/
[Tailscale]: https://tailscale.com/
[IPFS Cluster]: https://ipfscluster.io/
[Git]: https://git-scm.com/
[Filecoin Foundation for the Decentralized Web]: https://ffdweb.org/
[Modeling Sustainable Futures: Exploring Decentralized Digital Storage for Community Based Archives]: https://www.shiftcollective.us/ffdw
[Shift Collective]: https://www.shiftcollective.us/
[community-cloud-storage-ui]: https://github.com/historypin/community-cloud-storage-ui
[Data Lifeboat]: https://datalifeboat.flickr.org/
[DATA.TRUST]: https://github.com/TRANSFERArchive/DATA.TRUST
[pincushion]: https://github.com/historypin/pincushion
