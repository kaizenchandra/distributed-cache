````
# MASTER PROMPT: Design and Develop a Production-Grade Distributed Cache Using Java 21 and Spring Boot

## 1. ROLE AND ENGINEERING RESPONSIBILITIES

Act as a **Principal Software Engineer, Distinguished Distributed Systems Engineer, Java Performance Engineer, Solution Architect, and Site Reliability Engineer** with 15+ years of experience building high-performance distributed infrastructure such as Redis Cluster, Memcached, Hazelcast, and Apache Ignite.

Your task is to **design, develop, test, benchmark, document, and deploy an end-to-end Distributed Cache System** using Java 21 and Spring Boot.

The system must implement its own core distributed caching mechanisms, rather than simply wrap an existing distributed cache product.

Specifically, implement:

- Distributed key-value storage
- Consistent hashing
- Virtual nodes
- Replication
- Data partitioning
- Node discovery and membership
- Cluster topology management
- Data rebalancing
- Eviction algorithms
- Time-to-live expiration
- Concurrency control
- Failure detection and recovery
- Read/write consistency
- Horizontal scaling
- Observability and operational tooling

Treat this as a real engineering project, not merely a conceptual system design exercise.

**Deliver working source code, tests, local cluster infrastructure, benchmark scripts, and deployment documentation.**

### Engineering principles

- Use Java 21 and a verified compatible Spring Boot version.
- Follow repository conventions if an existing project is provided.
- Apply SOLID, DDD, and Clean/Hexagonal Architecture pragmatically.
- Prefer focused interfaces and maintainable modules.
- Avoid unnecessary microservices or abstract frameworks.
- Use bounded memory, queues, retries, connections, and execution resources.
- Handle concurrency, network partitions, timeouts, and node failures explicitly.
- Distinguish cache availability, data durability, and consistency.
- Never fabricate test results or performance measurements.
- State important assumptions and trade-offs.
- Implement actual algorithms instead of replacing them with Redis, Hazelcast, or Ignite.

---

# PART A — OBJECTIVE AND SCOPE

## 2. PRIMARY OBJECTIVE

Build a distributed in-memory key-value cache capable of running across multiple Java processes and Kubernetes nodes.

Example cluster:

- Cache Node A
- Cache Node B
- Cache Node C
- Cache Node D

A client performs:

`SET customer:123 {...}`

The system must:

1. Determine the responsible partition using consistent hashing.
2. Route the request to the correct primary node.
3. Store the value in memory.
4. Replicate the entry to configured replicas.
5. Apply expiration and eviction policies.
6. Return a result based on the configured consistency level.

When a node joins, leaves, or fails, the system must update routing and redistribute responsibility safely.

Implement:

- SET
- GET
- DELETE
- EXISTS
- TTL
- EXPIRE
- MGET
- MSET where feasible
- CAS / Compare-and-Set
- Cluster health inspection
- Node membership inspection
- Cache statistics
- Administrative topology operations

Document unsupported features explicitly.

---

## 3. TARGET NON-FUNCTIONAL REQUIREMENTS

Treat these as design goals, not measured results.

| Metric | Target |
|---|---|
| Aggregate throughput | 1M operations/second initially, scaling toward 5M–10M |
| Cache hit latency | p99 below 5 ms within a region |
| Availability | 99.99% target |
| Cluster size | 3–100+ nodes |
| Replication factor | Configurable, default 3 |
| Key size | Configurable, bounded |
| Value size | Configurable, bounded |
| Memory | Explicit per-node limits |
| Scalability | Horizontal |
| Expiration | Millisecond-level TTL semantics |
| Eviction | LRU, LFU, TTL-aware policies |
| Deployment | Docker/Kubernetes |
| Observability | Metrics, tracing, structured logs |

Define whether performance targets refer to:

- Client-observed operations
- Internal storage operations
- Replication operations
- Local versus remote reads
- Cache hits versus misses
- Synchronous versus asynchronous replication

Do not equate internal node operations with successful client requests.

---

# PART B — REQUIREMENTS

## 4. FUNCTIONAL REQUIREMENTS

### 4.1 Cache operations

Implement:

- Put
- Get
- Delete
- Key existence checks
- TTL inspection
- Expiration updates
- Batch operations
- Conditional writes
- Version-based updates

Define precise API behavior.

### 4.2 Key and value support

Support:

- String or byte-array keys
- Byte-array values
- Configurable maximum key/value sizes
- Binary-safe transport
- Configurable serialization
- Entry metadata
- TTL
- Versioning

Avoid Java native object serialization as the default wire protocol.

### 4.3 Cluster operations

Support:

- Node join
- Node leave
- Node failure
- Node replacement
- Membership discovery
- Replica selection
- Partition ownership
- Topology inspection
- Online rebalancing

### 4.4 Configurable cache policies

Support:

- TTL
- Maximum memory
- Eviction policy
- Replication factor
- Read consistency
- Write consistency
- Failure handling
- Admission policy, if justified

Validate configuration at startup and during runtime changes.

---

# PART C — HIGH-LEVEL DESIGN

## 5. ARCHITECTURE OPTIONS

Compare:

### Option A — Client-Side Routing

Clients maintain the consistent-hash ring and communicate directly with responsible cache nodes.

### Option B — Proxy-Based Routing

A cache gateway routes requests to the correct nodes.

### Option C — Server-Side Forwarding

Any cache node accepts requests and forwards them to the responsible primary or coordinator.

Evaluate:

- Hop count
- Client complexity
- Cluster topology updates
- Network overhead
- Failure recovery
- Operational simplicity
- Connection scaling

Select an architecture and justify it.

Provide Mermaid diagrams for:

1. Cluster topology
2. Read request
3. Write request
4. Replication
5. Node join
6. Node failure
7. Rebalancing

---

## 6. CORE COMPONENTS

Consider these components:

1. CacheClient
2. CacheGateway
3. ConsistentHashRing
4. VirtualNode
5. PartitionManager
6. MembershipManager
7. FailureDetector
8. CacheNode
9. LocalStorageEngine
10. ReplicaManager
11. ReplicationCoordinator
12. EvictionManager
13. ExpirationManager
14. RebalanceCoordinator
15. ClusterMetadata
16. MetricsCollector

Separate the control plane from the data plane.

Define which component is authoritative for membership and topology updates.

Avoid assuming that each node can independently modify cluster membership without risking conflicting ownership maps.

---

# PART D — CONSISTENT HASHING

## 7. IMPLEMENT CONSISTENT HASHING FROM SCRATCH

Implement a consistent-hash ring in Java 21.

Requirements:

- Stable hash function
- Configurable virtual nodes
- Deterministic key-to-node mapping
- Node addition
- Node removal
- Replica selection
- Collision handling
- Uniform distribution testing

Explain:

- Why modulo hashing causes extensive redistribution
- How consistent hashing reduces remapping
- How virtual nodes improve distribution
- Expected key movement when adding a node
- The effect of uneven node capacities

Use a deterministic hash function suitable for distributed routing, such as MurmurHash3 or another justified algorithm.

Specify the exact byte encoding and hash algorithm version so all clients and nodes produce identical routing decisions.

Test deterministic routing across process restarts.

---

## 8. VIRTUAL NODES

Implement configurable virtual nodes.

For example:

- Node A: 128 virtual nodes
- Node B: 128 virtual nodes
- Node C: 128 virtual nodes

Explain:

- Virtual-node placement
- Ownership
- Distribution fairness
- Weighted capacity
- Ring memory overhead
- Topology propagation
- Virtual-node changes
- Key redistribution

Measure distribution skew across representative workloads.

Do not assume more virtual nodes are always better.

---

# PART E — PARTITIONING AND REPLICATION

## 9. PARTITION OWNERSHIP

Define:

- Primary owner
- Replica owners
- Replication factor
- Failure domains
- Ownership epoch
- Topology version

Implement deterministic replica selection while avoiding duplicate physical nodes.

When possible, place replicas across separate hosts or availability zones.

Document limitations of local single-host testing.

---

## 10. REPLICATION STRATEGIES

Compare:

1. Synchronous replication
2. Asynchronous replication
3. Quorum-based replication
4. Primary-replica replication
5. Leaderless replication

Evaluate:

- Write latency
- Availability
- Network partitions
- Data loss
- Stale reads
- Conflict resolution
- Recovery cost

Select one implementable consistency model for the initial system.

Avoid combining incompatible guarantees.

For example, a primary-replica architecture with asynchronous replication must not claim that acknowledged writes cannot be lost.

### Required implementation

Support configurable replication factor.

Define:

- Write acknowledgment semantics
- Replica lag
- Replica ordering
- Failure recovery
- Duplicate replication messages
- Out-of-order replication
- Retry behavior
- Replica resynchronization

Use version numbers, epochs, or comparable mechanisms to reject stale replication operations.

---

# PART F — DISTRIBUTED CONSISTENCY

## 11. CONSISTENCY MODEL

Explicitly define:

- Read-after-write guarantees
- Eventual consistency behavior
- Stale-read behavior
- Conditional update semantics
- Delete visibility
- Failover consistency
- Rebalance consistency

Explain the relationship between:

- Replication factor N
- Read quorum R
- Write quorum W

Discuss why `R + W > N` alone does not guarantee linearizability in all systems.

If strict consistency is required, evaluate a leader-based consensus protocol such as Raft.

Do not implement Raft from scratch unless the selected architecture genuinely requires it.

If a consensus-backed membership or metadata system is chosen, use a well-defined component and document its operational assumptions.

---

## 12. SPLIT-BRAIN PREVENTION

Handle:

- Network partitions
- Old primary continuing to accept writes
- New primary promotion
- Conflicting topology versions
- Stale clients
- Replica promotion races

Define fencing rules.

A topology epoch alone is insufficient unless storage operations enforce it.

Explain the role of a coordinator or consensus-backed control plane in issuing authoritative ownership changes.

Implement tests for stale-owner rejection.

---

# PART G — IN-MEMORY STORAGE ENGINE

## 13. LOCAL CACHE ENGINE

Build an efficient thread-safe in-memory storage engine.

Consider:

- ConcurrentHashMap
- Segmented locking
- Atomic counters
- Entry versioning
- Access metadata
- TTL expiration
- Memory accounting

Use Java 21 concurrency primitives appropriately.

Define cache entry structure.

Example fields:

- Key
- Value
- Creation timestamp
- Expiration timestamp
- Last access metadata
- Access frequency
- Version
- Memory weight

### Correctness requirements

- Thread-safe GET/SET/DELETE
- Atomic conditional updates
- No lost updates
- Bounded memory
- Safe eviction under concurrency
- Safe expiration handling
- Correct size accounting

Do not assume ConcurrentHashMap automatically makes multi-step entry operations atomic.

---

# PART H — EVICTION ALGORITHMS

## 14. IMPLEMENT CACHE EVICTION

Implement and compare:

1. LRU — Least Recently Used
2. LFU — Least Frequently Used
3. FIFO — First In, First Out
4. TTL-aware expiration

Evaluate:

- Time complexity
- Memory overhead
- Lock contention
- Hit ratio
- Scan resistance
- Implementation complexity

Implement at least LRU and LFU as selectable policies.

Use bounded metadata structures and concurrency-safe operations.

Explain the limitations of exact global LRU in a highly concurrent cache.

Consider approximate or segmented LRU where appropriate.

Do not introduce a complex TinyLFU implementation unless admission-policy benefits justify it.

---

## 15. MEMORY MANAGEMENT

Implement explicit per-node memory accounting.

Account for:

- Keys
- Values
- Entry metadata
- Hash table overhead
- Eviction metadata
- Replication buffers
- Network buffers
- Temporary transfer buffers

Distinguish logical cache weight from actual JVM heap usage.

Avoid claiming byte-accurate JVM heap accounting without measurement.

Define:

- Maximum cache weight
- High watermark
- Low watermark
- Eviction batch size
- Maximum object size
- Admission rejection
- Memory pressure response

Explain JVM GC implications and compare G1 GC with ZGC for this workload.

Tune only based on available measurements.

---

# PART I — TTL AND EXPIRATION

## 16. EXPIRATION ENGINE

Implement:

- Per-entry TTL
- Default TTL
- No-expiration mode
- Lazy expiration on access
- Background expiration
- Expiration metrics

Use an efficient expiration strategy such as:

- Timing wheel
- Priority queue
- Sampled expiration
- Bucketed expiration

Select the simplest implementation that meets the performance targets.

Address:

- Clock skew
- Restart behavior
- Replication of expiration
- Negative TTL
- Zero TTL
- Expiration races
- Expiration versus concurrent update
- Expiration versus rebalance

Define whether TTL is based on insertion time, last write, or last access.

Ensure expiration does not accidentally delete a newer version of a key.

---

