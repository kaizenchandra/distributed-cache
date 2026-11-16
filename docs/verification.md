# Executed verification

Environment: macOS aarch64, Java 21.0.13, Maven 3.10.0. Maven explicitly used JAVA_HOME for Java 21 (default Maven JVM
was Java 27).

- `mvn -o -Dmaven.repo.local=/tmp/cache-m2 verify`: PASS, five JUnit tests, zero failures/errors/skips. Local repository
  copied to temporary writable storage because sandbox denied home-cache locks.
- `python3 scripts/integration.py`: final run PASS. Five actual JVMs: one coordinator and four storage nodes, initially
  three active owners. Checked SET/GET, direct contents/version on all initial replicas, HTTP stale-epoch rejection,
  authenticated Prometheus JVM metrics, 20-way CAS with one winner, TTL, DELETE, four-node topology transfer preserving
  value, missing-auth rejection, killed storage process and fail-closed subsequent mutations. Test terminated remaining
  processes.
- Earlier integration runs exposed socket sandbox denial and a transfer verification failure. Final source accounts for
  expiration occurring between transfer and verification; final full cluster run passed after changes. These tests do
  not prove all transfer races safe under sustained load.
- Docker Compose and Kubernetes manifests: supplied, not executed. Docker API access was denied in sandbox; no
  deployment success claimed.
- Chaos campaigns, Testcontainers, JMH and throughput measurements: not executed / not implemented. No throughput or
  latency numbers are claimed.

This evidence does not meet the full requested production definition of done. See README acceptance status and remaining
security/recovery risks.

## Consensus-mode follow-up

Implemented etcd v3 metadata transactions, leased registrations, incarnation-aware immutable staging, topology/manifest
publication fencing, multi-gateway CAS, automatic topology reconciliation and bounded incremental replica
reconstruction. See `docs/consensus-v2.md` for exact semantics and residual risks.

Executed on Java 21 with official etcd 3.6.5 darwin-arm64:

- Maven `verify`: eight JUnit tests passed (five existing plus three consensus configuration/fencing/bounds tests).
- Legacy five-JVM integration regression: passed after adding conditional consensus controllers.
- Consensus failure suite: three actual etcd members, four storage JVMs and two gateways; passed cross-gateway CAS,
  primary crash, repair to spare, empty restart/changed incarnation, stale epoch and incarnation rejection, obsolete
  publication rejection, a timed-out transaction released only after topology change, gateway-to-etcd partition, gateway
  crash/restart, delete visibility actual Raft leader crash/re-election, and loss of consensus quorum. The transport
  gate test demonstrated late staged publication remaining invisible.
- New Compose configuration and CI steps supplied. Compose was not launched, and no Kubernetes deployment of the new
  consensus path was executed. No performance measurements were taken.

An intermediate test build failed because Mockito self-attachment was blocked by the sandbox; the unit test now
exercises the authority-validation helper directly without instrumentation. Earlier runs were excluded from three-member
evidence after discovering that IntelliJ already owned test port 22379. The final suite uses preflight-checked ports
33379/33381/33383, asserts every child process remains alive after startup, checks etcd server versions on all three
endpoints, and uses etcdctl to identify the actual leader before killing it. That full run passed, including leader
replacement and quorum-loss rejection. An intermediate repair timeout was observed; no single cause was established. Do
not replace jars in place while their JVMs are running.

## Collision-free metadata, repair and etcd security follow-up

Final artifact verification:

- Java 21 Maven `verify`: PASS, nine JUnit tests (five core, four consensus); zero failures/errors/skips. New assertions
  cover unique addresses for 10,000 keys, malformed-Unicode rejection, topology configuration agreement and rejection of
  plaintext endpoints in secure mode.
- Legacy five-JVM integration regression: PASS against the same final packaged jar.
- `CACHE_SECURE_TEST=1 ETCD_BIN=/tmp/etcd-v3.6.5-darwin-arm64/etcd python3 scripts/consensus_failure.py`: PASS with
  three live, version-checked native etcd members, four storage JVMs, two gateways and a separately stopped
  negative-credentials gateway. Client and peer traffic to etcd used mTLS; authentication was enabled with a
  namespace-only cache role and five-second tokens.
