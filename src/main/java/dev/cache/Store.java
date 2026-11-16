package dev.cache;

import java.time.Clock;
import java.util.*;

/**
 * One lock makes admission, accounting, expiry and CAS atomic. Logical weight, not heap bytes.
 */
public final class Store {
    private final Map<String, Slot> data = new HashMap<>();
    private final long limit;
    private final String policy;
    private final Clock clock;
    private long weight, ticks, epoch, evictions, expirations;

    public Store(long limit, String policy, Clock clock) {
        if (limit < 1024 || !Set.of("LRU", "LFU", "FIFO").contains(policy))
            throw new IllegalArgumentException("store config");
        this.limit = limit;
        this.policy = policy;
        this.clock = clock;
    }

    public synchronized void fence(long next) {
        if (next < epoch) throw new IllegalStateException("stale epoch");
        epoch = next;
    }

    public synchronized Entry get(String key) {
        Slot s = data.get(key);
        if (s == null) return null;
        if (s.entry.deleted() || expired(s.entry)) return null;
        if (!policy.equals("FIFO")) s.access = ++ticks;
        s.frequency = Math.min(Long.MAX_VALUE - 1, s.frequency) + 1;
        return s.entry;
    }

    private boolean expired(Entry e) {
        return e.expiresAt() > 0 && e.expiresAt() <= clock.millis();
    }

    public synchronized void transfer(long supplied, Entry e) {
        Slot old = data.get(e.key());
        if (weight + e.weight() - (old == null ? 0 : old.entry.weight()) > limit)
            throw new IllegalStateException("migration capacity insufficient");
        apply(supplied, e);
    }

    public synchronized Entry raw(String key) {
        Slot s = data.get(key);
        return s == null ? null : s.entry;
    }

    public synchronized void apply(long supplied, Entry e) {
        if (supplied != epoch) throw new IllegalStateException("stale epoch");
        Slot old = data.get(e.key());
        if (old != null && old.entry.version() >= e.version()) return;
        if (e.weight() > limit) throw new IllegalArgumentException("entry exceeds cache capacity");
        long delta = e.weight() - (old == null ? 0 : old.entry.weight());
        while (weight + delta > limit) {
            var victim = data.entrySet().stream().filter(x -> !x.getKey().equals(e.key())).min(Comparator.<Map.Entry<String, Slot>>comparingLong(x -> policy.equals("LFU") ? x.getValue().frequency : x.getValue().access).thenComparingLong(x -> x.getValue().access)).orElseThrow();
            weight -= victim.getValue().entry.weight();
            data.remove(victim.getKey());
            evictions++;
        }
        data.put(e.key(), new Slot(e, ++ticks));
        weight += delta;
    }

    // Expiration keeps a bounded version watermark until eviction to reject delayed updates.
    public synchronized void expire() {
        for (Slot s : data.values())
            if (!s.entry.deleted() && expired(s.entry)) {
                Entry e = s.entry;
                Entry t = new Entry(e.key(), new byte[0], e.version(), e.expiresAt(), true);
                weight -= e.weight() - t.weight();
                s.entry = t;
                expirations++;
            }
    }

    public synchronized List<Entry> page(String after, int count) {
        return data.keySet().stream().filter(k -> k.compareTo(after) > 0).sorted().limit(count).map(k -> data.get(k).entry).toList();
    }

    public synchronized Map<String, Long> stats() {
        return Map.of("weight", weight, "entries", (long) data.size(), "epoch", epoch, "evictions", evictions, "expirations", expirations);
    }

    public record Entry(String key, byte[] value, long version, long expiresAt, boolean deleted) {
        public Entry {
            value = value.clone();
        }

        @Override
        public byte[] value() {
            return value.clone();
        }

        long weight() {
            return 160L + key.length() * 2L + value.length;
        }
    }

    private static final class Slot {
        Entry entry;
        long access, frequency = 1;

        Slot(Entry e, long a) {
            entry = e;
            access = a;
        }
    }
}
