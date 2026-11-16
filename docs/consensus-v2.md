# Consensus-backed cache mode

Historical initial design: [current metadata, repair and etcd security behavior](metadata-repair-security.md) supersedes
the fixed-slot and unsecured-client details below. Existing fixed-slot namespaces require an explicit migration; the new
code refuses to reinterpret them.

Select `cache.mode=consensus` on every JVM. Legacy controllers are disabled in this mode, including `/internal/apply`
and `/internal/fence`; they cannot bypass the new publication protocol. Legacy mode remains the default for
compatibility with the original sample. Use `compose.consensus.yaml` for the new topology. Do not mix the modes in a
namespace.

## Authority and visibility

etcd 3.6.5 supplies Raft-backed metadata transactions, not cache values. The implementation uses its v3 JSON gateway,
linearizable range reads and atomic mod-revision comparisons. Each namespace has one topology document containing node
URLs, process incarnations, virtual-node count, replication factor, minimum copies and metadata slot count. Every
storage JVM publishes a five-second etcd lease registration once a second. Multiple gateways may reconcile expired
registrations into the topology with compare-and-swap. A timeout is suspicion; an expired authoritative lease plus a
committed topology revision changes ownership. Kubernetes discovery is not used as a consensus substitute.

A SET reads the current topology and key manifest, stages a new UUID-addressed immutable byte value at the current ring
owners, waits for their acknowledgments, then CAS-publishes a manifest only if both the topology revision and previous
manifest revision still match. Concurrent writers stage independent UUIDs; at most one publishes against the same prior
manifest. CAS returns 409 on conflict, including topology change. Versions are increasing per-slot revision-derived
tokens, not a global count of client operations. Unpublished staged payloads consume bounded storage and are evicted
normally. A timeout after publication remains ambiguous; clients do not automatically retry mutations.

GET reads the authoritative manifest through etcd, then fetches only its exact payload UUID/version from its recorded
owners. The first owner is the nominal primary; an unavailable copy is bypassed in favor of a replica of that same
committed version. A missing committed payload returns a cache miss, never an older version. Deletes and TTL are
committed metadata; deleting does not depend on a tombstone surviving local eviction. Expiration uses absolute
milliseconds and still depends on synchronized clocks.

## Storage-enforced fencing

Each stage validates the topology revision against a linearizable etcd read and checks the destination process
incarnation. A restarted empty process receives a new UUID incarnation. Epoch validation alone has a check/apply race: a
topology change can occur immediately after validation. Immutable staging plus the final topology-and-manifest CAS
closes the visibility race: an old owner may retain late staged bytes, but cannot publish them under an obsolete
revision. Internal fetches are not client-visible authority; the gateway must first obtain the current pointer. Old
gateways disconnected from quorum cannot serve public cache operations. Internal credentials and etcd write permissions
remain privileged; this is a crash/partition protocol, not Byzantine security.

## Failover and repair

Gateway instances do not elect a single active gateway; per-key etcd CAS arbitrates concurrent operations. A gateway
crash requires no promotion or local coordinator journal. Any other gateway can continue. The typed client still targets
one URL: use a health-checked load balancer for endpoint failover, and do not blindly replay timed-out mutations.

Expired storage registration changes the ring. Committed values remain readable from surviving recorded replicas. Each
gateway scans sixteen fixed manifest slots per maintenance tick. For each live committed entry it fetches an
exact-version surviving copy, stages and verifies copies on the new ring owners, then CAS-updates the owner list against
unchanged topology and manifest revisions. Copying is idempotent, supports concurrent client writes, and also
reconstructs an empty restarted node or a copy evicted from an otherwise unchanged owner set. Concurrent writes
supersede repairs by changing the manifest revision. Source payloads are retained until ordinary bounded-cache eviction.
There is no stop-the-world snapshot or delete-at-source phase.

