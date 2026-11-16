package dev.cache;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.*;

/**
 * Single authority; never run two coordinators with the same credentials. No automatic promotion.
 */
@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(name = "cache.mode", havingValue = "legacy", matchIfMissing = true)
@RestController
public class Coordinator {
    private final boolean enabled;
    private final Wire wire;
    private final int replicas, vnodes;
    private final ObjectMapper json = new ObjectMapper();
    private Ring ring;
    private long epoch = 1, version;
    private boolean ready;

    public Coordinator(@Value("${cache.coordinator:false}") boolean enabled, @Value("${cache.nodes:http://localhost:8080}") String nodes, @Value("${cache.internal-token}") String token, @Value("${cache.replicas:3}") int replicas, @Value("${cache.vnodes:128}") int vnodes) {
        this.enabled = enabled;
        wire = new Wire(token);
        if (replicas < 1 || replicas > 100) throw new IllegalArgumentException("replicas");
        this.replicas = replicas;
        this.vnodes = vnodes;
        ring = new Ring(List.of(nodes.split(",")), vnodes);
    }

    static boolean sameTransferredEntry(Store.Entry expected, Store.Entry received, long now) {
        if (received == null || !expected.key().equals(received.key())
                || expected.version() != received.version() || expected.expiresAt() != received.expiresAt())
            return false;
        // Expiry workers run independently. An equal-version transfer is idempotent,
        // so an expired payload may remain at a replica after its source became a tombstone.
        if (expected.expiresAt() > 0 && expected.expiresAt() <= now
                && (expected.deleted() || received.deleted())) return true;
        return expected.deleted() == received.deleted() && Arrays.equals(expected.value(), received.value());
    }

    static void validate(Request r) {
        if (r == null || r.operation() == null || !Set.of("GET", "SET", "DELETE", "EXISTS", "TTL", "EXPIRE", "CAS").contains(r.operation())
                || r.key() == null || r.key().isEmpty() || r.key().length() > 512
                || !java.nio.charset.StandardCharsets.UTF_8.newEncoder().canEncode(r.key())
                || r.value() != null && r.value().length > 65536
                || r.ttlMillis() < -1 || r.ttlMillis() > 31536000000L
                || Set.of("SET", "CAS").contains(r.operation()) && r.ttlMillis() != 0 && r.value() == null
                || r.operation().equals("CAS") && (r.expectedVersion() == null || r.expectedVersion() < 0))
            throw new IllegalArgumentException("request limits");
    }

    private void check() {
        if (!enabled || !ready)
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "coordinator inactive; bootstrap required");
    }

    private Store.Entry read(String key) {
        Object raw = wire.call(ring.owners(key, replicas).getFirst(), "/internal/entry?key=" + java.net.URLEncoder.encode(key, java.nio.charset.StandardCharsets.UTF_8), null, Object.class);
        Map<?, ?> m = (Map<?, ?>) raw;
        return m.isEmpty() ? null : json.convertValue(raw, Store.Entry.class);
    }

    @PostMapping("/api/v1/operation")
    public synchronized Result operation(@RequestBody Request r) {
        check();
        validate(r);
        Store.Entry old;
        try {
            old = read(r.key());
        } catch (IllegalStateException failure) {
            if (!Set.of("GET", "EXISTS", "TTL").contains(r.operation())) ready = false;
            throw failure;
        }
        long now = System.currentTimeMillis();
        if (Set.of("GET", "EXISTS", "TTL").contains(r.operation()))
            return new Result(old != null, r.operation().equals("GET") && old != null ? old.value() : null, old == null ? 0 : old.version(), old == null ? -2 : old.expiresAt() == 0 ? -1 : Math.max(0, old.expiresAt() - now));
        if (!Set.of("SET", "DELETE", "CAS", "EXPIRE").contains(r.operation()))
            throw new IllegalArgumentException("unknown operation");
        if (r.operation().equals("CAS") && (r.expectedVersion() == null || (old == null ? 0 : old.version()) != r.expectedVersion()))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "CAS conflict");
        if (r.operation().equals("EXPIRE") && old == null) return new Result(false, null, 0, -2);
        boolean deleted = r.operation().equals("DELETE") || r.ttlMillis() == 0;
        byte[] value = deleted ? new byte[0] : r.operation().equals("EXPIRE") ? old.value() : Objects.requireNonNull(r.value(), "value required");
        Store.Entry entry = new Store.Entry(r.key(), value, ++version, r.ttlMillis() < 0 ? 0 : Math.addExact(now, r.ttlMillis()), deleted);
        try {
            for (String n : ring.owners(r.key(), replicas))
                wire.call(n, "/internal/apply", new Node.Apply(epoch, entry), Map.class);
        } catch (IllegalStateException failure) {
            ready = false;
            throw failure;
        }
        return new Result(!deleted, null, version, deleted ? -2 : r.ttlMillis());
    }

    @PostMapping("/admin/bootstrap")
    public synchronized Object bootstrap() {
        if (!enabled || ready) throw new IllegalStateException("not eligible");
        if (ring.nodes().size() < replicas) throw new IllegalStateException("insufficient nodes");
        for (String n : ring.nodes()) {
            Map<?, ?> s = wire.call(n, "/internal/stats", null, Map.class);
            if (((Number) s.get("entries")).longValue() != 0 || ((Number) s.get("epoch")).longValue() != 0)
                throw new IllegalStateException("bootstrap requires fresh nodes");
        }
        for (String n : ring.nodes()) wire.call(n, "/internal/fence", new Node.Fence(epoch), Map.class);
        ready = true;
        return topology();
    }

    @PostMapping("/admin/topology")
    public synchronized Object change(@RequestBody Topology t) {
        check();
        Ring next = new Ring(t.nodes(), vnodes);
        if (next.nodes().size() < replicas) throw new IllegalArgumentException("insufficient replicas");
        // Mutations hold this same monitor. Fence every source and destination before copying.
        ready = false;
        epoch++;
        Set<String> all = new HashSet<>(ring.nodes());
        all.addAll(next.nodes());
        for (String n : all) wire.call(n, "/internal/fence", new Node.Fence(epoch), Map.class);
        for (String source : ring.nodes()) {
            String after = "";
            while (true) {
                Store.Entry[] page = wire.call(source, "/internal/page?after=" + java.net.URLEncoder.encode(after, java.nio.charset.StandardCharsets.UTF_8), null, Store.Entry[].class);
                if (page.length == 0) break;
                for (Store.Entry e : page) {
                    if (ring.owners(e.key(), replicas).getFirst().equals(source)) {
                        for (String dest : next.owners(e.key(), replicas)) {
                            Store.Entry received = wire.call(dest, "/internal/transfer", new Node.Apply(epoch, e), Store.Entry.class);
                            if (!sameTransferredEntry(e, received, System.currentTimeMillis()))
                                throw new IllegalStateException("transfer verification failed");
                        }
                    }
                    after = e.key();
                }
            }
        }
        ring = next;
        ready = true;
        return topology();
    }

    @GetMapping("/admin/topology")
    public synchronized Object topology() {
        if (!enabled) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        return Map.of("epoch", epoch, "ready", ready, "nodes", ring.nodes(), "replicas", replicas);
    }

    public record Request(String operation, String key, byte[] value, long ttlMillis, Long expectedVersion) {
    }

    public record Result(boolean found, byte[] value, long version, long ttlMillis) {
    }

    public record Topology(List<String> nodes) {
    }
}
