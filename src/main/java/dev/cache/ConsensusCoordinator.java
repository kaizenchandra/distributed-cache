package dev.cache;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.*;

/**
 * Any gateway can coordinate; etcd per-key CAS is the publication/conditional-write point.
 */
@RestController
@ConditionalOnProperty(name = "cache.mode", havingValue = "consensus")
public final class ConsensusCoordinator {
    private final Consensus c;
    private final Etcd etcd;
    private final Wire wire;
    private final java.util.concurrent.atomic.LongAdder copied = new java.util.concurrent.atomic.LongAdder(), failures = new java.util.concurrent.atomic.LongAdder(), unrecoverable = new java.util.concurrent.atomic.LongAdder(), scanned = new java.util.concurrent.atomic.LongAdder();
    private String cursor = "";
    private long scannedRevision;
    private volatile boolean worker;

    public ConsensusCoordinator(Consensus c, Etcd etcd, @Value("${cache.internal-token}") String token) {
        this.c = c;
        this.etcd = etcd;
        wire = new Wire(token);
    }

    private byte[] requireValue(byte[] value) {
        if (value == null) throw new IllegalArgumentException("value required");
        return value;
    }

    private void gateway() {
        if (c.storage) throw new IllegalStateException("not a gateway");
    }

    private Store.Entry fetch(Consensus.Manifest manifest, List<Consensus.Member> live) {
        if (manifest == null || manifest.deleted() || manifest.expiresAt() > 0 && manifest.expiresAt() <= System.currentTimeMillis())
            return null;
        for (var owner : manifest.owners().stream().sorted(java.util.Comparator.comparingInt(o -> live.contains(o) ? 0 : 1)).toList())
            try {
                Object raw = wire.call(owner.url(), "/internal/consensus/fetch", new ConsensusNode.Fetch(owner.incarnation(), manifest.payload()), Object.class);
                if (raw instanceof Map<?, ?> m && !m.isEmpty()) {
                    Store.Entry e = etcd.json.convertValue(raw, Store.Entry.class);
                    if (e.version() == manifest.version() && e.key().equals(manifest.payload())) return e;
                }
            } catch (IllegalStateException ignored) {
            }
        return null; // Cache loss/eviction is a miss; never fall back to an older version.
    }

    private Consensus.Manifest manifest(Etcd.Value v, String key) {
        if (v.revision() == 0) return null;
        var m = etcd.parse(v, Consensus.Manifest.class);
        return m.key().equals(key) ? m : null;
    }

