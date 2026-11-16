# Performance verification

The project now includes a bounded client HTTP load generator supporting closed-loop counts and open-loop scheduled
demand, multiple gateway endpoints, seeded uniform/Zipfian keys, read/write mixes, configurable values, TTL churn, and
memory-pressure workloads. It reports successful client operations/sec, HTTP/transport errors, real read hit/miss
counts, per-operation latency histograms, and arrivals dropped by the scheduler or busy worker limit. It never equates
staged replication operations with successful client requests.

See [actual local measurements](performance-results/2026-11-16/README.md) and [commands](../help.md). The five executed
workloads include mixed traffic, 50-arrival/sec skewed traffic, 10k scheduled-arrival saturation, short TTLs, and large
permanent values causing memory pressure. The mixed workload returned 409 conflicts; the saturation workload dropped
demand before dispatch. These outcomes are retained in the results rather than counted as passes against a throughput
target.

`python3 scripts/test_load.py` verifies generator accounting against a real local HTTP fixture: hit counts, fixed
in-flight concurrency under overload, complete arrival accounting and error/nonzero-exit reporting. Fixed-size latency
histograms report upper-bound percentiles at 5% bucket spacing. Priming/warmup are excluded; drain time is included in
throughput. At most 256 workers and 100,000 keys are permitted. There is no unbounded request queue or latency sample
array.

For scheduled demand tiers, set `--rate 10000`, `100000`, `1000000`, `5000000` or `10000000` with a chosen duration.
Only the 10k tier was executed. At high targets this single Python process will drop arrivals; a configured target is
not proof that the server received that rate. Inspect scheduled, dispatched, dropped and successful counts. Exit 1 means
request errors, 2 means drops without errors, and 0 means neither occurred. Conflicting writes may return the documented
409; blind replay is deliberately absent.

Isolated JMH storage benchmarks are now implemented and executed; see [benchmark results and boundaries](benchmark-results/2026-11-16/README.md) and [commands](../help.md). They do not measure distributed throughput.

Remaining performance work: synchronized distributed load generation across
independent hosts; long warmup and steady-state trials; repetitions/confidence intervals; continuous CPU/GC/heap/network
and replication/rebalance instrumentation; 100k/1M/5M/10M received-rate campaigns; controlled degradation/rebalancing
during load. No 1M client-ops/sec, p99 below 5 ms, or 99.99% availability target has been demonstrated. Testcontainers
is not required by the existing native/Docker suites and has not been introduced.

Exact eviction scans, global storage locks, Base64 allocation and sequential synchronous replication remain expected
bottlenecks, not established causal profiling results. G1 versus ZGC, gRPC/Netty transport and topology lookup caching
should be compared only under equivalent measured workloads without weakening fencing/consistency semantics.
