# Isolated JMH results

Date: 2026-11-16. Java 21.0.13.0.3, macOS ARM64, JMH 1.37. Local Docker/Kubernetes and existing development containers
were present. These measurements are local storage microbenchmarks, not client or replicated throughput.

The hit-and-copy runs used 1,024 permanent 128-byte entries in a shared synchronized Store, a 16 MiB logical limit, two
forked JVMs, three 1-second warmups and five 1-second measurement iterations per fork, with `-prof gc` and 256 MiB fixed
heaps. Each operation includes the defensive value copy. Throughput is aggregate across benchmark threads. Results
include GC/allocation profiling; no network, serialization, routing, topology or consensus work occurs.

| Policy | Threads | Mean operations/sec | 99.9% score confidence interval (ops/sec) | Allocation bytes/op |
|--------|--------:|--------------------:|-------------------------------------------|--------------------:|
| LRU    |       1 |         59556316.58 | 57684570.97–61428062.18                   |             144.000 |
| LFU    |       1 |         58293068.02 | 57381954.64–59204181.40                   |             144.000 |
| LRU    |       4 |         15816676.93 | 14884496.96–16748856.90                   |             144.001 |
| LFU    |       4 |         16076300.37 | 15366331.27–16786269.47                   |             144.001 |

The four-thread shared-store runs were slower in this trial. This is an observation under shared-host conditions, not a
causal profiling proof or a policy ranking. Do not interpret millions of in-process operations as distributed cache
throughput. No latency percentiles or availability guarantee were measured.

`smoke.json` covers all six benchmark methods for LRU/LFU with 128-byte values (11 parameterized cases). It used one
fork, one 200 ms warmup, and two 300 ms measurements with GC profiling. Its purpose is execution verification, not
stable performance comparison. FIFO and 4 KiB parameter values are supplied by the benchmark but were not measured in
this update.

Benchmark boundaries: `hit` returns entry metadata without copying the payload; `hitAndCopy` also allocates a defensive
copy; `miss` performs an absent lookup; `overwrite` includes entry allocation and an AtomicLong version generator and
can reject out-of-order versions under contention; `eviction` has a separate 64 KiB thread-local Store per worker;
`expireSweep256` replenishes 256 expired entries in invocation-level setup and times a sweep. Expiration setup
allocations affect GC profiling even though replenishment is outside timed method work, so its B/op is not isolated
expiration allocation. Do not compare expiration sweep throughput directly to single-key operation throughput.

Raw JMH JSON, including confidence intervals, iteration samples, JVM settings and secondary GC metrics, is retained
alongside this README. Reproduce commands in [help.md](../../../help.md).

Upstream reference: [OpenJDK JMH samples and packaging](https://github.com/openjdk/jmh/tree/master/jmh-samples).
Benchmark setup and interpretation remain workload-specific.