- Security negatives passed: missing client certificate, untrusted server CA, missing/wrong username/password
  authentication, out-of-namespace writes, and the actual Java gateway using incorrect etcd credentials. It returned 503
  without publishing.
- Functional/failure checks passed: cross-gateway CAS, delayed timed-out publication rejected after topology change,
  primary crash and repair to spare, empty restart reconstruction, stale incarnation/epoch rejection, gateway
  partition/restart, delete visibility, repair-worker crash with leased handoff, 40 distinct retained keys beyond the
  former slot count, concurrent admission bounded at exactly 64 manifests with 507 for new keys, existing-key access at
  capacity, actual Raft leader replacement, and read/write rejection after quorum loss.

Initial secure fixture attempts failed due to malformed test certificate chains (missing authority-key identifiers),
then because etcd's JSON gateway rejects a client certificate Common Name under authentication. The fixture now issues
complete strict-validation chains with a CN-less transport client identity, and the Java client validates that
requirement at startup. Certificate validation was not disabled; the successful final suite permitted TLS 1.2/1.3.

No secured Docker/Kubernetes deployment, throughput benchmark, certificate-rotation test or exhaustive storage-partition
campaign was executed. The schema needs a fresh namespace; retained metadata/tombstones still have no automatic garbage
collection. See docs/metadata-repair-security.md for operational constraints and exact configuration.

## 2026-11-16 batch API and validation follow-up

Executed against the updated packaged artifact on macOS with Java 21:

- `JAVA_HOME=$(/usr/libexec/java_home -v 21) mvn -o -Dmaven.repo.local=/tmp/cache-m2 -B clean verify`: PASS, 13 tests,
  zero failures/errors/skips. Dependencies were copied from the existing Maven cache because the sandbox prevents
  home-cache writes.
- `python3 scripts/integration.py`: PASS with five actual JVMs. In addition to the existing regression, checked ordered
  SET/CAS-conflict/GET batch outcomes and rejection of malformed SET/unknown operations with HTTP 400. The sandbox
  initially blocked socket binding; the successful run used approved loopback access.
- Python compilation checks for integration, consensus failure and load scripts: PASS.

Added a bounded sequential batch endpoint shared by legacy and consensus modes, typed client support, common request
validation, occupied-port/child-liveness checks in the legacy fixture, a build/regression CI workflow, and `help.md`.

The new batch envelope unit tests exercise partial success, continued execution and validation before side effects.
Consensus-mode batch deployment was not exercised: etcd/etcdctl are absent from this environment. The existing consensus
JUnit suite passed as part of Maven verification; historical full consensus/security results above are not fresh results
for this artifact. Docker daemon access was denied; Compose, Kubernetes and the new CI workflow were not executed. No
performance measurement or full production-readiness claim is made.

## 2026-11-16 native etcd installation and fresh consensus campaigns

Environment: macOS ARM64, Java 21.0.13.0.3, Maven 3.10.0, Python 3.15.2, OpenSSL 4.1.0, official etcd and etcdctl 3.6.5
(etcd Git SHA a061450).

Installed the official macOS ARM64 release locally under `.tools/etcd-v3.6.5-darwin-arm64`. Archive SHA-256
`14d7743f9ed07950a8e85491646e067e394a09e049e42083e2f6473fefa717a8` matched official GitHub release metadata and the
release SHA256SUMS asset. Added `scripts/install-etcd.py` with pinned official digests for macOS/Linux ARM64/AMD64,
optional offline archive input, and no system installation. Its local archive install and corrupted-archive rejection
were executed successfully. The Linux installation path and GitHub Actions jobs were not executed here.

Executed against the clean packaged artifact:

- `JAVA_HOME=$(/usr/libexec/java_home -v 21) mvn -o -Dmaven.repo.local=/tmp/cache-m2 -B clean verify`: PASS, 13 tests;
  zero failures/errors/skips.
- `ETCD_BIN=/tmp/cache-etcd-tools/etcd-v3.6.5-darwin-arm64/etcd python3 scripts/consensus_failure.py`: PASS after fixing
  the fixture lease race described below.
