# How to test this project

Run commands from the project root. Use Java 21, Maven 3.6.3+, and Python 3. The JVM tests require no credentials,
Docker, or external cache. Integration tests use their own temporary test credentials and launch real processes. Do not
run them against production infrastructure.

## 1. Build and unit tests

```sh
# macOS: select Java 21 for Maven and child processes
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export PATH="$JAVA_HOME/bin:$PATH"
java -version
mvn -version
mvn -B clean verify
```

On Linux, set JAVA_HOME to your installed JDK 21. Both version commands should report Java 21. Expect 13 tests with zero
failures/errors/skips and `BUILD SUCCESS`. Reports: `target/surefire-reports/`. The executable artifact is
`target/distributed-cache-0.1.0.jar`.

Tests cover ring distribution/movement, replica uniqueness, eviction, TTL/version ordering, fencing, concurrent
accounting, defensive copies, consensus metadata addressing/configuration, and batch validation/partial success. They do
not prove full distributed correctness.

If a restricted environment prevents Maven writing to its cache, copy the existing dependency repository to writable
temporary storage and use `mvn -o -Dmaven.repo.local=/tmp/cache-m2 clean verify`. Offline mode requires all dependencies
to be cached already.

## 2. Five-JVM regression (no Docker)

```sh
python3 scripts/integration.py
```

Requires the packaged jar from step 1, `java` on PATH, and free localhost ports 19080–19084. It checks routing,
replication contents, stale fencing, metrics authentication, CAS contention, TTL, deletion, four-node migration,
authorization, node failure, batch partial success and malformed-request rejection. Success prints `PASS`; failures
return a nonzero exit code. Logs remain in `target/process-*.log`; child processes are stopped in `finally`. The script
refuses occupied ports. Do not rebuild/replace the jar while test JVMs run.

If socket binding reports `Operation not permitted`, allow loopback sockets in the execution environment. If binding
reports `Address already in use`, stop the process using the test ports first.

## 3. Consensus and security failure tests

Install pinned etcd and etcdctl 3.6.5 locally (macOS/Linux on ARM64 or AMD64):

```sh
python3 scripts/install-etcd.py
# Use the export ETCD_BIN command printed by the installer. On this macOS ARM64 host:
export ETCD_BIN="$PWD/.tools/etcd-v3.6.5-darwin-arm64/etcd"
"$ETCD_BIN" --version
"$(dirname "$ETCD_BIN")/etcdctl" version
python3 scripts/consensus_failure.py
CACHE_SECURE_TEST=1 python3 scripts/consensus_failure.py
```

The installer downloads the official GitHub release and verifies its pinned SHA-256 digest before installing only the
two executables into git-ignored `.tools/`. No system installation or sudo is needed. On Linux AMD64, the directory is
`.tools/etcd-v3.6.5-linux-amd64`. For an already downloaded official archive, use
`python3 scripts/install-etcd.py --archive /path/to/archive`; the same digest check applies. The verified macOS ARM64
archive digest is `14d7743f9ed07950a8e85491646e067e394a09e049e42083e2f6473fefa717a8`.

ETCD_BIN must point to the executable, not its directory. The suite finds etcdctl alongside it; use ETCDCTL_BIN to
override. It fails early if the packaged jar or either tool is missing. Do not run plaintext and secure suites
concurrently: they share ports and log names. To preserve logs, copy `target/consensus-*.log` into a separate directory
after each run. Recently closed connections are allowed during preflight, but live listeners are rejected.

The secure run also requires OpenSSL and the JDK `keytool` on PATH. The fixture creates temporary certificates; it does
not install system trust roots. These tests launch three etcd members, four storage JVMs and two gateways; secure mode
also starts a short-lived gateway with deliberately invalid credentials. Reserve ports 33379–33384, 33400, 31080–31082
and 31091–31094. Inspect the script's preflight list if adapting ports. Logs go under `target/`. Expect a final `PASS`
and exit code 0. Coverage includes consensus batch partial success, cross-gateway TTL/deletion, concurrent CAS, primary
crash/repair, empty restart, stale incarnation/epoch/publication rejection, gateway partition/restart, leased
repair-worker handoff, bounded metadata admission, actual etcd Raft leader replacement, and rejection after quorum loss.
Secure mode repeats these with authenticated mTLS for etcd and adds negative certificate/credential/namespace tests.
Cache HTTP transport remains separate from etcd mTLS. See [consensus semantics](docs/consensus-v2.md)
and [security constraints](docs/metadata-repair-security.md) for the covered failures and remaining risks.

