package dev.cache;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;

/**
 * SHA-256 first signed big-endian 64 bits, UTF-8; collision buckets sorted by node ID.
 */
public final class Ring {
    private final NavigableMap<Long, SortedSet<String>> points = new TreeMap<>();
    private final List<String> nodes;

    public Ring(List<String> nodes, int virtualNodes) {
        if (nodes.isEmpty() || new HashSet<>(nodes).size() != nodes.size() || virtualNodes < 1 || virtualNodes > 4096)
            throw new IllegalArgumentException("invalid ring");
        this.nodes = List.copyOf(nodes);
        for (String n : nodes)
            for (int i = 0; i < virtualNodes; i++)
                points.computeIfAbsent(hash(n + "#" + i), k -> new TreeSet<>()).add(n);
    }

    public static long hash(String s) {
        try {
            return ByteBuffer.wrap(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8))).getLong();
        } catch (NoSuchAlgorithmException e) {
            throw new AssertionError(e);
        }
    }

    public List<String> owners(String key, int replicas) {
        LinkedHashSet<String> result = new LinkedHashSet<>();
        long h = hash(key);
        for (var part : List.of(points.tailMap(h, true), points.headMap(h, false)))
            for (var bucket : part.values())
                for (String n : bucket) {
                    result.add(n);
                    if (result.size() == Math.min(replicas, nodes.size())) return List.copyOf(result);
                }
        return List.copyOf(result);
    }

    public List<String> nodes() {
        return nodes;
    }
}