- `CACHE_SECURE_TEST=1 ETCD_BIN="$PWD/.tools/etcd-v3.6.5-darwin-arm64/etcd" python3 scripts/consensus_failure.py`: PASS
  after closed-port preflight handling was corrected.
- `ETCD_BIN="$PWD/.tools/etcd-v3.6.5-darwin-arm64/etcd" python3 scripts/consensus_failure.py`: PASS immediately
  following the secure run, validating the final fixture on a back-to-back plaintext run.
- Python compilation checks for the installer and consensus fixture: PASS.

Both final campaigns used three live etcd members, four storage JVMs, and two gateways. Secure mode additionally
started/stopped an intentionally misconfigured gateway. Coverage included added consensus batch SET/CAS-conflict/GET
partial success, cross-gateway TTL and deletion, multi-gateway CAS contention, delayed publication rejection after
topology change, primary crash and repair, empty restart/incarnation fencing, stale topology/publication rejection,
gateway partition/restart, repair-worker crash and leased handoff, metadata capacity enforcement, actual etcd leader
replacement, and rejection after quorum loss. Secure mode repeated the campaign with etcd client/peer mTLS and
authentication, plus missing-client-certificate, untrusted-CA, absent/wrong-credential, namespace-escape and
invalid-Java-gateway-credential negatives.

Initial plaintext failure: `StopIteration` selecting the repair worker. The worker key could still contain the killed
gateway's old incarnation until its lease expired. The test now waits until the leased identity belongs to a currently
live gateway before selecting a process to kill. Initial secure attempt: port preflight encountered transient
closed-connection state immediately after plaintext cleanup. The fixture now rejects active listeners and uses
SO_REUSEADDR for its bind probe. Final plaintext and secure suites exited 0 and stopped all child processes. No cache
runtime fix was required by these failures.

Final logs retained locally: `target/consensus-plain/results.log`, `target/consensus-secure/results.log`, and each
directory's etcd/JVM logs. `mvn clean` removes this evidence. CI now declares independent plaintext and authenticated
consensus jobs with pinned native tool installation; this is configuration, not evidence of a completed CI run.

Remaining scope includes secured cache HTTP transport/deployment validation, certificate rotation, Docker/Kubernetes
execution, full metrics/tracing, default TTL, weighted/failure-domain placement, exhaustive chaos testing, JMH and
distributed offered-rate performance campaigns. No throughput, availability SLO, or production-readiness claim is made.

## 2026-11-16 Docker Compose, controlled chaos and measured workloads

Docker access was approved for this update. Engine 29.8.2 / Compose 5.5.0 on OrbStack ARM64; Docker VM reports 11 CPUs
and 9,434,791,936 bytes of memory. Existing `distributed-cache` development containers on localhost:8080 were preserved
throughout. Dedicated projects `cache-verify-legacy` and `cache-verify-consensus` used test gateway ports 18080/18081.

Added `scripts/compose-test.py` and test port overrides. Both Compose configurations were built/started with the
supplied Dockerfile; matching cached image build layers were reused. The harness owns only the dedicated test projects,
saves logs and results, unpauses injected failures and removes its containers/networks/volumes in `finally` unless
explicitly asked to keep them.

Final executed commands:

- `python3 scripts/compose-test.py --mode legacy --chaos --skip-build`: PASS, exit 0. SET/GET, batch partial success/CAS
  conflict, TTL, DELETE, missing-auth rejection, authenticated Prometheus JVM metrics, and storage SIGKILL followed by
  fail-closed writes.
- `python3 scripts/compose-test.py --mode consensus --chaos --skip-build`: PASS, exit 0. Same API checks across two
  gateways; one paused etcd member with eventual recovery/new writes; actual primary selected from committed manifest
  and SIGKILLed; ownership change, repair to three live owners, empty restart with changed incarnation and repaired
  manifest; gateway pause while second gateway serves writes; two paused etcd members reject GET/SET with 503; restored
  quorum permits reads and fresh writes.
- `python3 scripts/test_load.py`: PASS, three tests against a real local HTTP fixture. Verified successful hit counts,
  overload/dropped-arrival accounting, independently observed HTTP concurrency bounded by two workers, and HTTP 503
  responses counted as errors with exit 1.
