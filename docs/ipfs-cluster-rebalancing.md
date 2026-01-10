# IPFS Cluster allocation control: explicit pinning meets automatic failover

**Bottom line: Explicit allocations and automatic rebalancing are NOT mutually exclusive, but their interaction is nuanced.** With `disable_repinning: false` and properly configured replication factors, IPFS Cluster will re-allocate pins when explicit peers fail—but only when the replica count drops below `replication_factor_min`. By default (since v0.14), automatic repinning is disabled, meaning the cluster stubbornly waits for specified peers indefinitely.

Your "primary + backup + dynamic" model is achievable using a combination of **tag-based allocation**, **explicit allocations per-pin**, and **replication factor ranges**—though there's no single native configuration for this pattern. The balanced allocator with `allocate_by: ["tag:tier", "freespace"]` gets closest to your goal.

---

## 1. Explicit allocations: best-effort priority, not guarantees

When you pin with explicit allocations via `POST /pins/{cid}?allocations=peer1,peer2,peer3`, those peers receive **priority** but are treated as best-effort:

**At pin time:** If any specified peers are unavailable, IPFS Cluster silently allocates from remaining cluster peers instead. The pin succeeds without error—priority allocations are "best effort. If any priority peers are unavailable then Pin will simply allocate from the rest of the cluster."

**When a peer goes offline permanently:** The behavior depends critically on `disable_repinning`:

| Setting | Behavior when allocated peer dies |
|---------|-----------------------------------|
| `disable_repinning: true` (default since v0.14) | Cluster stubbornly waits indefinitely; pin status shows error; requires manual `ipfs-cluster-ctl recover` |
| `disable_repinning: false` | Re-allocation triggers **only** when replica count falls below `replication_factor_min` |

**Key gotcha:** Even with repinning enabled, if you have 3 allocations (min=2, max=3) and one peer dies, **no automatic action occurs** because 2 replicas still satisfy the minimum. Only crossing below the min threshold triggers failover.

**Sources:**
- https://ipfscluster.io/documentation/guides/pinning/
- https://pkg.go.dev/github.com/ipfs-cluster/ipfs-cluster
- https://github.com/ipfs-cluster/ipfs-cluster/issues/369

---

## 2. Replication factors complement explicit allocations

Replication factors and explicit allocations work together rather than conflicting:

| Scenario | Resulting behavior |
|----------|-------------------|
| Explicit allocations < `replication_factor_min` | Additional peers selected from cluster to meet minimum |
| Explicit allocations > `replication_factor_max` | Only `replication_factor_max` peers selected from explicit list |
| Explicit allocations between min and max | Explicit allocations used as-is with priority |

**Failover triggering:** If you specify 3 allocations with min=2 and max=3, and one peer permanently fails:
- Remaining count = 2 (still ≥ min) → **No automatic re-allocation**
- Two peers fail, count = 1 (below min) → **Re-allocation triggered** (if repinning enabled)

**Important nuance:** Once allocations are set, "Cluster does not automatically change them (i.e. to increase them)." A new pin operation for the same CID will try to reach `replication_factor_max` while respecting existing allocations—but this requires an explicit re-pin action.

**Recommended configuration for your 10-12 node cluster:**
```json
{
  "cluster": {
    "replication_factor_min": 2,
    "replication_factor_max": 4,
    "disable_repinning": false
  }
}
```
The **leeway between min and max** (2-4 rather than 3-3) prevents excessive churn from brief outages while ensuring failover when truly needed.

**Sources:**
- https://ipfscluster.io/documentation/guides/pinning/
- https://github.com/ipfs-cluster/ipfs-cluster/issues/277

---

## 3. Allocator configuration: tags are your primary lever

IPFS Cluster's **balanced allocator** (the only actively maintained option) can be configured to prefer certain nodes through tag-based grouping and metric ordering.

**Available metrics for `allocate_by`:**
- `freespace` — Available storage in IPFS repo
- `tag:<name>` — User-defined tags (e.g., `tag:tier`, `tag:region`)
- `pinqueue` — Current pinning queue length
- `numpin` — Total pin count

**Configuration for node preference:**
```json
{
  "allocator": {
    "balanced": {
      "allocate_by": ["tag:tier", "tag:region", "freespace"]
    }
  },
  "informer": {
    "tags": {
      "tags": {
        "tier": "primary",
        "region": "us-east"
      }
    }
  }
}
```

**No native "always include peer X" setting exists.** However, four workarounds achieve similar results:

1. **Per-pin allocations:** Always include your preferred peer in `--allocations` flag
2. **Tag-based priority:** Give preferred peers unique tag values and prioritize that tag in `allocate_by`
3. **Trusted peers mode:** Set `pin_only_on_trusted_peers: true` to limit pins to trusted peers only
4. **StorageMax exclusion:** Set `StorageMax=0` on peers you want excluded (stops metric broadcasting)

**The `--local` flag** when adding content always includes the local peer in allocations regardless of free space—useful for ensuring the originating node keeps a copy.

**Sources:**
- https://ipfscluster.io/documentation/reference/configuration/
- https://pkg.go.dev/github.com/ipfs/ipfs-cluster/allocator/balanced

---

## 4. Pin types have no impact on rebalancing

IPFS Cluster supports two pin modes:

| Mode | Behavior |
|------|----------|
| **Recursive** (default) | Pins the CID and all linked children (full DAG) |
| **Direct** | Pins only the specific block |

**Pin type determines what content is stored, not where or how replication works.** Rebalancing behavior is controlled entirely by replication factors and the `disable_repinning` setting—pin type has no effect on allocation decisions.

IPFS Cluster also defines internal types for sharded content (`MetaType`, `ClusterDAGType`, `ShardType`), but these are implementation details for handling large files split across multiple peers.

