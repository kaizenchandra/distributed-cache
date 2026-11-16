# Distributed cache — Java 21 reference implementation

A custom bounded in-memory cache running in separate JVMs.

See [help.md](help.md) for build, regression, consensus/security, Docker and manual test instructions.

**Current consensus implementation:**
see [collision-free metadata, improved repair and authenticated mTLS](docs/metadata-repair-security.md).

**Consensus mode is available:** [consensus topology, fencing, failover and repair](docs/consensus-v2.md). Run
`python3 scripts/init-auth.py` then
`docker compose -f compose.consensus.yaml up --build -d`. Browser/API authentication uses Keycloak by default; see [authentication](docs/authentication.md). It uses three etcd
members, four storage nodes and two active gateways. The original commands and acceptance list below describe legacy
mode; remaining-limitations statements about missing consensus/failover apply to that mode. Consensus mode still has the
production security and performance limits documented in its guide.

This is an executable engineering baseline, **not production-ready and not the complete master-prompt scope**. No
Redis/cache product is used.

## Run

Java 21 and Maven 3.6.3+ required. Spring Boot 3.5.16 supports Java
21: https://docs.spring.io/spring-boot/3.5/system-requirements.html

```sh
mvn clean verify
python3 scripts/integration.py
python3 scripts/init-auth.py
set -a
. ./.env
set +a
CACHE_AUTH_MODE=token docker compose up --build -d
curl -H "Authorization: Bearer $CACHE_ADMIN_TOKEN" -X POST localhost:8080/admin/bootstrap
curl -H "Authorization: Bearer $CACHE_CLIENT_TOKEN" -H 'Content-Type: application/json' localhost:8080/api/v1/operation -d '{"operation":"SET","key":"aw","value":"dmFsdWU=","ttlMillis":-1}'
curl -H "Authorization: Bearer $CACHE_CLIENT_TOKEN" -H 'Content-Type: application/json' localhost:8080/api/v1/operation -d '{"operation":"GET","key":"aw","ttlMillis":-1}'
```

Run these commands from `distributed-cache`. The setup script creates a git-ignored
`.env` with three distinct random tokens and owner-only permissions; running it
again preserves existing credentials. Compose automatically reads this file for
both topologies, including when launched from an IDE. Sourcing it above also makes
the tokens available to the `curl` commands. Shell environment variables override
the file, so unset any stale `CACHE_CLIENT_TOKEN`, `CACHE_INTERNAL_TOKEN`, or
`CACHE_ADMIN_TOKEN` exports if needed. The `.env` file is excluded from Docker builds.

Typed client: `new CacheClient(url, token).execute("SET", keyBytes, valueBytes, -1, null)`.
Keys from the typed client use unpadded Base64url; direct API callers must use that same canonical encoding. JSON values
use standard Base64. Maximum encoded key 512 UTF-16 units, value 64 KiB, request 100,000 bytes including chunked
requests. No native Java serialization. Protocol path version is v1. No compression or automatic retries.

`GET`, `SET`, `DELETE`, `EXISTS`, `TTL`, `EXPIRE`, `CAS` are supported. Missing version = 0 for conditional creation.
CAS requires expectedVersion. TTL is milliseconds from coordinator write time: -1 never expires, 0 deletes immediately,
positive at most one year; missing TTL defaults to 0 in JSON, so specify it explicitly. GET returns found=false,
version=0, ttlMillis=-2 when absent; permanent TTL=-1. CAS conflicts return 409, invalid requests 400, auth 401, size
rejection 413, unavailable or ambiguous peer operations 503. A timeout does not imply a write failed.

## Boundaries

One Maven application with focused classes: Store (storage), Ring (routing), Node (storage RPC), Coordinator (single
authority), Wire/CacheClient (transport), Security (credential roles). Deployment role is configured using
`cache.coordinator`. Only the coordinator credential may access internal APIs; possession of it permits arbitrary
internal operations. Never expose internal APIs publicly.

