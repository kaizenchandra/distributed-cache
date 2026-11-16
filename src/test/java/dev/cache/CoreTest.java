package dev.cache;

import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.*;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import static org.junit.jupiter.api.Assertions.*;

class CoreTest {
    @Test
    void deterministicDistributionAndMovement() {
        var ns = List.of("a", "b", "c");
        Ring a = new Ring(ns, 128), b = new Ring(List.of("c", "b", "a"), 128), c = new Ring(List.of("a", "b", "c", "d"), 128);
        Map<String, Integer> counts = new HashMap<>();
        int moved = 0;
        for (int i = 0; i < 30000; i++) {
            String k = "k" + i;
            assertEquals(a.owners(k, 3), b.owners(k, 3));
            assertEquals(3, new HashSet<>(a.owners(k, 3)).size());
            String n = a.owners(k, 1).getFirst();
            counts.merge(n, 1, Integer::sum);
            if (!n.equals(c.owners(k, 1).getFirst())) {
                moved++;
                assertEquals("d", c.owners(k, 1).getFirst());
            }
        }
        assertTrue(moved > 4500 && moved < 11000);
        for (int n : counts.values()) assertTrue(n > 6500 && n < 13500);
    }

    Store.Entry e(String k, long v) {
        return new Store.Entry(k, new byte[200], v, 0, false);
    }

    @Test
    void lruAndLfu() {
        for (String p : List.of("LRU", "LFU")) {
            Store s = new Store(1024, p, Clock.systemUTC());
            s.apply(0, e("a", 1));
            s.apply(0, e("b", 2));
            s.get("a");
            s.get("a");
            s.apply(0, e("c", 3));
            assertNotNull(s.get("a"));
            assertNull(s.get("b"));
            assertTrue(s.stats().get("weight") <= 1024);
        }
    }

    @Test
    void expiryAndOrdering() {
        Store s = new Store(1024, "LRU", Clock.fixed(Instant.ofEpochMilli(1000), ZoneOffset.UTC));
        s.fence(2);
        assertThrows(IllegalStateException.class, () -> s.apply(1, e("a", 1)));
        s.apply(2, new Store.Entry("a", new byte[10], 2, 999, false));
        s.expire();
        assertNull(s.get("a"));
        s.apply(2, e("a", 1));
        assertNull(s.get("a"));
        s.apply(2, e("a", 3));
        assertEquals(3, s.get("a").version());
    }

    @Test
    void concurrentOrderingAndMemory() throws Exception {
        Store s = new Store(2048, "LFU", Clock.systemUTC());
        try (var pool = Executors.newFixedThreadPool(8)) {
            List<Future<?>> fs = new ArrayList<>();
            for (int i = 1; i <= 1000; i++) {
                long v = i;
                fs.add(pool.submit(() -> {
                    s.apply(0, e("a", v));
                    s.get("a");
                }));
            }
            for (var f : fs) f.get();
        }
        assertEquals(1000, s.get("a").version());
        assertTrue(s.stats().get("weight") <= 2048);
    }

    @Test
    void transferAcceptsIndependentExpiryButRejectsDifferentEntries() {
        Clock clock = Clock.fixed(Instant.ofEpochMilli(1000), ZoneOffset.UTC);
        Store source = new Store(1024, "LRU", clock);
        Store destination = new Store(1024, "LRU", clock);
        var live = new Store.Entry("a", new byte[]{1}, 2, 999, false);
        source.apply(0, live);
        destination.apply(0, live);
        source.expire();
        var tombstone = source.raw("a");
        destination.transfer(0, tombstone);
        assertFalse(destination.raw("a").deleted()); // Equal version keeps the old representation.
        assertNull(destination.get("a"));
        assertTrue(Coordinator.sameTransferredEntry(tombstone, destination.raw("a"), 1000));
        assertTrue(Coordinator.sameTransferredEntry(live, tombstone, 1000));
        assertFalse(Coordinator.sameTransferredEntry(live, tombstone, 998));
        assertFalse(Coordinator.sameTransferredEntry(live, new Store.Entry("a", new byte[]{2}, 2, 999, false), 1000));
        assertFalse(Coordinator.sameTransferredEntry(tombstone, new Store.Entry("a", new byte[]{1}, 3, 999, false), 1000));
        assertFalse(Coordinator.sameTransferredEntry(tombstone, new Store.Entry("a", new byte[]{1}, 2, 998, false), 1000));
        assertFalse(Coordinator.sameTransferredEntry(tombstone, new Store.Entry("b", new byte[]{1}, 2, 999, false), 1000));
        assertFalse(Coordinator.sameTransferredEntry(live, null, 1000));
    }

    @Test
    void defensiveCopies() {
        byte[] a = {1};
        var e = new Store.Entry("a", a, 1, 0, false);
        a[0] = 2;
        assertEquals(1, e.value()[0]);
        e.value()[0] = 3;
        assertEquals(1, e.value()[0]);
    }
}
