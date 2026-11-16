# Architecture review

1. **Consistent hashing** — Only ranges captured by new points move; modulo hashing changes most mappings.

2. **Virtual nodes** — Multiple independently placed points smooth ownership; 128 is configurable.

3. **Uneven distribution** — Uniform-key tests bound skew; weighted points and failure domains remain future work.

4. **Replica selection** — Clockwise ring traversal skips duplicate physical URLs.

5. **Primary replicas** — Coordinator applies primary then replicas and waits for all.

6. **Sync vs async** — Sync waits for apply; async can acknowledge before remote copies exist.

7. **Write latency** — Sequential synchronous round trips grow roughly with owner count.

8. **Primary crash** — A mutation can be partially applied; 503 is ambiguous, no promotion occurs.

9. **Split brain** — One manual coordinator only; duplicate authorities are unsafe and unsupported.

10. **Epoch fencing** — Store.apply rejects unequal epochs, but durable authoritative issuance is missing.

11. **Consistency** — Serialized primary reads/CAS in healthy single-authority operation; no durable or HA guarantee.

12. **Delete resurrection** — Possible with unsafe stale promotion; supported APIs never promote replicas.

13. **Stale replication** — Versioned tombstones reject older writes while retained; eviction/restart loses watermarks.

14. **LRU vs LFU** — LRU ranks recency; LFU ranks access count and uses recency as tie-breaker.

15. **Exact LRU cost** — Every hit updates shared metadata; eviction scans contend on one lock.

16. **Memory bounds** — Logical weight and hard capacity admission under lock; JVM heap overhead is separate.

17. **TTL replication** — Absolute expiry timestamps travel with versions; clock synchronization is required.

18. **Node join** — Coordinator pauses operations and fences all nodes before transfer.

19. **Migration** — Only old primary copies are transferred in pages, verified before topology activation.

20. **Stale clients** — Clients route through one authority and hold no ring; automatic endpoint failover is absent.

21. **Network partition** — Requests needing unreachable owners fail; uncertain mutations pause service.

22. **Stale replicas** — No automatic repair; reset/rebuild is required, never blindly promote.

23. **Replica reads** — Disabled to avoid stale-read and resurrection semantics.

24. **Hot keys** — Serialized hot keys overload coordinator; application sharding/rate limiting needed.

25. **Stampedes** — Loading/coalescing is not implemented; applications need single-flight and jitter.

26. **100-node scale** — Ring can map 100 nodes; serialized control/data coordinator prevents throughput scaling.

27. **GC p99** — Allocation and pauses affect latency; no GC tuning claim without measurement.

28. **Netty/gRPC** — Prefer binary bounded streaming for measured HTTP bottlenecks; not implemented here.

29. **Benchmarking** — Count successful external requests with offered rate, errors, hit ratio, latency and host
    telemetry.

30. **Volatile guarantees** — Eviction, expiry, crashes and resets can lose entries; use an authoritative backing store.
