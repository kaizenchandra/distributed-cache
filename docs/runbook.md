# Operations and security

Bootstrap only fresh empty nodes. GET `/admin/topology` reports epoch/readiness/nodes. POST `/admin/topology` with
`{ "nodes": ["http://node-a:8080", "http://node-b:8080", "http://node-c:8080", "http://node-d:8080"] }` changes
membership. This pauses all client requests during transfer; start destination nodes first. Never alter the coordinator
count. Transfer errors deliberately stop service. Preserve logs, diagnose the cause, then perform an explicitly
authorized full volatile-cluster reset; there is no resume endpoint.

A single storage process failure can make requests unavailable; no automatic promotion. Restarting with empty memory
does not reconstruct replicas. Coordinator restart requires full reset because topology/version state is volatile.
Rolling upgrades preserving cache contents are unsupported. Prefer a planned outage and explicit cache reset. PDB
minAvailable=3 prevents ordinary voluntary node eviction of the three-node sample but cannot prevent failures.

Kubernetes DNS names provide logical stable identities distinct from ephemeral pod IPs. A replacement pod reuses
identity but not memory; do not infer readiness for data from health. Health is process health only, not cluster
readiness. Expose coordinator through an authenticated private ingress or port-forward; no public service is supplied.
Restrict pod ingress through NetworkPolicy/firewalls. TLS can be configured with Spring Boot server.ssl properties and a
mounted certificate; inter-node HTTPS requires JVM trust configuration. TLS/mTLS is not enabled or tested by supplied
samples. Plain HTTP samples are restricted to trusted local environments. Tokens are distinct role credentials, startup
validated, supplied through environment/Kubernetes Secret; do not log them. Internal token compromise permits arbitrary
node mutation. No tenant isolation or credential rotation protocol.

Servlet threads, connections and backlog are capped. Payload size is checked before JSON parsing, including chunked
requests. Long/slow bodies, RPC allocation bursts, authentication brute force and administrator DoS still require
ingress limits and mTLS. Admin requests share a global lock, with no rate limiter. Audit logging is not yet supplied.

Prometheus scrape example is in deploy/. Actuator provides JVM/HTTP/process metrics; custom cache counters and topology
gauges are not yet wired. `/internal/stats` reports entries, logical bytes, epoch, eviction and expiration counters with
internal authorization. Suggested dashboard: successful client rate, HTTP latency histogram, error ratio, JVM heap/GC
pause, node stats, cluster ready. Do not count internal RPC rate as client throughput; avoid key labels. Alerts for
coordinator unavailable, sustained 5xx, heap pressure and long GC pauses need environment-specific thresholds.
OpenTelemetry export/tracing and Grafana dashboard JSON remain unimplemented.