- `JAVA_HOME=$(/usr/libexec/java_home -v 21) mvn -o -Dmaven.repo.local=/tmp/cache-m2 -B verify`: PASS, 13 JUnit tests
  with no failures/errors/skips. No clean was used so Docker/performance evidence was preserved.
- Python compilation checks for Compose/load/test scripts: PASS.

Five client performance workloads were executed on a retained consensus test cluster, with final raw results committed
under `docs/performance-results/2026-11-16/` and a measured summary in its README. The generator now supports
closed-loop counts, open-loop scheduled arrivals, multiple URLs, deterministic uniform/Zipf mixes, bounded in-flight
work and latency histograms, binary-safe values, TTLs, seeding/warmup, actual read hit/miss counts, per-status errors,
overload/drop accounting, and JSON results even on request errors or saturation. Seeding/warmup are excluded from
measured latency/throughput. Histogram percentiles are bucket upper bounds with 5% spacing.

Observed final measurements:

- Mixed 200 requests / four workers: 197 successful, three HTTP 409 conflicts, 629.56 successful client ops/sec. This is
  not an error-free workload.
- Zipfian 50 scheduled arrivals/sec for five seconds: 250 successful, zero errors/drops, 49.96 successful client
  ops/sec.
- 10k scheduled arrivals/sec for two seconds: 20,000 scheduled, 2,363 dispatched/successful, 17,637 dropped before
  dispatch, 1,179.46 successful client ops/sec. Exit 2 deliberately reports saturation; this does not prove 10k
  arrivals/sec reached the server or establish the cluster's maximum capacity.
- 25 ms TTL run: 100 successful HTTP reads, all misses, 911.15 ops/sec.
- 400 permanent 64 KiB values under logical memory pressure: 100 successful HTTP reads, hit ratio 0.88, 460.87 ops/sec.

These brief local trials include a Python generator bottleneck, shared-host contention, different cache/JIT/repair
states and no confidence intervals. Container CPU/memory and authenticated gateway JVM metrics snapshots were captured
under `target/performance/` after the initial campaign, not continuously during requests. No causal CPU/GC/network
bottleneck claim is made.

Issues found and corrected in tests: a repeated single-etcd pause could catch leader re-election and produce 503 on a
mutation. This is consistent with the no-replay rule for ambiguous writes. The fixture now allows bounded recovery,
probes availability with reads and fresh unique mutation keys, and records transient recovery failures. It does not
blindly retry the same ambiguous mutation. The final primary-crash scenario verifies the actual primary and repaired
incarnations rather than killing an arbitrary storage container. The load generator distinguishes dropped demand from
dispatched client requests and exits 1 for errors or 2 for saturation; concurrent 409 conflicts are preserved as errors
rather than hidden by retries.

Final evidence: `target/compose-legacy/result.json`, `target/compose-consensus/result.json`, each directory's container
logs/status, and the committed workload JSON. Final `docker ps` showed only the original four development containers;
all test containers, networks and etcd volumes were removed. `mvn clean` removes local target evidence.

A Docker chaos job was added to GitHub Actions but not run remotely. These campaigns do not cover arbitrary network
partitions, packet loss, latency injection, CPU throttling, all rolling-upgrade/expiration/migration races, secured
Docker/Kubernetes deployment, certificate rotation, JMH, multi-host load generation or the 100k/1M/5M/10M received-rate
targets. Kubernetes deployment and production availability/latency SLOs remain unverified. No cache runtime change was
required by the observed test failures; the fixes are in test assumptions and measurement/reporting.

## 2026-11-16 Kubernetes acceptance and JMH follow-up

The configured OrbStack Kubernetes API was offline (localhost:26443 refused connections). Installed official kind
v0.33.0 locally with a pinned SHA-256-verified macOS ARM64 binary, then created a disposable single-node cluster
`cache-verify` running Kubernetes v1.37.0. Used kubectl v1.37.2 and a separate `.tools/kubeconfig-cache-verify`, leaving
the normal context unchanged. The default `standard` local-path StorageClass dynamically bound three 1 GiB ReadWriteOnce
etcd PVCs.