Default RF=3, minimum available members=2. Writes acknowledge all owners selected from the current topology, so a
failure from four storage nodes to three retains RF3; a failure from three to two allows two-copy acknowledgment. Below
two members all public operations reject with 503. During lease expiry/reconciliation a write can still target an
unavailable owner and fail transiently. The topology reports configured minimum and replica factor. Repair cannot
recover a payload lost from every recorded owner; that is a cache miss, not durable recovery. Metadata consensus does
not make payloads durable.

## Bounded metadata and operational limits

There are `cache.metadata-slots` fixed hash slots (default 4096, max 65536). The manifest stores the original logical
key and each read verifies it. A slot collision intentionally evicts the previous key manifest, like a direct-mapped
admission policy; it is never treated as the other key. This bounds current metadata but can significantly reduce hit
ratio before local memory fills. This is an explicit interim trade-off, not an unbounded metadata index or a
hash-collision correctness shortcut. Increase slots consistently on a fresh namespace; configuration mismatch is
rejected. Changing slot count live is unsupported.

One repair scan cycle is roughly slots/16 maintenance ticks, plus RPC time. Default 4096 slots is at least 256 seconds.
Replica RPCs and publication metadata requests are sequential, so this is not a high-throughput architecture. Historical
etcd revisions require compaction and backend quota monitoring; current slot count does not bound uncompacted disk
history. The compose example enables periodic compaction. Lease grant per heartbeat adds metadata traffic and expired
leases; optimize with streaming keepalive only after verification.

## Run and verify

```sh
# Export the three distinct CACHE_*_TOKEN variables as in README.
docker compose -f compose.consensus.yaml up --build -d
# No manual bootstrap required: membership reconciles automatically.
curl -H "Authorization: Bearer $CACHE_ADMIN_TOKEN" localhost:8080/admin/topology
mvn verify
ETCD_BIN=/path/to/etcd python3 scripts/consensus_failure.py
```

The failure suite launches three real etcd processes, four storage JVMs and two gateway JVMs; it uses isolated temporary
etcd data directories and cleans up child processes. It requires local TCP binding and platform-matching etcd and
etcdctl binaries. Set ETCDCTL_BIN if etcdctl is not next to ETCD_BIN. The harness rejects occupied ports and checks
child-process liveness before accepting results. Logs go to target/consensus-*.log. It tests cross-gateway CAS, primary
kill, repair to spare, empty restart, stale incarnation/epoch RPC rejection, stale publication transaction rejection
(including a real timed-out transaction held at a transport gate until ownership changes), gateway partition via an HTTP
transport gate, gateway crash/restart, delete visibility, actual etcd leader failure/re-election and quorum loss. It
does not emulate packet loss, arbitrary storage-node partitions, delayed application after authorization, long GC pauses
or simultaneous loss of all data copies.

## Security and recovery

The compose example is for a trusted private network and does not provision etcd authentication/mTLS. Do not expose its
etcd ports or internal APIs. Production operation requires an authenticated, TLS-protected etcd deployment and a
suitably configured client transport; those client-auth options are not implemented here. No production Kubernetes/Helm
deployment of the new authority is supplied yet. Existing Kubernetes manifests remain the legacy baseline.

Restart gateways freely while retaining etcd metadata. Restart storage nodes sequentially and wait for replica repair
before stopping another. Inspect `/internal/consensus/stats` for incarnation and logical storage; `/admin/topology`
reports committed topology. Losing etcd quorum deliberately stops reads and writes. Restore member quorum using etcd
operational procedures; never bootstrap an independent overlapping authority with old credentials. If metadata is
restored from an old snapshot, reset the cache namespace/storage together: rollback of metadata can otherwise revive old
pointers. Full loss of payload copies requires backing-store refill. No durability, availability SLO or distributed
throughput target is claimed.

Sources: https://etcd.io/docs/v3.6/learning/api/ and https://etcd.io/docs/v3.6/learning/api_guarantees/ .
