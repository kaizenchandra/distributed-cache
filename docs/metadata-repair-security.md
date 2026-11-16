# Collision-free metadata, paginated repair and authenticated etcd

This is the current consensus-mode behavior. It supersedes the fixed-slot and unsecured-client sections of
consensus-v2.md. The cache data plane remains HTTP with bearer credentials in the local samples; the mTLS implementation
here protects cache-to-etcd and etcd-to-etcd traffic, not cache client/storage RPCs.

## Metadata index and admission

Each key has an exact metadata address: namespace prefix + `keys/` + unpadded Base64url of its UTF-8 bytes. Keys are not
normalized. Malformed Unicode surrogate input is rejected before encoding, avoiding replacement-character aliasing. The
full original key remains in the manifest as an additional identity check. There is no modulo or shortened hash in this
metadata address, and creating another key never overwrites its manifest.

`cache.metadata-max-entries` defaults to 100,000 and is startup-validated between 1 and 1,000,000. Every first manifest
publication atomically compares topology revision, absent key revision and admission-counter revision, then creates the
manifest and increments the counter in one etcd transaction. Existing-key mutations do not consume another entry.
Competing creates retry only transactions explicitly rejected by their comparisons, up to eight attempts; ambiguity from
transport failure is never automatically replayed. Exhausted contention returns 409, exhausted metadata capacity
returns 507. Existing-key updates and reads continue at the capacity limit.

Deleted and expired manifests retain their admission reservation. This prevents delayed writes from exploiting a removed
absent-key generation and keeps current metadata bounded. It also means a workload with indefinitely new keys eventually
gets 507: automatic generation-safe metadata garbage collection and live quota changes are not implemented. Choose a
suitable limit, monitor the namespace `metadata-count` key, and include capacity planning for retained tombstones.
Historical etcd revisions still require compaction and backend quota management. Payload eviction remains a separate
bounded local-cache policy.

The topology now contains `metadataMaxEntries` instead of `metadataSlots`. Old fixed-slot namespaces are intentionally
rejected rather than silently reinterpreted. Use a **fresh namespace** when deploying this schema. Existing
namespaces/data are not deleted or automatically migrated. A live migration from fixed-slot metadata is not provided; it
needs a separately verified cutover/export procedure. Never edit the counter independently of manifests.

## Repair changes

One gateway claims a five-second etcd lease as repair worker. Other gateways continue serving clients and take over
repair after lease expiry if the worker dies. Manifest publication still uses topology-and-manifest CAS; the lease
controls duplicate work, not correctness. A long stalled repair may overlap its successor, but cannot publish stale
ownership.

The worker scans at most 32 existing manifests per maintenance tick with etcd range pagination, rather than polling
empty slots. Maintenance has a 250ms fixed delay after its work finishes. A topology revision change resets the cursor
immediately. The cursor wraps at the end of the index. Each entry has independent failure handling, so a failed entry
advances the local scan and is retried on a subsequent sweep. Cursor state is local: a newly elected repair worker
restarts its scan; a durable repair checkpoint is not implemented.

Repair probes current destinations first and transfers only missing copies. Source reads prefer members of the current
topology and accept only the exact committed payload ID/version. Every copied payload is checked for ID, version,
expiration and byte equality. All destinations are probed before publishing a changed replica set. Concurrent writes or
topology changes invalidate that publication by CAS. Completely lost payloads are recorded as unrecoverable observations
and remain cache misses; repair does not reconstruct nonexistent data or resurrect older values.

`GET /admin/repair` requires the admin token and returns worker identity, last claim status, cursor and cumulative
scanned/copied/failure/unrecoverable-observation counts. Worker status is observational, not a lease-validity promise.
Large repairs and repeated timeouts can take multiple sweeps. There is no transfer bandwidth controller or durable
progress journal yet.

## Java etcd client security

Use [the configuration example](../deploy/etcd-client-security.properties). Secure mode requires every etcd endpoint to
use HTTPS and requires all of:

| Property under `cache.etcd-security` | Meaning                                             |
|--------------------------------------|-----------------------------------------------------|
| `enabled`                            | Set true to require the secure client configuration |
| `key-store`                          | PKCS12 client identity and certificate chain        |
| `key-password-file`                  | UTF-8 file containing its store/key password        |
| `trust-store`                        | PKCS12 containing trusted etcd CA certificates      |
| `trust-password-file`                | Trust-store password file                           |
| `username`                           | Namespace-scoped etcd user, not root                |
| `password-file`                      | File containing that user's password                |

