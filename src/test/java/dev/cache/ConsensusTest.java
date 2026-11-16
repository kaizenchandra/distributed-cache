package dev.cache;

import org.junit.jupiter.api.Test;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;


class ConsensusTest {
    private Consensus consensus(Etcd etcd) {
        return new Consensus(etcd, "test", "http://node", false, 128, 3, 2, 32);
    }

    @Test
    void fencesExactTopologyAndIncarnation() throws Exception {
        Etcd etcd = new Etcd("http://unused");
        Consensus c = consensus(etcd);
        var member = new Consensus.Member(c.url, c.incarnation);
        var topology = new Consensus.Topology(List.of(member), 128, 3, 2, 32);
        var state = new Etcd.Value(c.topologyKey(), etcd.json.writeValueAsString(topology), 42);
        assertDoesNotThrow(() -> c.authorize(42, c.incarnation, state));
        assertThrows(IllegalStateException.class, () -> c.authorize(41, c.incarnation, state));
        assertThrows(IllegalStateException.class, () -> c.authorize(42, "replaced", state));
    }

    @Test
    void configurationCannotSilentlyForkRouting() throws Exception {
        Etcd etcd = new Etcd("http://unused");
        Consensus c = consensus(etcd);
        var invalid = new Consensus.Topology(List.of(), 128, 3, 2, 64);
        assertThrows(IllegalStateException.class, () -> c.decode(new Etcd.Value(c.topologyKey(), etcd.json.writeValueAsString(invalid), 1)));
    }

    @Test
    void metadataAddressesAreInjectiveAndReplicaFloorEnforced() {
        Consensus c = consensus(new Etcd("http://unused"));
        Set<String> slots = new HashSet<>();
        for (int i = 0; i < 10000; i++) slots.add(c.slot("key" + i));
        assertEquals(10000, slots.size());
        assertNotEquals(c.slot("é"), c.slot("é"));
        assertThrows(IllegalArgumentException.class, () -> c.slot("\ud800"));
        assertThrows(IllegalStateException.class, () -> c.owners(new Consensus.Topology(List.of(new Consensus.Member("a", "1")), 128, 3, 2, 32), "key"));
    }

    @Test
    void secureClientRejectsPlaintextEndpoints() {
        var env = new org.springframework.mock.env.MockEnvironment().withProperty("cache.etcd-security.enabled", "true");
        assertThrows(IllegalArgumentException.class, () -> new Etcd("http://localhost:2379", env));
    }
}