Configuration: `cache.bytes` logical per-node capacity (default 16 MiB), `cache.policy` LRU/LFU/FIFO, `cache.replicas`
default 3, `cache.vnodes` default 128, `cache.nodes` comma-separated stable URLs. Topology changes via admin API; other
runtime configuration changes require a controlled restart/reset.

See [architecture](docs/architecture.md), [consistency](docs/consistency.md), [runbook](docs/runbook.md), [performance](docs/performance.md), [failure analysis](docs/failures.md),
and [review](docs/review.md).

## Acceptance status

Implemented: deterministic virtual-node ring, distinct replica placement, synchronous acknowledgment, primary reads,
TTL, LRU/LFU/FIFO, logical memory bounds, versions, atomic coordinator CAS, authenticated typed client, fail-closed
mutations after uncertain replication, fenced manual topology transfer, bounded transfer pages and transfer
verification, Docker/Kubernetes examples, metrics endpoint.

Not implemented: gRPC/Netty data plane, atomic batch transactions, automatic discovery/heartbeats/failure confirmation,
consensus-backed
authority, automatic promotion, live concurrent migration/delta capture, resumable migration, durable coordinator
journal, replica repair, default TTL, weighted/failure-domain placement, TLS/mTLS provisioning, per-tenant isolation,
admin rate limiting, full custom metrics/tracing/dashboard, Testcontainers suites, exhaustive chaos testing,
distributed multi-host offered-rate generation. These remain required before the original definition of done can be met.
Kubernetes
manifests are locally verified examples, not a validated production deployment. No throughput or availability target has been
demonstrated.

## Batch operations

Both modes expose `POST /api/v1/cache/batch` using the client credential. Supply
`{"operations":[...]}` with 1–100 ordinary operation requests. Responses contain ordered
`{status,result,error}` items. MGET/MSET are represented as repeated GET/SET requests.
Batches execute sequentially and are not atomic; inspect each result and never blindly
retry a partially successful mutation batch. The existing 100,000-byte request limit applies.
Malformed envelopes are rejected before execution. Java callers can use `CacheClient.batch`.

Native consensus verification: install test tools with `python3 scripts/install-etcd.py`,
export the printed `ETCD_BIN`, then run `python3 scripts/consensus_failure.py` and
`CACHE_SECURE_TEST=1 python3 scripts/consensus_failure.py` sequentially. Both campaigns
passed locally on macOS ARM64 with etcd 3.6.5; see [verified instructions](help.md)
and [execution evidence](docs/verification.md). This does not establish production readiness.

Docker verification and local performance campaigns are now available: run
`python3 scripts/compose-test.py --mode consensus --chaos` for an isolated cluster
and controlled failures. See [help.md](help.md) for both modes, cleanup, and the
load-generator commands, and [measured local results](docs/performance-results/2026-11-16/README.md)
for actual successes, conflicts, misses and saturation drops. Production deployment
and throughput targets remain unverified.

Kubernetes acceptance now runs in an explicit test kubeconfig with
`python3 scripts/kubernetes-test.py --kubeconfig .tools/kubeconfig-cache-verify --mode consensus`.
The local suite passed primary repair, scaling, gateway rolling restart and etcd PVC-backed
replacement. See [Kubernetes guide](docs/kubernetes.md). Optional isolated JMH benchmarks
build with `mvn -Pjmh verify`; [measured results](docs/benchmark-results/2026-11-16/README.md)
exclude network and consensus work. Full setup and verified commands are in [help.md](help.md).

## Next.js testing console

[Cache Lab](frontend/README.md) provides a local frontend for all seven operations,
UTF-8 keys/values, CAS versions, TTL, batches, health, topology, and session request history.
See its setup guide to configure server-side tokens and run `npm run dev` from `frontend`.

## Keycloak login and roles

Both Compose stacks include Keycloak and the frontend. Run `python3 scripts/init-auth.py` and
`docker compose up --build -d`, then open http://localhost:3000. See
[accounts, role permissions, bootstrap and configuration](docs/authentication.md).