    @PostMapping("/api/v1/operation")
    public Coordinator.Result operation(@RequestBody Coordinator.Request r) {
        gateway();
        Coordinator.validate(r);
        Etcd.Value state = c.topology();
        var topology = c.decode(state);
        c.owners(topology, r.key());
        Etcd.Value record = etcd.get(c.slot(r.key()));
        var old = manifest(record, r.key());
        Store.Entry visible = fetch(old, topology.members());
        long now = System.currentTimeMillis();
        if (Set.of("GET", "EXISTS", "TTL").contains(r.operation()))
            return new Coordinator.Result(visible != null, r.operation().equals("GET") && visible != null ? visible.value() : null, visible == null ? 0 : old.version(), visible == null ? -2 : old.expiresAt() == 0 ? -1 : Math.max(0, old.expiresAt() - now));
        if (r.operation().equals("CAS") && (r.expectedVersion() == null || r.expectedVersion() != (visible == null ? 0 : old.version())))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "CAS conflict");
        if (r.operation().equals("EXPIRE") && visible == null) return new Coordinator.Result(false, null, 0, -2);
        boolean deleted = r.operation().equals("DELETE") || r.ttlMillis() == 0;
        byte[] value = deleted ? new byte[0] : r.operation().equals("EXPIRE") ? visible.value() : requireValue(r.value());
        long version = Math.addExact(record.revision(), 1), expiry = r.ttlMillis() < 0 ? 0 : now + r.ttlMillis();
        String payload = UUID.randomUUID().toString();
        var owners = c.owners(topology, r.key());
        if (!deleted) {
            var entry = new Store.Entry(payload, value, version, expiry, false);
            for (var owner : owners)
                wire.call(owner.url(), "/internal/consensus/stage", new ConsensusNode.Stage(state.revision(), owner.incarnation(), entry), Store.Entry.class);
        }
        var next = new Consensus.Manifest(r.key(), payload, version, expiry, deleted, owners);
        if (!etcd.publish(c.slot(r.key()), record.revision(), next, List.of(etcd.compare(c.topologyKey(), state.revision())), c.prefix + "metadata-count", c.maximum))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "topology or key changed; mutation not published");
        return new Coordinator.Result(!deleted, null, version, deleted ? -2 : r.ttlMillis());
    }

    @Scheduled(fixedDelay = 250)
    public void maintain() {
        if (c.storage) return;
        try {
            c.reconcile();
            repair();
        } catch (IllegalStateException ignored) {
            failures.increment();
        }
    }

    /**
     * One leased worker scans existing manifests in bounded pages, with per-entry failure isolation.
     */
    public synchronized void repair() {
        worker = etcd.claim(c.prefix + "repair-worker", c.incarnation);
        if (!worker) return;
        var state = c.topology();
        var topology = c.decode(state);
        if (topology.members().size() < c.minimum) return;
        if (scannedRevision != state.revision()) {
            cursor = "";
            scannedRevision = state.revision();
        }
        var page = etcd.page(c.prefix + "keys/", cursor, 32);
        for (var record : page) {
            cursor = record.key();
            scanned.increment();
            try {
                var old = etcd.parse(record, Consensus.Manifest.class);
                if (old.deleted() || old.expiresAt() > 0 && old.expiresAt() <= System.currentTimeMillis()) continue;
                var desired = c.owners(topology, old.key());
                Store.Entry entry = null;
                for (var owner : desired) {
                    boolean present = false;
                    try {
                        Object raw = wire.call(owner.url(), "/internal/consensus/fetch", new ConsensusNode.Fetch(owner.incarnation(), old.payload()), Object.class);
                        if (raw instanceof Map<?, ?> m && !m.isEmpty()) {
                            var existing = etcd.json.convertValue(raw, Store.Entry.class);
                            present = existing.version() == old.version();
                        }
                    } catch (IllegalStateException ignored) {
                    }
                    if (present) continue;
                    if (entry == null) {
                        entry = fetch(old, topology.members());
                        if (entry == null) {
                            unrecoverable.increment();
                            break;
                        }
                    }
                    Store.Entry verified = wire.call(owner.url(), "/internal/consensus/stage", new ConsensusNode.Stage(state.revision(), owner.incarnation(), entry), Store.Entry.class);
                    if (verified.version() != entry.version() || !verified.key().equals(entry.key()) || verified.expiresAt() != entry.expiresAt() || !Arrays.equals(verified.value(), entry.value()))
                        throw new IllegalStateException("repair verification mismatch");
                    copied.increment();
                }
                // Re-probe all destinations before publishing a new replica set.
                if (!old.owners().equals(desired)) {
                    boolean verified = true;
                    for (var owner : desired) {
                        Object raw = wire.call(owner.url(), "/internal/consensus/fetch", new ConsensusNode.Fetch(owner.incarnation(), old.payload()), Object.class);
                        if (!(raw instanceof Map<?, ?> m) || m.isEmpty()) {
                            verified = false;
                            break;
                        }
                    }
                    if (verified)
                        etcd.cas(record.key(), record.revision(), new Consensus.Manifest(old.key(), old.payload(), old.version(), old.expiresAt(), false, desired), List.of(etcd.compare(c.topologyKey(), state.revision())));
                }
            } catch (IllegalStateException e) {
                failures.increment();
            }
        }
        if (page.size() < 32) cursor = "";
    }

    @GetMapping("/admin/repair")
    public synchronized Object repairStatus() {
        gateway();
        return Map.of("identity", c.incarnation, "worker", worker, "cursor", cursor, "scanned", scanned.sum(), "copied", copied.sum(), "failures", failures.sum(), "unrecoverableObservations", unrecoverable.sum());
    }

    @GetMapping("/admin/topology")
    public Object topology() {
        gateway();
        var state = c.topology();
        return Map.of("revision", state.revision(), "topology", c.decode(state), "minimumCopies", c.minimum);
    }

    @PostMapping("/admin/bootstrap")
    public Object bootstrap() {
        gateway();
        c.reconcile();
        return topology();
    }
}
