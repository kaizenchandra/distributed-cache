package dev.cache;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.time.Clock;
import java.util.Arrays;
import java.util.Map;

@RestController
@ConditionalOnProperty(name = "cache.mode", havingValue = "consensus")
public final class ConsensusNode {
    private final Consensus consensus;
    private final Store store;

    public ConsensusNode(Consensus consensus, @Value("${cache.bytes:16777216}") long bytes, @Value("${cache.policy:LRU}") String policy) {
        this.consensus = consensus;
        store = new Store(bytes, policy, Clock.systemUTC());
    }

    @PostMapping("/internal/consensus/stage")
    public synchronized Store.Entry stage(@RequestBody Stage stage) {
        if (!consensus.storage) throw new IllegalStateException("not storage");
        if (stage.entry().key().length() != 36 || stage.entry().value().length > 65536 || stage.entry().version() < 1)
            throw new IllegalArgumentException("stage limits");
        java.util.UUID.fromString(stage.entry().key());
        consensus.authorize(stage.topologyRevision(), stage.incarnation());
        // Version payload IDs are immutable. Same ID with different bytes must never overwrite.
        Store.Entry previous = store.raw(stage.entry().key());
        if (previous != null && (previous.version() != stage.entry().version() || previous.expiresAt() != stage.entry().expiresAt() || previous.deleted() != stage.entry().deleted() || !Arrays.equals(previous.value(), stage.entry().value())))
            throw new IllegalStateException("immutable payload conflict");
        store.apply(0, stage.entry());
        return stage.entry();
    }

    @PostMapping("/internal/consensus/fetch")
    public Object fetch(@RequestBody Fetch request) {
        if (!consensus.incarnation.equals(request.incarnation())) throw new IllegalStateException("node replaced");
        Store.Entry e = store.get(request.payload());
        return e == null ? Map.of() : e;
    }

    @org.springframework.scheduling.annotation.Scheduled(fixedDelay = 250)
    public void expire() {
        store.expire();
    }

    @GetMapping("/internal/consensus/stats")
    public Object stats() {
        return Map.of("incarnation", consensus.incarnation, "storage", store.stats());
    }

    public record Stage(long topologyRevision, String incarnation, Store.Entry entry) {
    }

    public record Fetch(String incarnation, String payload) {
    }
}