# PART J — NODE MEMBERSHIP AND FAILURE DETECTION

## 17. CLUSTER MEMBERSHIP

Evaluate:

- Static configuration
- Kubernetes Endpoint discovery
- Gossip protocols
- Centralized coordination
- Consensus-backed metadata

Select an appropriate control-plane mechanism.

Implement:

- Node registration
- Heartbeats
- Membership inspection
- Node readiness
- Graceful departure
- Failure suspicion
- Failure confirmation
- Topology updates

Distinguish temporary network delay from confirmed node failure.

Do not treat a missed heartbeat alone as authoritative proof of failure.

---

## 18. FAILURE RECOVERY

Design:

- Replica promotion
- Ownership reassignment
- Failed-node replacement
- Replica reconstruction
- Stale-primary fencing
- Client rerouting
- Retry handling

Test:

- Primary crash
- Replica crash
- Network partition
- Node restart
- Multiple simultaneous failures
- Stale topology
- Replica promotion
- Recovery after rejoin

Define what the system does when sufficient replicas or coordinator quorum are unavailable.

---

# PART K — REBALANCING

## 19. ONLINE DATA REBALANCING

Implement rebalancing when:

- A node joins
- A node leaves
- A node fails
- Node capacity changes
- Virtual-node ownership changes

Design a safe migration protocol:

1. Publish proposed topology.
2. Identify affected key ranges.
3. Start snapshot transfer.
4. Track concurrent writes.
5. Transfer changes occurring during migration.
6. Verify transferred data.
7. Atomically activate ownership changes.
8. Fence obsolete owners.
9. Clean up obsolete replicas after safety checks.

Explain how the protocol prevents lost writes during concurrent mutation.

Support:

- Chunked migration
- Bounded transfer buffers
- Backpressure
- Migration progress
- Retry
- Resume
- Checksums
- Idempotent transfer
- Bandwidth throttling

Define behavior when a migration fails midway.

Do not delete the source copy until the destination has been verified and ownership change is safely committed.

---

# PART L — NETWORK PROTOCOL

## 20. CLIENT-SERVER COMMUNICATION

Compare:

- HTTP/JSON
- gRPC
- Netty-based binary protocol

Choose a suitable approach.

Recommended initial direction:

- Spring Boot for administration and control APIs
- gRPC or Netty for the high-throughput data plane

Justify the additional complexity.

Define a protocol for:

- GET
- SET
- DELETE
- EXISTS
- EXPIRE
- CAS
- Batch operations
- Replication
- Snapshot transfer
- Topology discovery

Include:

- Protocol version
- Request ID
- Partition ID
- Topology epoch
- Deadlines
- Error codes
- Payload size limits
- Compression policy
- Authentication
- TLS

Do not automatically retry a timed-out mutation without considering ambiguous execution.

---

# PART M — JAVA 21 AND SPRING BOOT IMPLEMENTATION

## 21. TECHNOLOGY STACK

Use:

| Component | Technology |
|---|---|
| Language | Java 21 |
| Framework | Spring Boot, verified compatible release |
| Build | Maven |
| Admin API | Spring Web MVC |
| Data plane | gRPC or Netty, justified |
| Storage | Custom Java in-memory engine |
| Concurrency | Java 21 concurrency utilities |
| Serialization | Protobuf or binary codec |
| Membership | Selected coordination mechanism |
| Metrics | Micrometer |
| Tracing | OpenTelemetry |
| Testing | JUnit 5, Mockito |
| Integration tests | Testcontainers |
| Benchmarks | JMH, k6/Gatling, custom client |
| Containers | Docker |
| Deployment | Kubernetes |
| Monitoring | Prometheus and Grafana |

Do not use Redis, Hazelcast, Ignite, Infinispan, or Memcached as the implementation of the core cache.

They may be used only as external benchmark references or comparison systems.

---

## 22. PROJECT STRUCTURE

Use a focused multi-module Maven project if module boundaries justify it.

Example:

```text
distributed-cache/
├── pom.xml
├── README.md
├── cache-common/
├── cache-protocol/
├── cache-engine/
├── cache-cluster/
├── cache-server/
├── cache-client/
├── cache-benchmarks/
├── docs/
│   ├── architecture.md
│   ├── consistency.md
│   ├── replication.md
│   ├── rebalancing.md
│   ├── performance.md
│   ├── runbook.md
│   └── decisions/
├── docker/
├── helm/
└── .github/workflows/
```

