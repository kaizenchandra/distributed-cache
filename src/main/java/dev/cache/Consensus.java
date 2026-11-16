package dev.cache;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;
import java.util.UUID;

/**
 * Consensus metadata only: no cache payloads are stored in etcd.
 */
@Component
public final class Consensus {
    final String prefix;
    final String url;
    final String incarnation = UUID.randomUUID().toString();
    final boolean storage;
    final int vnodes, replicas, minimum, maximum;
    private final Etcd etcd;
    boolean enabled = false;

    public Consensus(Etcd etcd, @Value("${cache.namespace:default}") String namespace, @Value("${cache.node-url:http://localhost:8080}") String url, @Value("${cache.coordinator:false}") boolean gateway, @Value("${cache.vnodes:128}") int vnodes, @Value("${cache.replicas:3}") int replicas, @Value("${cache.minimum-copies:2}") int minimum, @Value("${cache.metadata-max-entries:100000}") int maximum) {
        if (!namespace.matches("[a-zA-Z0-9_-]{1,64}") || vnodes < 1 || vnodes > 4096 || replicas < 1 || minimum < 1 || minimum > replicas || maximum < 1 || maximum > 1000000)
            throw new IllegalArgumentException("consensus config");
        this.etcd = etcd;
        prefix = "/cache/" + namespace + "/";
        this.url = url;
        storage = !gateway;
        this.vnodes = vnodes;
        this.replicas = replicas;
        this.minimum = minimum;
        this.maximum = maximum;
    }

    @Value("${cache.mode:legacy}")
    void mode(String mode) {
        enabled = mode.equals("consensus");
    }

    String topologyKey() {
        return prefix + "topology";
    }

    String slot(String key) {
        if (!java.nio.charset.StandardCharsets.UTF_8.newEncoder().canEncode(key))
            throw new IllegalArgumentException("invalid Unicode key");
        return prefix + "keys/" + java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(key.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    public Etcd.Value topology() {
        return etcd.get(topologyKey());
    }

    public Topology decode(Etcd.Value value) {
        if (value.revision() == 0) throw new IllegalStateException("topology not ready");
        Topology t = etcd.parse(value, Topology.class);
        if (t.virtualNodes() != vnodes || t.replicas() != replicas || t.minimumCopies() != minimum || t.metadataMaxEntries() != maximum)
            throw new IllegalStateException("topology configuration mismatch");
        return t;
    }

    public List<Member> owners(Topology t, String key) {
        if (t.members().size() < minimum) throw new IllegalStateException("insufficient live copies");
        var urls = t.members().stream().map(Member::url).toList();
        var ring = new Ring(urls, vnodes);
        return ring.owners(key, replicas).stream().map(u -> t.members().stream().filter(m -> m.url().equals(u)).findFirst().orElseThrow()).toList();
    }

    @Scheduled(fixedDelay = 1000)
    public void heartbeat() {
        if (!enabled || !storage) return;
        try {
            etcd.register(prefix + "members/" + Etcd.b64(url), new Member(url, incarnation));
        } catch (
                IllegalStateException ignored) {/* quorum unavailable: registration expires; data operations fail closed */}
    }

    public boolean reconcile() {
        List<Member> live = etcd.range(prefix + "members/", true).stream().map(v -> etcd.parse(v, Member.class)).sorted(Comparator.comparing(Member::url)).toList();
        Etcd.Value old = topology();
        Topology next = new Topology(live, vnodes, replicas, minimum, maximum);
        if (old.revision() != 0 && decode(old).equals(next)) return false;
        return etcd.cas(topologyKey(), old.revision(), next, List.of());
    }

    public void authorize(long revision, String target) {
        authorize(revision, target, topology());
    }

    void authorize(long revision, String target, Etcd.Value state) {
        Topology topology = decode(state);
        if (state.revision() != revision || !incarnation.equals(target) || topology.members().stream().noneMatch(m -> m.url().equals(url) && m.incarnation().equals(target)))
            throw new IllegalStateException("stale topology or node incarnation");
    }

    public record Member(String url, String incarnation) {
    }

    public record Topology(List<Member> members, int virtualNodes, int replicas, int minimumCopies,
                           int metadataMaxEntries) {
    }

    public record Manifest(String key, String payload, long version, long expiresAt, boolean deleted,
                           List<Member> owners) {
    }
}
