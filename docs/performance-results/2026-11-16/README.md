# Measured local client workloads

Date: 2026-11-16. macOS ARM64 host, OrbStack Docker Engine 29.8.2 / Compose 5.5.0; Docker reports 11 CPUs and
9,434,791,936 bytes of VM memory. Consensus Compose topology: three etcd 3.6.5 containers (256 MiB limits), four storage
JVMs and two gateways (512 MiB limits each). Other local development containers were present, so these are not
isolated-machine capacity measurements.

These are short smoke measurements from the Python HTTP generator, including client/JSON/network/etcd/storage work.
Seeding and warmup are excluded; drain time is included. Successful requests include both cache hits and misses. No
retries hide conflicts. Quantiles below are successful GET latency histogram upper bounds with 5% spacing. These runs do
not establish maximum capacity, steady-state latency or any production SLO.

| Workload                              | Scheduled | Completed / successful | Errors | Dropped before dispatch | Successful ops/sec | GET p99 upper bound (ms) | Hit ratio |
|---------------------------------------|----------:|-----------------------:|-------:|------------------------:|-------------------:|-------------------------:|----------:|
| [mixed](mixed.json)                   |       200 |              200 / 197 |      3 |                       0 |             629.56 |                    9.813 |      1.00 |
| [zipf-50](zipf-50.json)               |       250 |              250 / 250 |      0 |                       0 |              49.96 |                   23.616 |      1.00 |
| [offered-10k](offered-10k.json)       |     20000 |            2363 / 2363 |      0 |                   17637 |            1179.46 |                   15.984 |      1.00 |
| [ttl-churn](ttl-churn.json)           |       100 |              100 / 100 |      0 |                       0 |             911.15 |                     4.72 |      0.00 |
| [large-eviction](large-eviction.json) |       100 |              100 / 100 |      0 |                       0 |             460.87 |                    9.346 |      0.88 |

The mixed run recorded three HTTP 409 write conflicts, consistent with optimistic per-key publication under concurrent
writes. It exited 1 and is not an error-free test. No automatic retry was performed. The 10k scheduled-demand run exited
2 because the fixed worker limit dropped arrivals: only dispatched requests reached the cluster. The generator itself
and client HTTP setup can limit throughput, so this is not a measured cluster-capacity ceiling.

TTL priming with 25 ms expiration yielded misses, which still count as successful HTTP cache operations. The large-value
run seeded 400 distinct permanent 64 KiB values, exceeding per-node logical capacity under three-copy placement, then
observed misses under memory pressure. It did not measure exact JVM heap accounting. Immutable staged payloads and
background repair also consume bounded cache space.

Commands are in [help.md](../../../help.md). Run configuration (mix, value size, key count, seed, URLs, concurrency,
duration and target rate where applicable) is recorded in each JSON file. The 10k run occurred before the final rerun of
the other four workloads; no comparison claims equal cache/JIT/repair state. JVM metrics and container stats snapshots
were collected under `target/performance/`, after the initial campaign rather than continuously during requests; they do
not establish peak CPU, GC or network utilization.