Keep module dependencies acyclic.

Document interfaces and boundaries.

Avoid unnecessary modules.

---

# PART N — API DESIGN

## 23. CACHE API

Expose a development-friendly HTTP API or equivalent client operations.

Example:

`PUT /api/v1/cache/{key}`

Request:

```json
{
  "value": "customer-data",
  "ttlSeconds": 300
}
```

Example response:

```json
{
  "success": true,
  "version": 42,
  "expiresAt": "2026-11-14T10:00:00Z"
}
```

Also support:

- `GET /api/v1/cache/{key}`
- `DELETE /api/v1/cache/{key}`
- `GET /api/v1/cache/{key}/ttl`
- `POST /api/v1/cache/batch`
- `POST /api/v1/cache/{key}/cas`

Define:

- Authentication
- Authorization
- Status codes
- Serialization
- Version validation
- TTL semantics
- Errors
- Idempotency
- Request deadlines

Avoid putting arbitrary binary keys directly into URL paths without a documented encoding and size constraint.

For production, provide a typed Java client supporting the chosen data-plane protocol.

---

# PART O — DISTRIBUTED FAILURE SCENARIOS

## 24. ANALYZE AND TEST THESE SCENARIOS

1. Two clients update the same key concurrently.
2. Primary fails before replication finishes.
3. Replica receives duplicate replication messages.
4. Replica receives replication events out of order.
5. Old primary accepts writes after failover.
6. Cluster splits into two network partitions.
7. Node joins while writes are active.
8. Node leaves during rebalancing.
9. Client uses an outdated hash ring.
10. Replica is promoted with stale data.
11. Key expires during migration.
12. Eviction occurs during replication.
13. Memory limit is reached.
14. Network timeout happens after SET succeeds.
15. Batch operation partially succeeds.
16. Node restarts with an empty cache.
17. Multiple nodes fail simultaneously.
18. Membership coordinator becomes unavailable.
19. Background expiration competes with heavy write traffic.
20. One key becomes extremely hot.
21. Large values cause network congestion.
22. Replica lag grows indefinitely.
23. Topology changes during client retries.
24. Evicted values reappear from a stale replica.
25. Delete operations are lost during failover.

For each scenario provide:

- Root cause
- Consistency impact
- User-visible behavior
- Mitigation
- Recovery
- Test strategy
- Residual risk

---

# PART P — TESTING

## 25. UNIT TESTS

Implement tests for:

- Hash distribution
- Deterministic ring placement
- Virtual nodes
- Replica selection
- LRU eviction
- LFU eviction
- TTL expiration
- Memory accounting
- Concurrent updates
- CAS
- Routing
- Version comparison

## 26. INTEGRATION TESTS

Test with multiple real cache processes.

Verify:

- Client routing
- Replication
- Node join
- Node leave
- Failover
- Rebalancing
- Stale topology handling
- Expiration
- Eviction
- Authentication

Use Testcontainers where appropriate.

## 27. CONCURRENCY TESTS

Verify:

- Concurrent GET/SET/DELETE
- CAS correctness
- Memory limit enforcement
- Expiration races
- Eviction races
- Replication ordering
- Rebalance under load
- Stale-primary fencing

Where useful, use deterministic scheduling, fault injection, or model-based testing.

## 28. CHAOS TESTS

Simulate:

- Process crashes
- Network partitions
- Latency injection
- Packet loss
- Replica outages
- Membership failures
- CPU throttling
- Memory pressure
- Rolling restarts

Do not claim coverage unless the tests have actually been executed.

---

# PART Q — PERFORMANCE ENGINEERING

## 29. PERFORMANCE TARGETS AND BENCHMARKS

Create workloads for:

- 10,000 ops/second
- 100,000 ops/second
- 1 million ops/second
- 5 million ops/second
- 10 million ops/second

Test:

1. Read-heavy traffic
2. Write-heavy traffic
3. Mixed traffic
4. Uniform key distribution
5. Zipfian distribution
6. Small values
7. Large values
8. High TTL churn
9. Heavy eviction
10. Node rebalancing
11. Replica failover
12. Network degradation

Measure:

- Offered and achieved ops/sec
- p50/p95/p99 latency
- Read and write error rates
- Cache hit ratio
- Memory utilization
- JVM GC pauses
- CPU utilization
- Network bandwidth
- Replication lag
- Queue depth
- Eviction rate
- Expiration rate
- Rebalance throughput
- Key distribution skew