The client keeps hostname verification enabled, accepts TLS 1.2/1.3, and never installs a permissive trust manager.
Invalid/missing stores, private keys and credentials fail configuration validation. Runtime authentication or quorum
failures return 503; they never enable an unsecured fallback. Password files are read at startup and surrounding
whitespace is stripped; provision passwords without leading/trailing whitespace. Client PKCS12 store and private-key
passwords must match.

**The transport client certificate must have no Common Name.** etcd's authenticated JSON gateway rejects clients
presenting a CN because it cannot use certificate-CN user authentication as the direct gRPC API does. Use an
organization subject and clientAuth EKU; use username/password token authentication for etcd authorization. Startup
validation rejects a CN-bearing private-key certificate with a configuration error. The server/peer certificates still
need valid SANs for their endpoint names and appropriate serverAuth/clientAuth usages. Include complete CA chains,
authority/subject key identifiers and key usages; do not disable strict certificate checks to accept malformed
certificates.

The client authenticates through `/v3/auth/authenticate`, sends the returned token as the Authorization header and
refreshes once after an explicit UNAUTHENTICATED rejection. This narrowly permitted replay is safe because etcd rejected
authentication before executing the request. Network timeouts and ambiguous mutations are not automatically replayed.
Passwords and tokens are not included in application request logs. Certificate/password rotation currently requires
restarting clients; restart storage one node at a time and verify repair before proceeding.

## Provisioning etcd

Operate a real three-or-more-member cluster. Set client `--cert-file`, `--key-file`, `--trusted-ca-file`,
`--client-cert-auth`, plus peer `--peer-cert-file`, `--peer-key-file`, `--peer-trusted-ca-file`,
`--peer-client-cert-auth`. Set minimum TLS 1.2. Ensure SANs match the advertised client and peer names. Restrict ingress
to authorized service/admin networks.

Before exposing a fresh cluster to applications, use etcdctl with your trusted transport certificate and CA to provision
authorization. These commands prompt for passwords rather than placing them in command arguments:

```sh
# Configure ETCDCTL_ENDPOINTS, ETCDCTL_CACERT, ETCDCTL_CERT and ETCDCTL_KEY.
etcdctl user add root
etcdctl user grant-role root root
etcdctl role add cache-role
etcdctl role grant-permission cache-role readwrite /cache/production-v3/ --prefix=true
etcdctl user add cache
etcdctl user grant-role cache cache-role
etcdctl auth enable
# Subsequent admin operations use --user=root and an interactive password prompt.
```

The cache account must have read/write access only to its namespace, covering membership leases, topology, manifests,
admission counter and repair-worker key. Do not grant it the root role or permissions outside that prefix. Protect root
credentials separately. Cache processes are trusted authority participants; compromise of their namespace-write
credentials can corrupt that namespace. TLS does not provide Byzantine protection.

Mount secrets read-only with permissions readable by the service UID (the container defaults to UID 10001), and prohibit
unrelated users from reading private keys/passwords. No real secrets are committed. The existing Compose configurations
remain explicitly unsecured local examples; configuring a secured external etcd cluster requires the properties above.
Production secured Compose/Kubernetes deployment was not executed.

## Executable verification

```sh
mvn verify
ETCD_BIN=/path/to/etcd python3 scripts/consensus_failure.py
CACHE_SECURE_TEST=1 ETCD_BIN=/path/to/etcd python3 scripts/consensus_failure.py
```

`etcdctl` must be next to the etcd binary, or set ETCDCTL_BIN. Secure tests require OpenSSL and keytool.
`scripts/pki.py` generates short-lived **test-only** certificates and stores in a fresh temporary directory; it is not
production PKI provisioning. The secure suite enables client and peer mTLS, namespace-scoped username/password
authorization, and five-second auth tokens to exercise token renewal. It starts three native etcd members, four storage
JVMs, two gateway JVMs, plus a temporary incorrect-credentials gateway. Ports are preflight-checked and child-process
liveness is asserted.

The tests cover TLS missing-client-certificate/untrusted-server-CA rejection, missing/wrong authentication, namespace
escape rejection, Java gateway fail-closed behavior, concurrent cross-gateway CAS, delayed stale publication, primary
crash and repair, empty restart, stale incarnation/epoch, gateway isolation/restart, delete visibility, leased
repair-worker handoff, more keys than the former slot count without collision eviction, concurrent admission to the hard
cap, actual etcd leader loss/re-election and rejection without quorum. These are functional failure tests, not a
throughput benchmark or exhaustive proof of the protocol.

Sources: [etcd transport security](https://etcd.io/docs/v3.6/op-guide/security/)
and [etcd API guarantees](https://etcd.io/docs/v3.6/learning/api_guarantees/).
