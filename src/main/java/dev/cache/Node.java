package dev.cache;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.bind.annotation.*;

import java.time.Clock;
import java.util.List;
import java.util.Map;

@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(name = "cache.mode", havingValue = "legacy", matchIfMissing = true)
@RestController
public class Node {
    private final Store store;

    public Node(@Value("${cache.bytes:16777216}") long bytes, @Value("${cache.policy:LRU}") String policy) {
        store = new Store(bytes, policy, Clock.systemUTC());
    }

    @PostMapping("/internal/fence")
    public Map<String, Long> fence(@RequestBody Fence f) {
        store.fence(f.epoch());
        return store.stats();
    }

    @PostMapping("/internal/apply")
    public Map<String, Long> apply(@RequestBody Apply a) {
        store.apply(a.epoch(), a.entry());
        return store.stats();
    }

    @PostMapping("/internal/transfer")
    public Store.Entry transfer(@RequestBody Apply a) {
        store.transfer(a.epoch(), a.entry());
        return store.raw(a.entry().key());
    }

    @GetMapping("/internal/entry")
    public Object get(@RequestParam String key) {
        Store.Entry e = store.get(key);
        return e == null ? Map.of() : e;
    }

    @GetMapping("/internal/page")
    public List<Store.Entry> page(@RequestParam(defaultValue = "") String after) {
        return store.page(after, 32);
    }

    @GetMapping("/internal/stats")
    public Map<String, Long> stats() {
        return store.stats();
    }

    @Scheduled(fixedDelay = 250)
    public void expire() {
        store.expire();
    }

    public record Apply(long epoch, Store.Entry entry) {
    }

    public record Fence(long epoch) {
    }
}
