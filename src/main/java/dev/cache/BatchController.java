package dev.cache;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

/**
 * Bounded, sequential, non-transactional operations with individual outcomes.
 */
@RestController
public final class BatchController {
    private final Function<Coordinator.Request, Coordinator.Result> execute;

    public BatchController(ObjectProvider<Coordinator> legacy, ObjectProvider<ConsensusCoordinator> consensus) {
        var gateway = consensus.getIfAvailable();
        execute = gateway != null ? gateway::operation : legacy.getObject()::operation;
    }

    static List<Item> run(Batch batch, Function<Coordinator.Request, Coordinator.Result> execute) {
        if (batch == null || batch.operations() == null || batch.operations().isEmpty() || batch.operations().size() > 100)
            throw new IllegalArgumentException("batch requires 1..100 operations");
        // Reject malformed envelopes before any writes; valid operations may still fail independently.
        batch.operations().forEach(Coordinator::validate);
        List<Item> results = new ArrayList<>();
        for (var request : batch.operations()) {
            try {
                results.add(new Item(200, execute.apply(request), null));
            } catch (ResponseStatusException e) {
                results.add(new Item(e.getStatusCode().value(), null, "OPERATION_REJECTED"));
            } catch (IllegalArgumentException e) {
                results.add(new Item(400, null, "INVALID_REQUEST"));
            } catch (IllegalStateException e) {
                results.add(new Item(503, null, "UNAVAILABLE_OR_AMBIGUOUS"));
            }
        }
        return List.copyOf(results);
    }

    @PostMapping("/api/v1/cache/batch")
    public List<Item> batch(@RequestBody Batch batch) {
        return run(batch, execute);
    }

    public record Batch(List<Coordinator.Request> operations) {
    }

    public record Item(int status, Coordinator.Result result, String error) {
    }
}
