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

You will want to install [Docker] on whatever machine you are planning to run your node on.

**Note:** As of v0.4.0, `community-cloud-storage` communicates directly with IPFS Cluster and IPFS via HTTP APIs. You do NOT need to install `ipfs` or `ipfs-cluster-ctl` on your workstation.

You will also need to install the `community-cloud-storage` utility which helps create the Docker compose file for the bootstrap node and then clone that for subsequent nodes in your network.

The preferred way to run `community-cloud-storage` is with the `uvx` utility from [uv]. uv makes it easy to run Python utilities without needing to download and install them, or even have Python available.

```
uvx community-cloud-storage
```

Alternatively, you can install community-cloud-storage using Python's package manager with:

```
pip install community-cloud-storage
```

The rest of the documentation uses examples with `uvx` but if you install with `pip` you should be able to remove that part of the command.

## Setup Bootstrap Node

*Note: if you are creating a community-cloud-storage node in an existing network jump down to the [Let Others Join](#let-others-join) section below.*

The first node in a *community-cloud-storage* network is known as the bootstrap node. It requires a bit more setup than subsequent nodes because the Tailscale mesh network needs to be created and configured, and a couple secret keys need to be defined. This bootstrap node will be used by subsequent nodes to find the rest of the network when they join.

### Tailscale

Your IPFS Cluster will run in a virtual private mesh network using Tailscale. Tailscale is a service for the open source Wireguard software. Creating a Tailscale account will give you access to the free tier which will be fine for your network. If you are interested in learning more about Tailscale they have a good series of instructional videos such as [Tailscale: Get Started in 10 minutes](https://www.youtube.com/watch?v=sPdvyR7bLqI).

After you create your account, you will need to ensure that the access rules allow the nodes in your cluster to talk to each other. Tailscale gives you a great deal of control over these rules but a useful place to start is to simply allow all the user and devices to see each other. To do this go to your Access Control tab in Tailscale admin and use the Visual Editor to ensure it has a rule that allows all users and devices in your tailnet to see each other. 

<img src="https://github.com/historypin/community-cloud-storage/raw/main/images/tailscale-01.png?raw=true">

These settings are just to get you started with your storage cluster. You can further refine them as needed as you develop your cluster and use Tailscale for other things.

<img src="https://github.com/historypin/community-cloud-storage/raw/main/images/tailscale-02.png?raw=true">

Be sure to also mention that any admins should get invited to the Tailscale so they can see it from their workstation.

### Add Machine to Tailnet

Before setting up CCS, ensure your machine is on the Tailscale network. Use the Tailscale client on the host machine (not in Docker) to join your tailnet. This gives the machine a hostname on the private network that other nodes can reach.

### Create Compose File

Create the compose file for your bootstrap node. The `--cluster-peername` should match your machine's hostname on the tailnet:

```
uvx community-cloud-storage create --cluster-peername bootstrap --output compose.yml
```

This should write a Docker Compose configuration to `compose.yaml`.

**DANGER: Be careful to not make this compose file public since it contains secret keys!**

### Start Bootstrap

You can now start up your bootstrap node with:

```bash
$ docker compose up -d
```

If you want to stop the service at any time you can execute this command, as long as you are in the `community-cloud-storage` directory:

```
$ docker compose stop
```

### Let Others Join

In order to let others join the network you will need to share a modified version of the compose file with them via a secure channel (e.g. WhatsApp or Signal). The new node's machine must already be on the tailnet.

```
uvx community-cloud-storage clone --input compose.yml --cluster-peername acme --bootstrap-host bootstrap --output acme-compose.yml
```

This will write out a `acme-compose.yml` file which you can share via a secure channel with someone running a machine at that organization.

You should be able to run this using `docker compose`, but for the original Shift-FFDW project we have been standardizing on partners using a [QNAP NAS](https://www.qnap.com/en-us/product/tbs-h574tx) which makes is easy to set up. You can use whatever device you want as long as you can run Docker on it and it has at least 4GB of memory (more couldn't hurt).

For people with a QNAP you can:

1. Ensure the QNAP is on the tailnet first (install Tailscale from Apps).
2. Install Container Station from Apps if it's not already available.
3. Open Container Station.
4. Click `Applications` option in the menu on the left.
5. Click the `Create` button.
6. In the Application Name box enter `community-cloud-storage`
7. Paste the contents of the supplied `compose.yml` file into the text box.
8. Click the `create` button.
9. Click the `Containers` option in the menu on the left.
10. Verify that you see two containers running (ipfs and ipfs-cluster).

## Working With Storage

*community-cloud-storage* is operated via the command line interface. As long as your workstation is on the tailnet, you can manage storage on any node in the cluster.

## Command Line

The community-cloud-storage utility offers functionality to add and remove content from storage via the IPFS Cluster HTTP API.

### Adding Content

Add a file:

```
uvx community-cloud-storage add --cluster-peername acme my-file.pdf
```

or a directory:

```
uvx community-cloud-storage add --cluster-peername acme my-directory/
```

### Checking Status

See what the status of a given CID is in the cluster:

```
uvx community-cloud-storage status --cluster-peername acme <cid>
```

### Get a CID

Fetch a CID and store as a local file:

```
uvx community-cloud-storage get --cluster-peername acme --output /path/to/file <cid>
```

### Removing Content

Remove a CID from the cluster:

```
uvx community-cloud-storage rm --cluster-peername acme <cid>
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
