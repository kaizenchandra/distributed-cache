package dev.cache;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class BatchTest {
    Coordinator.Request request(String operation) {
        return new Coordinator.Request(operation, "aw", new byte[]{1}, -1, null);
    }

    @Test
    void partialSuccessPreservesOrderAndContinues() {
        var calls = new AtomicInteger();
        var results = BatchController.run(new BatchController.Batch(List.of(request("SET"), request("GET"), request("DELETE"))), r -> {
            int n = calls.incrementAndGet();
            if (n == 2) throw new ResponseStatusException(HttpStatus.CONFLICT);
            return new Coordinator.Result(true, null, n, -1);
        });
        assertEquals(List.of(200, 409, 200), results.stream().map(BatchController.Item::status).toList());
        assertEquals(3, results.get(2).result().version());
    }

    @Test
    void invalidEnvelopeNeverExecutesAndLimitsAreBounded() {
        var calls = new AtomicInteger();
        for (var requests : List.of(List.<Coordinator.Request>of(), Collections.nCopies(101, request("GET")), List.of(request("SET"), request("INVALID")))) {
            assertThrows(IllegalArgumentException.class, () -> BatchController.run(new BatchController.Batch(requests), r -> {
                calls.incrementAndGet();
                return null;
            }));
        }
        assertEquals(0, calls.get());
    }

    @Test
    void invalidMutationIsRejectedBeforePeerAccess() {
        assertThrows(IllegalArgumentException.class, () -> Coordinator.validate(new Coordinator.Request("SET", "aw", null, -1, null)));
        assertThrows(IllegalArgumentException.class, () -> Coordinator.validate(request("CAS")));
        assertThrows(IllegalArgumentException.class, () -> Coordinator.validate(new Coordinator.Request(null, "aw", null, -1, null)));
    }
}
