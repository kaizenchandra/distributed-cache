# Consistency, replication, fencing and migration

Successful requests are serialized at one coordinator and read only their current primary. SET acknowledgment means
every configured owner replied after applying the entry. There is no WAL, durable consensus or crash-safe
acknowledgment. Failure partway through replication leaves ambiguous partial state; coordinator pauses after mutation
RPC failure. Clients must not automatically retry mutations. Global serial ordering does not make this a fault-tolerant
linearizable database.

Versions are increasing coordinator-local longs. Same/older versions are ignored when a stored entry/watermark exists.
Deletes use versioned tombstones. Expiration is absolute coordinator Unix milliseconds, evaluated with node clocks:
synchronize clocks; skew changes visible expiration. Expiration retains a watermark and cannot remove a newer version
because both actions take the same lock. Tombstones are capacity bounded and may be evicted. Replica reads and automatic
promotion are forbidden, preventing stale replica resurrection through a supported API. Do not reuse an evicted replica
as authority without rebuilding it.

Storage rejects any apply epoch unequal to its current fence. A topology change holds the same coordinator monitor as
mutations, fences all old/new nodes, copies only entries whose old primary is the source, transfers pages of 32, checks
response bytes/version/expiry/delete marker, then activates. Transfer admission refuses capacity overflow instead of
evicting verified entries. Source replicas are retained; they are never automatically promoted. Concurrent expiration
can make entries unavailable but cannot extend their absolute lifetime. Mutation delta capture is unnecessary because
mutations are blocked. This is bounded-page quiesced migration, not uninterrupted online rebalancing. There is no
range-level incremental retry/resume or bandwidth throttle. Failure leaves the coordinator unavailable; no automatic
rollback. It requires all old nodes reachable, so it cannot remove a crashed node. In-memory epoch is lost on restart;
bootstrap refuses nonfresh nodes. Reset all nodes to start a new empty volatile cluster.

Epochs only fence already contacted storage nodes. They do not protect against duplicate coordinators using internal
credentials or unsafe operator promotion. Production fencing requires an authoritative consensus-backed epoch allocator
and storage-enforced leases/terms, plus a durable recovery protocol. Kubernetes discovery alone cannot supply that
guarantee. Never run two coordinators.

R+W>N provides overlap only when participants and version rules agree. Concurrent coordinators, sloppy quorums, stale
membership and nonmonotonic reads can still violate linearizability. This implementation uses R=1 primary, W=N, and
makes no quorum failover guarantee.