## 4. Verified Docker Compose and chaos tests

Requires a running Docker Engine and Compose 2.24.4+ (`!override` port support). Verified locally with Engine 29.8.2 and
Compose 5.5.0. From the repository root:

```sh
python3 scripts/init-env.py
python3 scripts/compose-test.py --mode legacy --chaos
python3 scripts/compose-test.py --mode consensus --chaos
```

Run the commands sequentially. Each command builds the Java 21 image, starts its own disposable project
(`cache-verify-legacy` or `cache-verify-consensus`), polls readiness, verifies authenticated operations/metrics and
injects failures. Success prints `PASS` per check and exits 0. It saves `target/compose-<mode>/result.json`,
`containers.json`, and `containers.log` before removing its containers, network and volumes in `finally`. These project
names are reserved for disposable tests; do not store valuable data in them. Existing `distributed-cache` containers on
port 8080 are preserved. Test gateways use localhost ports 18080/18081. Do not run these suites concurrently.

Legacy checks: SET/GET, CAS conflict, batch partial success, TTL, DELETE, missing-auth rejection, Prometheus metrics,
and storage SIGKILL causing fail-closed writes. It does not promise automatic recovery after empty storage restart.

Consensus checks: three actual etcd containers, four storage JVM containers, two gateways; API checks plus one paused
etcd member, actual primary SIGKILL, repair to live owners, empty restart with changed incarnation, gateway pause, two
paused etcd members, read/write rejection without quorum, and recovery after restoration. Election/topology changes can
produce temporary 409/503 responses; the harness waits for bounded recovery and records failed recovery probes. Every
write probe after an outage uses a fresh key so it does not blindly replay ambiguous mutations. This is a short
deterministic chaos campaign, not exhaustive partitions/packet-loss/latency/CPU-throttling coverage.

Use `--skip-build` after building these exact project images. Use `--keep` to retain a test cluster for investigation or
load tests; it also retains failed runs, so inspect the exit code and result JSON. Stop only that test project
afterward:

```sh
docker compose -p cache-verify-consensus -f compose.consensus.yaml -f deploy/compose.consensus-test.yaml down -v --remove-orphans
```

The test harness unpauses affected containers before cleanup. An uncatchable host/process kill can interrupt cleanup;
the command above removes leftover consensus test resources. For legacy cleanup substitute `cache-verify-legacy`,
`docker-compose.yaml`, and `deploy/compose.legacy-test.yaml`.

For a manually managed local development cluster, the original commands remain:

```sh
python3 scripts/init-env.py
set -a
. ./.env
set +a
docker compose up --build -d
curl --fail http://localhost:8080/actuator/health
curl --fail -H "Authorization: Bearer $CACHE_ADMIN_TOKEN" -X POST http://localhost:8080/admin/bootstrap
curl --fail -H "Authorization: Bearer $CACHE_CLIENT_TOKEN" -H 'Content-Type: application/json' http://localhost:8080/api/v1/operation -d '{"operation":"SET","key":"aw","value":"dmFsdWU=","ttlMillis":-1}'
curl --fail -H "Authorization: Bearer $CACHE_CLIENT_TOKEN" -H 'Content-Type: application/json' http://localhost:8080/api/v1/operation -d '{"operation":"GET","key":"aw","ttlMillis":-1}'
curl --fail -H "Authorization: Bearer $CACHE_ADMIN_TOKEN" http://localhost:8080/actuator/prometheus
```

Wait for health before bootstrap. Bootstrap requires fresh storage. GET should return `found:true` and
`value:"dmFsdWU="`. Keys from the typed client are unpadded Base64url bytes; values are standard Base64. Explicitly
supply TTL: -1 permanent, 0 immediate deletion, positive milliseconds. Missing JSON TTL currently means 0.

Batch MGET/MSET equivalents use `POST /api/v1/cache/batch` with the same client token:

```json
{
  "operations": [
    {
      "operation": "SET",
      "key": "aw",
      "value": "dmFsdWU=",
      "ttlMillis": -1
    },
    {
      "operation": "GET",
      "key": "aw",
      "ttlMillis": -1
    }
  ]
}
```