Use JMH for isolated storage-engine microbenchmarks.

Use a distributed load generator for end-to-end cluster benchmarks.

Do not use JMH results alone as evidence of million-ops/sec distributed throughput.

Never fabricate benchmark results.

---

# PART R — SECURITY

## 30. SECURITY REQUIREMENTS

Implement:

- Client authentication
- Inter-node authentication
- TLS or mTLS
- Authorization for administrative operations
- Tenant isolation where supported
- Request size limits
- Connection limits
- Rate limiting for administrative APIs
- Bounded resource consumption
- Secure configuration
- Secret management
- Audit logging

Avoid exposing unrestricted cache administration endpoints publicly.

Document risks associated with arbitrary binary payloads and untrusted clients.

---

# PART S — DEPLOYMENT

## 31. DOCKER AND KUBERNETES

Provide:

- Multi-stage Dockerfile
- Docker Compose with 3+ cache nodes
- Kubernetes StatefulSet where appropriate
- Headless Service
- Persistent cluster identity configuration
- Resource requests and limits
- Readiness/liveness probes
- PodDisruptionBudget
- Anti-affinity rules
- Graceful shutdown
- Horizontal scaling procedure
- Safe rolling upgrades
- Helm chart or equivalent manifests

Explain how node identity differs from pod IP addresses.

Do not assume Kubernetes pod discovery provides a complete consistency-safe membership protocol.

---

# PART T — OBSERVABILITY

## 32. METRICS AND ALERTING

Expose:

- Cache requests
- Cache hits
- Cache misses
- Read latency
- Write latency
- Evictions
- Expirations
- Memory usage
- Replication lag
- Failed replication
- Cluster membership changes
- Topology epoch
- Rebalance progress
- Failed nodes
- Client routing errors
- Network timeouts
- CAS conflicts
- Rejected admissions

Avoid per-key metric labels.

Provide:

- Prometheus configuration
- Grafana dashboard specification
- Structured logging
- Distributed tracing
- SLO alerts
- Cluster runbook

---

# PART U — EXECUTION PLAN

## 33. IMPLEMENTATION PHASES

Execute the project in the following order.

**Phase 1 — Architecture**

Define requirements, consistency model, node ownership, replication approach, and cluster topology authority.

**Phase 2 — Local Cache Engine**

Implement thread-safe in-memory storage, TTL, LRU/LFU, CAS, and memory limits.

**Phase 3 — Consistent Hashing**

Implement hash ring, virtual nodes, replica placement, and deterministic routing.

**Phase 4 — Networking**

Implement the client-server protocol, typed client, server communication, timeouts, and error handling.

**Phase 5 — Replication**

Implement primary-replica replication, write acknowledgments, ordering, and replica synchronization.

**Phase 6 — Membership and Failover**

Implement node discovery, health monitoring, authoritative topology changes, and stale-primary fencing.

**Phase 7 — Rebalancing**

Implement online range migration, concurrent-write capture, verification, and ownership activation.

**Phase 8 — Security and Observability**

Implement authentication, transport security, metrics, tracing, and administrative controls.

**Phase 9 — Deployment**

Provide Docker Compose, Kubernetes/Helm configuration, CI/CD, and operational documentation.

**Phase 10 — Testing and Optimization**

Run unit, integration, concurrency, failure, and benchmark tests. Fix significant defects and document limitations.

For each phase:

- Implement working code.
- Keep the project buildable.
- Run relevant verification.
- Correct discovered defects.
- Preserve unrelated work.
- Explain important changes.
- Document risks and limitations.

Do not stop after the design phase.

---

# PART V — REQUIRED DELIVERABLES

## 34. COMPLETE PROJECT OUTPUTS

Deliver:

### 1. Requirements
- Functional requirements
- Non-functional requirements
- Assumptions
- Acceptance criteria

### 2. High-Level Design
- Architecture diagrams
- Cluster topology
- Data flows
- Capacity planning
- Scaling strategy

### 3. Low-Level Design
- Class diagrams
- Sequence diagrams
- Domain model
- Hash ring design
- Eviction design
- Replication protocol

