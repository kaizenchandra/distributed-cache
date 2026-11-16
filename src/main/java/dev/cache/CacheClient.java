package dev.cache;

/**
 * Thread-safe typed client. Does not retry ambiguous mutations. Keys are canonical Base64url bytes.
 */
public final class CacheClient {
    private final String endpoint;
    private final Wire wire;

    public CacheClient(String endpoint, String token) {
        this.endpoint = endpoint;
        wire = new Wire(token);
    }

    public Coordinator.Result execute(String operation, byte[] key, byte[] value, long ttlMillis, Long expectedVersion) {
        return wire.call(endpoint, "/api/v1/operation", new Coordinator.Request(operation, java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(key), value, ttlMillis, expectedVersion), Coordinator.Result.class);
    }

    /**
     * Ordered independent operations; never retry a partially successful batch wholesale.
     */
    public java.util.List<BatchController.Item> batch(java.util.List<Coordinator.Request> operations) {
        return java.util.List.of(wire.call(endpoint, "/api/v1/cache/batch",
                new BatchController.Batch(operations), BatchController.Item[].class));
    }
}