The HTTP response is 200 with an ordered array of `{status,result,error}` items. Each item is independent; this is not a
transaction or snapshot. Maximum 100 operations and 100,000 request bytes. Invalid envelopes are rejected before any
execution. Operational failures can leave earlier writes successful; status 503 means the write outcome may be
ambiguous. Never retry an entire batch blindly. `CacheClient.batch` exposes these results to Java callers.

For consensus deployment instead use `docker compose -f compose.consensus.yaml up --build -d` and its documented gateway
ports. It automatically reconciles membership; do not use legacy bootstrap. Stop each topology with its corresponding
Compose `down` command. Local Compose does not establish production transport security.

## 5. Verified performance workloads

First retain an isolated consensus cluster:

```sh
python3 scripts/compose-test.py --mode consensus --keep
set -a
. ./.env
set +a
python3 scripts/test_load.py
python3 scripts/load.py --url http://localhost:18080 --url http://localhost:18081 --rate 50 --duration 5 --workers 8 --keys 20 --distribution zipf --read-ratio .95 --output target/performance/zipf-50.json
```

The three load-generator tests use a local HTTP fixture to verify real hit counts, bounded overload/drop accounting, and
nonzero exit status for server errors. The cluster workload primes its keyspace and excludes priming/warmup from timing.
Repeated `--url` options split traffic across gateways. It uses canonical binary-key encoding, reports GET hits/misses
separately, counts errors by HTTP status and operation, and maintains fixed-size latency histograms. Percentiles are
bucket upper bounds with 5% spacing, not exact sample percentiles. Each run uses a fresh key prefix; metadata remains
retained until the disposable cluster is reset.

Other workloads executed locally:

```sh
# Closed-loop mixed traffic. Concurrent writes may return documented 409 conflicts.
python3 scripts/load.py --url http://localhost:18080 --url http://localhost:18081 --requests 200 --workers 4 --keys 20 --read-ratio .8 --output target/performance/mixed.json
# Saturation: scheduled demand, not a claim that 10k requests/sec reach the server.
python3 scripts/load.py --url http://localhost:18080 --url http://localhost:18081 --rate 10000 --duration 2 --workers 8 --keys 20 --read-ratio 1 --output target/performance/offered-10k.json
# Short TTLs produce real misses after priming.
python3 scripts/load.py --url http://localhost:18080 --requests 100 --workers 2 --keys 10 --ttl-ms 25 --read-ratio 1 --output target/performance/ttl-churn.json
# Large permanent values exceed the logical cache capacity and exercise eviction.
python3 scripts/load.py --url http://localhost:18080 --requests 100 --workers 2 --keys 400 --value-bytes 65536 --warmup 0 --read-ratio 1 --output target/performance/large-eviction.json
```

`--requests` selects closed-loop operation count. Supplying `--rate` selects open-loop scheduled arrivals over
`--duration`; at most `--workers` requests are in flight. Busy arrivals and scheduler lateness are dropped and reported
separately, never accumulated into an unbounded queue.
`scheduled_arrivals = dispatched + dropped_busy + dropped_scheduler`. Reported successful ops/sec uses the measured run
plus drain time. Exit 0 means no request errors/drops, 1 means request errors, and 2 means dropped arrivals without
request errors. Inspect JSON even on nonzero exit: the mixed and saturation campaigns deliberately reveal
failures/limits. These short runs are not assertions of a production throughput SLO.

Stop the retained test project using the cleanup command in section 4.
See [measured results and limitations](docs/performance.md) and
committed [raw JSON](docs/performance-results/2026-11-16/) for the observed numbers. Do not use a retained failed-chaos
cluster for a baseline workload without checking its health first.

## 6. Verified Kubernetes deployment

Verified with Docker Engine 29.8.2, kind 0.33.0, kubectl 1.37.2, and Kubernetes 1.37.0 on macOS ARM64. The existing
OrbStack Kubernetes API was offline; the test used a new disposable kind cluster and a separate kubeconfig. Your current
context is not changed. Requires kubectl, Docker, Python 3, internet for official tool/node/etcd images, and sufficient
VM resources (the tested Docker VM had 11 CPUs and about 9 GiB RAM).

