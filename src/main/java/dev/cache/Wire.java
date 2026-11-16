package dev.cache;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

public final class Wire {
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
    private final ObjectMapper json = new ObjectMapper();
    private final String token;

    public Wire(String token) {
        this.token = token;
    }

    public <T> T call(String node, String path, Object body, Class<T> type) {
        try {
            var b = HttpRequest.newBuilder(URI.create(node + path)).timeout(Duration.ofSeconds(3)).header("Authorization", "Bearer " + token).header("Content-Type", "application/json");
            var r = client.send(body == null ? b.GET().build() : b.POST(HttpRequest.BodyPublishers.ofByteArray(json.writeValueAsBytes(body))).build(), HttpResponse.BodyHandlers.ofByteArray());
            if (r.statusCode() != 200) throw new IllegalStateException("peer status " + r.statusCode());
            return json.readValue(r.body(), type);
        } catch (Exception e) {
            throw new IllegalStateException("peer unavailable; mutation outcome may be ambiguous", e);
        }
    }
}