### 4. Source Code
- Java 21 multi-node cache
- Local storage engine
- Consistent hashing
- Virtual nodes
- Replication
- Eviction
- TTL
- Networking
- Membership
- Failover
- Rebalancing
- Typed Java client

### 5. Tests
- Unit tests
- Integration tests
- Concurrency tests
- Failure tests
- Chaos-test scripts

### 6. Infrastructure
- Docker
- Docker Compose
- Kubernetes
- Helm
- CI/CD

### 7. Performance
- JMH benchmarks
- End-to-end load testing
- Benchmark scripts
- Actual measured results where available
- Bottleneck analysis

### 8. Documentation
- README
- Architecture Decision Records
- Consistency model
- Deployment instructions
- Performance guide
- Operational runbook
- Known limitations

---

# PART W — MANDATORY ARCHITECTURE REVIEW

## 35. ANSWER THESE SYSTEM DESIGN QUESTIONS

1. How does consistent hashing minimize key redistribution?
2. Why use virtual nodes?
3. How do you avoid uneven partition distribution?
4. How are replicas selected?
5. How does primary-replica replication work?
6. What is the difference between synchronous and asynchronous replication?
7. How does replication affect write latency?
8. What happens if a primary crashes before replication?
9. How do you prevent split-brain writes?
10. Why are topology epochs and fencing necessary?
11. What consistency guarantees can this cache provide?
12. Can eventual consistency cause deleted keys to reappear?
13. How do you prevent stale replication from resurrecting values?
14. How do LRU and LFU differ?
15. Why is exact LRU expensive under high concurrency?
16. How do you keep memory usage bounded?
17. How does TTL expiration interact with replication?
18. How do you support node joins without losing writes?
19. How do you migrate keys during rebalancing?
20. How do clients recover from stale topology?
21. What happens during a network partition?
22. How do you recover a stale replica?
23. Should replicas be allowed to serve reads?
24. How do you prevent hot-key overload?
25. How do you handle cache stampedes?
26. How do you scale from 3 to 100 nodes?
27. What is the impact of Java GC on p99 latency?
28. When should Netty or gRPC be preferred over REST?
29. How do you benchmark a distributed cache correctly?
30. What guarantees can a volatile in-memory cache realistically provide?

Answer with architectural reasoning, failure analysis, trade-offs, and implementation evidence.

---

# PART X — DEFINITION OF DONE

## 36. ACCEPTANCE CRITERIA

The project is considered complete only when:

- Java 21 project builds successfully.
- Multiple cache nodes can run simultaneously.
- Consistent hashing is deterministic.
- Virtual-node distribution is tested.
- Cache operations route correctly.
- GET/SET/DELETE work across nodes.
- TTL expiration works.
- LRU and LFU eviction work.
- Memory limits are enforced.
- Replication behavior matches documented semantics.
- Node failures are handled within the selected consistency model.
- Stale owners are rejected.
- Node joins trigger safe rebalancing.
- Clients recover from topology changes.
- Concurrency tests cover significant races.
- Docker Compose starts a functional cluster.
- Kubernetes deployment configuration is provided.
- Metrics and health endpoints work.
- Benchmark scripts are reproducible.
- Performance claims are measured or labeled as unverified.
- Remaining operational risks are documented.

Do not declare production readiness based only on passing unit tests.

---

# FINAL EXECUTION INSTRUCTIONS

Build a **real distributed caching system**, not a CRUD application backed by Redis.

The implementation must demonstrate:

1. **Consistent hashing** with deterministic partition ownership.
2. **Virtual nodes** for improved distribution.
3. **Replication** with explicit consistency guarantees.
4. **Eviction** using working LRU and LFU implementations.
5. **TTL expiration** under concurrency.
6. **Thread-safe in-memory storage** with bounded resource consumption.
7. **Failure detection and recovery**.
8. **Safe rebalancing** when cluster topology changes.
9. **Client routing and network communication**.
10. **Security, observability, testing, and deployment**.

Begin with the architectural assessment and selected consistency model.

Then implement the system end to end, phase by phase.

Use the available development tools to create source files, compile code, run tests, fix failures, and validate multi-node behavior.

At completion report:

- Implemented functionality
- Architecture decisions
- Source files and project structure
- Tests actually executed
- Benchmark measurements, if available
- Known limitations
- Remaining production risks

**Do not stop after High-Level Design or Low-Level Design. Deliver the complete implementation, verification, infrastructure, and operational documentation.**
````