```sh
python3 scripts/install-kind.py
.tools/kind create cluster --name cache-verify --kubeconfig "$PWD/.tools/kubeconfig-cache-verify" --image kindest/node:v1.37.0 --wait 180s
docker build -t distributed-cache:0.1.0 .
# macOS ARM64: export only the installed platform, avoiding incomplete multi-platform imports.
docker image save --platform linux/arm64 distributed-cache:0.1.0 -o /tmp/cache-k8s-image.tar
.tools/kind load image-archive /tmp/cache-k8s-image.tar --name cache-verify
python3 scripts/kubernetes-test.py --kubeconfig .tools/kubeconfig-cache-verify --mode legacy
python3 scripts/kubernetes-test.py --kubeconfig .tools/kubeconfig-cache-verify --mode consensus
```

`docker image save --platform` requires Docker 28+; on AMD64 select `linux/amd64`. The pinned installer supports
macOS/Linux ARM64/AMD64 and verifies official release digests before installing `.tools/kind`.
`--binary /path/to/downloaded/kind` verifies an offline binary with the same check. It does not install kubectl. The
tested cluster had a default `standard` local-path StorageClass; consensus requires a default class and three
ReadWriteOnce PVCs. The cluster pulls the correct architecture of `quay.io/coreos/etcd:v3.6.5` itself. An earlier
attempt to import the locally cached multi-platform etcd archive failed because unavailable platform digests were
referenced; preloading etcd is unnecessary.

Each harness command creates only its reserved disposable namespace (`cache-verify-legacy` or `cache-verify-consensus`),
generates test credentials without printing them, performs server-side manifest validation, waits for ready workloads,
port-forwards a Service on a temporary localhost port, and runs real requests. It records
`target/kubernetes-<mode>/result.json`, resources/events and bounded pod logs before deleting its namespace/PVCs by
default. Only use a test cluster. Both commands exited 0 in the verified run.

Legacy verifies Service routing, auth, CAS/batch, TTL, DELETE and metrics. Consensus additionally verifies three bound
etcd PVCs, actual primary replacement/new incarnation/repair, scale 4→5→4, rolling gateway restart, and persistent etcd
identity after pod replacement. These checks do not promise zero transient errors. The legacy manifest now has its
missing gateway Service and probes. The consensus manifest is `deploy/kubernetes-consensus.yaml`;
see [deployment semantics and remaining risks](docs/kubernetes.md).

Existing test namespaces are refused unless you explicitly pass `--reuse`; it retains their existing Secret. `--keep`
retains the namespace and PVCs on success or failure for investigation. Namespace deletion is destructive to test data.
Do not use these reserved names for real workloads. When finished:

```sh
.tools/kind delete cluster --name cache-verify
```

That removes the test cluster and its local volumes. `.tools/` is git-ignored and excluded from Docker build context
because it contains the test kubeconfig. If the API is unreachable, inspect
`kubectl --kubeconfig .tools/kubeconfig-cache-verify cluster-info`. For Pending pods inspect namespace events/PVCs and
the default StorageClass; for ImagePullBackOff verify that the application image was loaded and etcd can be pulled. Do
not switch to production credentials to resolve a local test problem.

## 7. Verified isolated JMH benchmarks

JMH 1.37 is optional and does not change normal application dependencies. Use Java 21:

```sh
mvn -B -Pjmh verify
java -jar target/jmh/distributed-cache-0.1.0-benchmarks.jar -l
# Short execution verification: all six methods, LRU/LFU, 128-byte values.
java -jar target/jmh/distributed-cache-0.1.0-benchmarks.jar 'dev.cache.StoreBenchmark.*' -p policy=LRU,LFU -p valueBytes=128 -f 1 -wi 1 -i 2 -w 200ms -r 300ms -t 1 -prof gc -foe true -rf json -rff target/jmh/smoke.json
# Longer measured hit/copy trials; run sequentially.
java -jar target/jmh/distributed-cache-0.1.0-benchmarks.jar 'dev.cache.StoreBenchmark.hitAndCopy' -p policy=LRU,LFU -p valueBytes=128 -f 2 -wi 3 -i 5 -w 1s -r 1s -t 1 -prof gc -foe true -rf json -rff target/jmh/hit-copy-t1.json
java -jar target/jmh/distributed-cache-0.1.0-benchmarks.jar 'dev.cache.StoreBenchmark.hitAndCopy' -p policy=LRU,LFU -p valueBytes=128 -f 2 -wi 3 -i 5 -w 1s -r 1s -t 4 -prof gc -foe true -rf json -rff target/jmh/hit-copy-t4.json
```