Added `scripts/install-kind.py` with pinned official macOS/Linux ARM64/AMD64 release digests. Executed its
offline-binary installation successfully and verified rejection of a corrupt binary. Added `scripts/kubernetes-test.py`,
which requires explicit test kubeconfig, creates only a reserved disposable namespace, generates/reuses credentials
without printing them, validates manifests server-side, port-forwards a Service, exercises real APIs and lifecycle
changes, collects non-secret resource/events/bounded log evidence, and deletes its namespace/PVCs by default.

Fixed the original legacy manifest's missing coordinator Service and missing coordinator startup/readiness/liveness
probes; specified local image pull behavior and added a storage startup probe. Added a consensus manifest with three
parallel-start etcd members and PVCs, headless discovery, four storage pods with ordinal DNS identity, two gateways with
rolling strategy, resource limits, probes, preferred anti-affinity and PDBs. `.tools/` is excluded from Docker build
context because it holds cluster credentials.

Executed deployment verification:

- `docker build -t distributed-cache:0.1.0 .`: PASS, normal Java 21 image build executed all 13 JUnit tests with zero
  failures/errors/skips. Image config digest in the imported kind runtime was
  `sha256:52fa00e3cd310510a6cd5db9ad7c83bb15e7284488383a63932f1c4f9213e959`, matching the new build's config.
  Platform-specific Docker save plus `kind load image-archive` successfully imported the application. Pods pulled etcd's
  correct architecture themselves.
- `python3 scripts/kubernetes-test.py --kubeconfig .tools/kubeconfig-cache-verify --mode legacy`: PASS, exit 0. Server
  schema validation, pod readiness, Service routing, authenticated SET/GET, missing-auth rejection, batch CAS
  conflict/read, TTL, DELETE and authenticated JVM metrics. Namespace removed afterward.
- `python3 scripts/kubernetes-test.py --kubeconfig .tools/kubeconfig-cache-verify --mode consensus --reuse`: PASS, exit
  0 against the initially manually provisioned test namespace. All nine initial pods Ready, three etcd PVCs Bound; API
  checks plus actual primary pod replacement/new incarnation/repair, storage 4→5→4 scaling, rolling gateway restart and
  etcd-0 replacement retaining its persistent Raft member ID and committed cache metadata.
- `python3 scripts/kubernetes-test.py --kubeconfig .tools/kubeconfig-cache-verify --mode consensus`: PASS again, exit 0
  from a fresh namespace with newly generated credentials, validating the exact documented automatic setup. Same
  lifecycle/repair checks passed; namespace and PVCs removed afterward.
- Python compilation checks for Kubernetes harness and kind installer: PASS.

Image-import issue: importing the cached multi-platform etcd image directly through kind failed because its archive
referenced platform digests unavailable locally. The verified flow exports only the installed architecture of the
application image (`docker image save --platform linux/arm64`), loads that archive and lets kubelet pull etcd. No TLS
validation or image content checks were disabled. A local harness syntax error in its port-forward variable declaration
was corrected before either acceptance run.

Added optional Maven `jmh` profile using OpenJDK JMH 1.37. It adds benchmark sources/annotation processing only when
selected, writes all build products under `target/jmh`, skips Boot repackaging only for that profile, and produces a
runnable classifier jar. Fixed a Spring Boot parent shade-transformer merge conflict by overriding the inherited
transformer list. The normal app jar remains separate and runnable. Six benchmarks cover hits, copying, misses,
overwrites, eviction and a 256-entry expiration sweep.

Executed benchmark verification on Java 21.0.13.0.3 / macOS ARM64:

- `JAVA_HOME=$(/usr/libexec/java_home -v 21) mvn -o -Dmaven.repo.local=/tmp/cache-m2 -B -Pjmh verify`: PASS, 13 JUnit
  tests, zero failures/errors/skips. Missing dependencies were initially downloaded using the same command without
  offline mode.
- `java -jar target/jmh/distributed-cache-0.1.0-benchmarks.jar -l`: PASS, six generated benchmarks discovered.
- All-method smoke command documented in help.md, with LRU/LFU, 128-byte values, one fork, one 200 ms warmup, two 300 ms
  measurement iterations and GC profiling: PASS, 11 parameterized cases; repeated with fail-on-error enabled.