**Sources:**
- https://docs.ipfs.tech/how-to/pin-files/
- https://github.com/ipfs-cluster/ipfs-cluster/blob/master/api/types.go

---

## 5. CRDT handles partitions gracefully, syncs missed allocations

In CRDT consensus mode (recommended for 10+ node clusters), explicit allocations behave predictably during network events:

**During network partitions:**
- Each partition continues operating independently—any peer can accept pin requests
- Explicit allocations are recorded in each partition's local Merkle-DAG
- Pinsets can diverge temporarily (this is by design)

**When a node reconnects:**
- **Yes, it syncs pins it was explicitly allocated but missed.** The returning peer discovers and traverses the Merkle-DAG from the root to catch up
- Other peers periodically republish current heads via `rebroadcast_interval` (default: 1 minute)
- Sync time depends on DAG depth; for faster recovery, reduce `rebroadcast_interval` to 5-10 seconds

**Conflict resolution:** CRDT uses priority based on DAG height—higher height wins. Same height uses alphabetical ordering. All peers eventually converge to identical state (strong eventual consistency).

**Key difference from Raft:** CRDT tolerates divergent states and requires only **one healthy trusted peer** for recovery. Raft requires >50% peers online and doesn't allow divergence.

**Edge case warning (GitHub #803):** Untrusted peers can control/remove pins if they're the only ones allocated for that pin. Always include at least one trusted peer in critical allocations.

**Sources:**
- https://ipfscluster.io/documentation/guides/consensus/
- https://github.com/ipfs-cluster/ipfs-cluster/issues/798
- https://discuss.ipfs.tech/t/ipfs-cluster-consistency-model/6666

---

## 6. Implementing "primary + backup + dynamic" allocation

**No native pattern exists** for this model, but it's achievable through configuration:

### Recommended architecture for your use case

```
┌──────────────────────────────────────────────────────────┐
│  Tag Configuration per Node Type                         │
├──────────────────────────────────────────────────────────┤
│  Primary nodes (3-4):   tag:tier = "primary"             │
│  Backup nodes (3-4):    tag:tier = "backup"              │
│  Dynamic nodes (3-4):   tag:tier = "dynamic"             │
└──────────────────────────────────────────────────────────┘
```

**Cluster configuration:**
```json
{
  "cluster": {
    "replication_factor_min": 2,
    "replication_factor_max": 4,
    "disable_repinning": false
  },
  "consensus": {
    "crdt": {
      "trusted_peers": ["primary1_id", "primary2_id", "backup1_id", "backup2_id"]
    }
  },
  "allocator": {
    "balanced": {
      "allocate_by": ["tag:tier", "freespace"]
    }
  }
}
```

**Pinning workflow:**
```bash
# Pin to specific primary + backup, let dynamic node be chosen by freespace
ipfs-cluster-ctl pin add <cid> \
  --allocations "local_peer,backup_peer" \
  --replication-min 2 \
  --replication-max 3 \
  --name "important-data"
```

This pins to your specified local and backup peers first, then the balanced allocator selects the third replica from remaining peers based on freespace.

**Extension points exist** but require code changes: The `Allocator` and `Informer` interfaces allow custom implementations, but there's no plugin system—you must fork and recompile.

**Sources:**
- https://ipfscluster.io/documentation/reference/configuration/
- https://github.com/ipfs-cluster/ipfs-cluster/issues/646
- https://ipfscluster.io/documentation/collaborative/setup/

---

## Critical gotchas and edge cases

1. **Default behavior changed in v0.14:** `disable_repinning` now defaults to `true`. Most users expect automatic failover but don't get it without explicit configuration.

2. **Silent substitution at pin time:** If your explicit allocations include unavailable peers when you first pin, they're silently replaced—no error thrown.

3. **No automatic increase:** With 2 allocations and max=5, the cluster won't try to reach 5 replicas automatically. You must explicitly re-pin to trigger allocation increases.

4. **Returning peer after re-allocation:** If re-allocation was triggered (below min threshold), the returning peer gets its content **unpinned**—it's no longer in the allocation list.

5. **CRDT DAG depth:** Long-running clusters accumulate deep Merkle-DAGs. New/returning peers must traverse from root, which can be slow. Consider periodic state export/import for compaction.

6. **Metric TTL for large clusters:** Increase `metric_ttl` to 5 minutes for 10+ node clusters to reduce network chatter.

---

## Final recommendation

**Yes, you can use explicit allocations with automatic rebalancing—but configure carefully:**

1. **Set `disable_repinning: false`** to enable automatic failover
2. **Use replication factor ranges** (e.g., min=2, max=4) to provide failover headroom without excessive churn
3. **Implement tag-based tiers** (`primary`, `backup`, `dynamic`) with the balanced allocator
4. **Specify explicit allocations per-pin** for your primary + backup requirement, letting the third replica be dynamically assigned
5. **Use CRDT consensus** for your 10-12 node cluster—it handles partitions gracefully and only needs one healthy trusted peer for recovery

**The limitation:** Automatic re-allocation only kicks in when crossing below `replication_factor_min`, not immediately when any peer fails. If you need faster failover, consider setting a lower min (e.g., min=1, max=3) and accepting that single-replica state triggers immediate re-allocation.

**Key documentation sources:**
- Configuration reference: https://ipfscluster.io/documentation/reference/configuration/
- Pinning guide: https://ipfscluster.io/documentation/guides/pinning/
- Consensus modes: https://ipfscluster.io/documentation/guides/consensus/
- Security guide: https://ipfscluster.io/documentation/guides/security/
- GitHub issues #277, #369, #646, #798, #803: https://github.com/ipfs-cluster/ipfs-cluster/issues