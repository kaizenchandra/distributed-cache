package dev.cache;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.openjdk.jmh.annotations.*;

/** Isolated storage work only: no HTTP, replication, topology or consensus costs. */
@BenchmarkMode(Mode.Throughput)
@OutputTimeUnit(TimeUnit.SECONDS)
@Warmup(iterations = 3, time = 1)
@Measurement(iterations = 5, time = 1)
@Fork(value = 2, jvmArgsAppend = {"-Xms256m", "-Xmx256m"})
public class StoreBenchmark {
    @State(Scope.Benchmark)
    public static class Shared {
        @Param({"LRU", "LFU", "FIFO"}) public String policy;
        @Param({"128", "4096"}) public int valueBytes;
        Store store;
        byte[] value;
        String[] keys;
        AtomicLong versions;

        @Setup(Level.Trial)
        public void setup() {
            store = new Store(16 * 1024 * 1024, policy, Clock.systemUTC());
            value = new byte[valueBytes];
            keys = new String[1024];
            versions = new AtomicLong(1024);
            for (int i = 0; i < keys.length; i++) {
                keys[i] = "key-" + i;
                store.apply(0, new Store.Entry(keys[i], value, i + 1, 0, false));
            }
        }
    }

    @State(Scope.Thread)
    public static class Cursor {
        int index;
        String key(Shared shared) { return shared.keys[index++ & 1023]; }
    }

    @Benchmark public Store.Entry hit(Shared shared, Cursor cursor) {
        return shared.store.get(cursor.key(shared));
    }

    @Benchmark public byte[] hitAndCopy(Shared shared, Cursor cursor) {
        return shared.store.get(cursor.key(shared)).value();
    }

    @Benchmark public Store.Entry miss(Shared shared) {
        return shared.store.get("absent");
    }

    @Benchmark public void overwrite(Shared shared, Cursor cursor) {
        shared.store.apply(0, new Store.Entry(cursor.key(shared), shared.value,
                shared.versions.incrementAndGet(), 0, false));
    }

    @State(Scope.Thread)
    public static class Pressure {
        @Param({"LRU", "LFU", "FIFO"}) public String policy;
        Store store;
        byte[] value = new byte[1024];
        long version;
        @Setup(Level.Trial) public void setup() {
            store = new Store(64 * 1024, policy, Clock.systemUTC());
        }
    }

    @Benchmark public void eviction(Pressure state) {
        long version = ++state.version;
        state.store.apply(0, new Store.Entry("key-" + version, state.value, version, 0, false));
    }

    @State(Scope.Thread)
    public static class Expiration {
        Store store;
        // Refill outside timed work; reported operation is a sweep of 256 expired entries.
        @Setup(Level.Invocation) public void setup() {
            store = new Store(1024 * 1024, "LRU", Clock.fixed(Instant.ofEpochMilli(1000), ZoneOffset.UTC));
            for (int i = 0; i < 256; i++) store.apply(0, new Store.Entry("key-" + i, new byte[128], i + 1, 999, false));
        }
    }

    @Benchmark public void expireSweep256(Expiration state) { state.store.expire(); }
}
