# Failure analysis

Every entry states cause/impact and mitigation/recovery. Tests marked pending have not been executed. Residual risk
across all scenarios: volatile data and single-authority availability; no production failover protocol.

| #  | Scenario                         | Behavior, mitigation and recovery                                                         | Verification                                       |
|----|----------------------------------|-------------------------------------------------------------------------------------------|----------------------------------------------------|
| 1  | Concurrent updates               | Coordinator monitor orders writes; CAS returns 409 to losers.                             | CAS race integration test                          |
| 2  | Primary crash during replication | Partial state; ambiguous 503; stop uncertain mutations and diagnose/reset.                | process failure smoke; mid-write injection pending |
| 3  | Duplicate replication            | Stored equal version ignored; no replay guarantee after eviction.                         | ordering unit test                                 |
| 4  | Out-of-order replication         | Lower retained version ignored.                                                           | ordering unit test                                 |
| 5  | Old primary                      | Storage rejects stale fenced epoch; disconnected stale primary has no public write route. | fence unit test                                    |
| 6  | Split network                    | No promotion; authority/owner unavailable gives 503.                                      | partition injection pending                        |
| 7  | Join during writes               | One monitor pauses operations through transfer.                                           | join integration; sustained load pending           |
| 8  | Leave during transfer            | RPC error leaves cluster unavailable.                                                     | fault test pending                                 |
| 9  | Stale ring client                | Typed client only knows coordinator endpoint.                                             | routing integration                                |
| 10 | Stale promotion                  | Unsupported; never promote stale replicas.                                                | no promotion test                                  |
| 11 | Expire during migration          | Absolute expiry retained; expired data remains invisible.                                 | combined race pending                              |
| 12 | Eviction during replication      | Replicas may evict different data; primary only reads avoid resurrection.                 | eviction unit; distributed pressure pending        |
| 13 | Memory limit                     | Evict under lock or reject oversized entries; transfer refuses eviction.                  | memory concurrency unit                            |
| 14 | Timeout after SET                | 503 can mean applied; no automatic mutation retries.                                      | timeout injection pending                          |
| 15 | Partial batch                    | Batch API is unsupported.                                                                 | not applicable                                     |
| 16 | Empty restarted node             | No repair; fail/reset required, volatile data may be missing.                             | restart test pending                               |
| 17 | Multiple failures                | Unavailable owners produce errors; no quorum recovery.                                    | multiple failure test pending                      |
| 18 | Coordinator unavailable          | All operations unavailable; no alternate authority.                                       | kill test pending                                  |
| 19 | Expiration under load            | Store lock serializes expiry and mutation, adding contention.                             | heavy TTL churn pending                            |
| 20 | Hot key                          | Coordinator bottleneck; rate limit/coalesce at application.                               | Zipf test pending                                  |
| 21 | Large values                     | 64KiB and request/thread caps constrain individual allocations.                           | congestion test pending                            |
| 22 | Replica lag                      | Sync operations time out; no growing async queue.                                         | latency injection pending                          |
| 23 | Topology during retries          | Coordinator serializes; client never automatically retries.                               | retry fault test pending                           |
| 24 | Evicted data resurrection        | No replica read/promotion; primary-only transfer avoids copying stale replicas.           | rebalance pressure test pending                    |
| 25 | Lost delete                      | Tombstones while retained; unsafe recovery can lose them. No durability guarantee.        | delete integration; crash recovery pending         |