- Hit-and-copy commands in help.md, LRU/LFU, 128-byte values, two forks, three 1-second warmups and five 1-second
  measurements per fork, GC profiling, first with one thread and then four threads: PASS. Four result records, each
  retaining ten measured iteration samples and JMH confidence intervals.
- Final default-profile Maven `verify`: PASS, 13 JUnit tests with no failures/errors/skips; normal executable Boot jar
  repackaged successfully. This confirms the JMH profile does not replace the normal application artifact.

JMH initially could not bind its fork-control socket inside the sandbox; the actual successful runs used approved
loopback access and real forked JVMs. No in-process/no-fork fallback was used. Raw smoke and longer results are
committed in `docs/benchmark-results/2026-11-16/`, with setup/interpretation in its README. These local microbenchmarks
exclude network/serialization/replication/consensus work; no distributed throughput, latency percentile or availability
claim follows from them. Expiration fixture setup affects profiler allocation numbers; shared overwrite includes
version-generator overhead and can reject out-of-order versions under contention.

Deployment evidence remains under `target/kubernetes-legacy/` and `target/kubernetes-consensus/`. Added Kubernetes and
JMH CI jobs were not run remotely. Single-node kind cannot validate host/zone anti-affinity or node failure. Pod
deletion bypasses PDBs; there was no node-drain campaign. Application readiness probes currently establish process
health, not fenced data availability. Production etcd/cache transport security, snapshot/restore, certificate rotation,
network policies, full storage rolling upgrades, multi-node failures, and distributed received-rate/SLO campaigns remain
required. See docs/kubernetes.md. The local kind cluster is disposable and removed after verification; persistent
production deployment is not claimed.

Final cleanup confirmed: `kind delete cluster --name cache-verify` removed the single test node.
`kubectl config current-context` remained `orbstack`, and `docker ps` showed only the original four development cache
containers. No user Kubernetes cluster configuration or development containers were replaced.

## Consensus with Keycloak and Next.js — 2026-11-16

The local development stack was switched from legacy to consensus mode without deleting volumes. Legacy
coordinator/storage containers were stopped. Keycloak and its existing realm were preserved. The frontend now targets
gateway-0; all three etcd members, four consensus storage nodes and both gateways are running. Each etcd endpoint passed
`etcdctl endpoint health` by committing a proposal.

`python3 scripts/auth-test.py --mode consensus` passed **61 end-to-end HTTP
checks**. [Complete check output](auth-consensus-results.txt) contains no passwords or tokens. Tests follow the actual
NextAuth/Keycloak authorization-code flow and exercise the Next.js proxy with session cookies. They verify correct and
incorrect passwords, user/admin roles, anonymous rejection, frontend and backend authorization, static-token bypass
rejection, internal-RPC separation, tampered signatures, expired access tokens, cross-origin rejection, session token
confidentiality and logout.

Cache checks cover all seven operations, missing-key sentinels, permanent TTL, natural expiration, EXPIRE changes,
immediate deletion at TTL zero, conditional creation at version zero, successful and conflicting CAS, Unicode and
multiline text, empty values, the 64 KiB boundary, invalid inputs, sequential batches with individual conflicts,
continuation after failure, malformed-batch prevalidation and deletion. Admin checks cover consensus membership
reconciliation, repair status, and rejection of the legacy-only topology mutation. Membership reported four storage
nodes, three replicas, and minimum copies of two. A value written through the frontend was read back through gateway-1
with identical value/version/TTL metadata.

Generated test keys were deleted. Login secrets were loaded from local `.env` without printing them; browser session
JSON was checked for access/refresh-token leakage. The test helper reads its own encrypted session server-side using the
local NextAuth secret solely to test independent backend authorization. It does not expose tokens to the browser.

Browser automation was unavailable (browser access host unavailable and native Computer Use permissions not granted).
The user explicitly selected HTTP-only testing. Therefore rendered controls, screenshots, accessibility and visual
layout were **not** tested. This campaign verifies HTTP flows and application behavior; it does not claim
crash/failover/repair-under-failure, quorum-loss, throughput, production TLS or availability validation.

The consensus stack remains running at http://localhost:3000 with Keycloak at http://localhost:8180. Manage it using
`docker compose -f compose.consensus.yaml ...`; `docker compose ps` without that file describes the legacy service
definitions.