All listed benchmark cases completed locally; inspect JSON and console output for benchmark failures. The smoke run
verified 11 parameterized cases. Each longer run produced two policy results with two forks and ten measured iteration
samples per result. JMH uses localhost sockets to coordinate forked JVMs; a sandbox denying bind permission must allow
these sockets. Do not disable forks merely to bypass that restriction.

The profile writes exclusively under `target/jmh`, leaving the normal executable application jar at
`target/distributed-cache-0.1.0.jar`. It overrides inherited Spring Boot shade transformers and disables Boot
repackaging for the benchmark artifact. Normal `mvn verify` and Docker builds retain the application build. The normal
and JMH builds each passed all 13 JUnit tests.

Benchmarks cover local hits, payload copying, misses, versioned overwrites, eviction and a 256-entry expiration sweep.
Shared hit/overwrite state exposes contention; eviction/expiration fixtures are per thread. Invocation-level expiration
setup influences GC profiler allocations and must not be interpreted as allocation caused only by the sweep. Overwrite
includes version-generator overhead and may reject out-of-order versions under contention. FIFO and 4 KiB values are
available parameters but were not measured in this update.
See [raw JMH results and boundaries](docs/benchmark-results/2026-11-16/README.md). These in-process measurements exclude
all distributed work and do not establish client throughput, latency percentiles or availability SLOs.

## Verification recorded on 2026-11-16

Verified on macOS ARM64 with Java 21.0.13.0.3, Maven 3.10.0, Python 3.15, OpenSSL 4.1.0 and official etcd/etcdctl 3.6.5:

- Clean Maven verification: 13 tests, zero failures/errors/skips.
- Checksum-verified local etcd installation via `--archive`: passed; corrupted-archive rejection also passed. The
  archive was downloaded from the official release, and its digest matched both official release metadata and
  SHA256SUMS.
- Plaintext consensus failure campaign: passed all scenarios, including added batch and TTL checks; the final fixture
  also passed a repeat immediately after the secure run.
- Authenticated mTLS consensus failure campaign: passed all scenarios and security negatives.

The first plaintext attempt exposed a fixture race: an old gateway incarnation could still own the repair-worker lease
after restart. The fixture now waits for a live worker identity before testing handoff. A secure attempt immediately
after plaintext hit transient closed-port state; preflight now permits reuse of closed connections while rejecting live
listeners. No cache runtime change was required for these failures.

The legacy five-JVM regression passed in the preceding update. Current and historical results, including final reruns,
are in [verification notes](docs/verification.md). Logs from the current consensus campaigns are retained locally in
`target/consensus-plain/` and `target/consensus-secure/`; `mvn clean` deletes them.

GitHub Actions now includes independent plaintext and secure consensus jobs with native etcd installation. Local Docker
Compose smoke and controlled chaos tests were subsequently executed; see the follow-up evidence below. CI/Linux
execution, production Kubernetes deployment, exhaustive chaos testing, distributed load targets and production readiness
remain
unverified. Local kind deployment verification was added in the Kubernetes follow-up below. Local etcd mTLS testing does
not prove secured cache-to-cache transport or a production certificate-rotation
procedure.

## Docker and performance follow-up

Local legacy and consensus Compose verification and controlled chaos tests were executed against images built with the
supplied Dockerfile (existing matching build layers were reused). Three HTTP-fixture tests for the new load generator
passed. Five measured client workloads are committed in `docs/performance-results/2026-11-16/`; the 10k scheduled-demand
run saturated and the mixed run returned 409 conflicts. Neither is reported as a successful SLO test. Both final Compose
chaos commands exited 0 and cleaned up their test projects; the original four development containers remain running.
Maven verification also passed all 13 tests again. See [verification notes](docs/verification.md) for execution evidence
and discovered test assumptions. The CI workflow now includes a Docker chaos job, which has not been executed in GitHub
Actions here.

## Kubernetes and JMH follow-up

Both local Kubernetes acceptance suites passed and deleted their test namespaces/PVCs. The disposable kind cluster was
also removed; the original `orbstack` context and four development containers were preserved. The consensus suite
verified primary repair, online storage scaling, gateway rolling restart and persistent etcd replacement. JMH smoke and
one-/four-thread two-fork trials completed; [raw results](docs/benchmark-results/2026-11-16/README.md) are committed.
Detailed evidence and remaining production limits are in [verification notes](docs/verification.md). Added
Kubernetes/JMH CI jobs are configuration only; remote CI execution remains unverified.
