package dev.cache;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;

/**
 * Minimal etcd v3 JSON gateway client. All reads are linearizable; no mutation retries.
 */
@Component
public final class Etcd {
    public final ObjectMapper json = new ObjectMapper();
    private final List<String> endpoints;
    private final HttpClient client;
    private final String username, password;
    private volatile int preferred;
    private volatile String token = "";

    public Etcd(String endpoints) {
        this(endpoints, new org.springframework.core.env.StandardEnvironment());
    }

    @org.springframework.beans.factory.annotation.Autowired
    public Etcd(@org.springframework.beans.factory.annotation.Value("${cache.etcd:http://localhost:2379}") String endpoints, org.springframework.core.env.Environment env) {
        this.endpoints = List.of(endpoints.split(","));
        var builder = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(500));
        boolean secure = env.getProperty("cache.etcd-security.enabled", Boolean.class, false);
        try {
            if (secure) {
                if (this.endpoints.stream().anyMatch(e -> !URI.create(e).getScheme().equals("https")))
                    throw new IllegalArgumentException("secure etcd requires HTTPS endpoints");
                String base = "cache.etcd-security.";
                var keys = java.security.KeyStore.getInstance("PKCS12");
                char[] keyPassword = secret(env, base + "key-password-file").toCharArray();
                try (var input = java.nio.file.Files.newInputStream(java.nio.file.Path.of(env.getRequiredProperty(base + "key-store")))) {
                    keys.load(input, keyPassword);
                }
                boolean identity = false;
                for (var aliases = keys.aliases(); aliases.hasMoreElements(); ) {
                    String alias = aliases.nextElement();
                    if (!keys.isKeyEntry(alias)) continue;
                    identity = true;
                    var certificate = (java.security.cert.X509Certificate) keys.getCertificate(alias);
                    for (var rdn : new javax.naming.ldap.LdapName(certificate.getSubjectX500Principal().getName()).getRdns())
                        if (rdn.getType().equalsIgnoreCase("CN"))
                            throw new IllegalArgumentException("etcd JSON gateway client certificate must have no Common Name");
                }
                if (!identity) throw new IllegalArgumentException("client private key missing");
                var trust = java.security.KeyStore.getInstance("PKCS12");
                char[] trustPassword = secret(env, base + "trust-password-file").toCharArray();
                try (var input = java.nio.file.Files.newInputStream(java.nio.file.Path.of(env.getRequiredProperty(base + "trust-store")))) {
                    trust.load(input, trustPassword);
                }
                var km = javax.net.ssl.KeyManagerFactory.getInstance(javax.net.ssl.KeyManagerFactory.getDefaultAlgorithm());
                km.init(keys, keyPassword);
                var tm = javax.net.ssl.TrustManagerFactory.getInstance(javax.net.ssl.TrustManagerFactory.getDefaultAlgorithm());
                tm.init(trust);
                var tls = javax.net.ssl.SSLContext.getInstance("TLS");
                tls.init(km.getKeyManagers(), tm.getTrustManagers(), null);
                builder.sslContext(tls);
                var parameters = new javax.net.ssl.SSLParameters();
                parameters.setProtocols(new String[]{"TLSv1.3", "TLSv1.2"});
                parameters.setEndpointIdentificationAlgorithm("HTTPS");
                builder.sslParameters(parameters);
                java.util.Arrays.fill(keyPassword, '\0');
                java.util.Arrays.fill(trustPassword, '\0');
                username = env.getRequiredProperty(base + "username");
                password = secret(env, base + "password-file");
                if (username.isBlank() || password.isEmpty())
                    throw new IllegalArgumentException("empty etcd credentials");
            } else {
                username = "";
                password = "";
            }
            client = builder.build();
        } catch (Exception e) {
            throw new IllegalArgumentException("invalid etcd TLS/auth configuration", e);
        }
    }

    private static String secret(org.springframework.core.env.Environment env, String property) throws java.io.IOException {
        String path = env.getRequiredProperty(property);
        return java.nio.file.Files.readString(java.nio.file.Path.of(path)).strip();
    }

    public static String b64(String s) {
        return Base64.getEncoder().encodeToString(s.getBytes(StandardCharsets.UTF_8));
    }

    private static String decode(String s) {
        return new String(Base64.getDecoder().decode(s), StandardCharsets.UTF_8);
    }

    private synchronized void authenticate(String endpoint) throws Exception {
        if (username.isEmpty() || !token.isEmpty()) return;
        var req = HttpRequest.newBuilder(URI.create(endpoint + "/v3/auth/authenticate")).timeout(Duration.ofMillis(1200)).header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofByteArray(json.writeValueAsBytes(Map.of("name", username, "password", password)))).build();
        var response = client.send(req, HttpResponse.BodyHandlers.ofByteArray());
        String next = json.readTree(response.body()).path("token").asText();
        if (response.statusCode() != 200 || next.isEmpty())
            throw new IllegalStateException("etcd authentication rejected");
        token = next;
    }

    public JsonNode request(String path, Object body, boolean read) {
        RuntimeException failure = null;
        for (int attempt = 0; attempt < endpoints.size(); attempt++)
            try {
                String endpoint = endpoints.get(Math.floorMod(preferred, endpoints.size()));
                authenticate(endpoint);
                HttpResponse<byte[]> response = null;
                for (int authAttempt = 0; authAttempt < 2; authAttempt++) {
                    var builder = HttpRequest.newBuilder(URI.create(endpoint + "/v3/" + path)).timeout(Duration.ofMillis(1200)).header("Content-Type", "application/json");
                    if (!token.isEmpty()) builder.header("Authorization", token);
                    response = client.send(builder.POST(HttpRequest.BodyPublishers.ofByteArray(json.writeValueAsBytes(body))).build(), HttpResponse.BodyHandlers.ofByteArray());
                    // Only explicit UNAUTHENTICATED rejection permits replay; never retry an ambiguous mutation.
                    JsonNode error = json.readTree(response.body());
                    if (!username.isEmpty() && error.path("code").asInt() == 16 && authAttempt == 0) {
                        token = "";
                        authenticate(endpoint);
                        continue;
                    }
                    break;
                }
                if (response.statusCode() != 200) throw new IllegalStateException("etcd HTTP " + response.statusCode());
                JsonNode result = json.readTree(response.body());
                if (result.has("error")) throw new IllegalStateException("etcd error");
                return result;
            } catch (Exception e) {
                preferred++;
                failure = new IllegalStateException("consensus unavailable or outcome ambiguous", e);
                if (!read) throw failure;
            }
        throw failure;
    }

    public Value get(String key) {
        var values = range(key, false);
        return values.isEmpty() ? new Value(key, "", 0) : values.getFirst();
    }

    public List<Value> range(String prefix, boolean all) {
        Map<String, Object> req = new HashMap<>();
        req.put("key", b64(prefix));
        if (all)
            req.put("range_end", b64(prefix.substring(0, prefix.length() - 1) + (char) (prefix.charAt(prefix.length() - 1) + 1)));
        List<Value> result = new ArrayList<>();
        for (JsonNode v : request("kv/range", req, true).path("kvs"))
            result.add(new Value(decode(v.path("key").asText()), decode(v.path("value").asText()), v.path("mod_revision").asLong()));
        return result;
    }

    public List<Value> page(String prefix, String after, int limit) {
        Map<String, Object> req = new HashMap<>();
        req.put("key", b64(after.isEmpty() ? prefix : after + "\0"));
        req.put("range_end", b64(prefix.substring(0, prefix.length() - 1) + (char) (prefix.charAt(prefix.length() - 1) + 1)));
        req.put("limit", limit);
        List<Value> result = new ArrayList<>();
        for (JsonNode v : request("kv/range", req, true).path("kvs"))
            result.add(new Value(decode(v.path("key").asText()), decode(v.path("value").asText()), v.path("mod_revision").asLong()));
        return result;
    }

    public boolean publish(String key, long revision, Object value, List<Map<String, Object>> guards, String countKey, int maximum) {
        if (revision != 0) return cas(key, revision, value, guards);
        for (int attempt = 0; attempt < 8; attempt++) {
            Value count = get(countKey);
            long total = count.revision() == 0 ? 0 : Long.parseLong(count.value());
            if (total >= maximum)
                throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.INSUFFICIENT_STORAGE, "metadata capacity exhausted");
            try {
                var compares = new ArrayList<>(guards);
                compares.add(compare(key, 0));
                compares.add(compare(countKey, count.revision()));
                var puts = List.of(Map.of("request_put", Map.of("key", b64(key), "value", b64(json.writeValueAsString(value)))), Map.of("request_put", Map.of("key", b64(countKey), "value", b64(Long.toString(total + 1)))));
                if (request("kv/txn", Map.of("compare", compares, "success", puts), false).path("succeeded").asBoolean())
                    return true;
                if (get(key).revision() != 0) return false;
            } catch (java.io.IOException e) {
                throw new IllegalStateException(e);
            }
        }
        return false;
    }

    public boolean claim(String key, String identity) {
        Value current = get(key);
        if (current.revision() != 0 && !current.value().equals(identity)) return false;
        long lease = request("lease/grant", Map.of("TTL", "5"), false).path("ID").asLong();
        return request("kv/txn", Map.of("compare", List.of(compare(key, current.revision())), "success", List.of(Map.of("request_put", Map.of("key", b64(key), "value", b64(identity), "lease", Long.toString(lease))))), false).path("succeeded").asBoolean();
    }

    public Map<String, Object> compare(String key, long revision) {
        return Map.of("key", b64(key), "target", "MOD", "result", "EQUAL", "mod_revision", Long.toString(revision));
    }

    public boolean cas(String key, long revision, Object value, List<Map<String, Object>> guards) {
        try {
            List<Map<String, Object>> compares = new ArrayList<>(guards);
            compares.add(compare(key, revision));
            return request("kv/txn", Map.of("compare", compares, "success", List.of(Map.of("request_put", Map.of("key", b64(key), "value", b64(json.writeValueAsString(value))))), "failure", List.of()), false).path("succeeded").asBoolean();
        } catch (java.io.IOException e) {
            throw new IllegalStateException(e);
        }
    }

    public void register(String key, Object value) {
        try {
            long lease = request("lease/grant", Map.of("TTL", "5"), false).path("ID").asLong();
            request("kv/put", Map.of("key", b64(key), "value", b64(json.writeValueAsString(value)), "lease", Long.toString(lease)), false);
        } catch (java.io.IOException e) {
            throw new IllegalStateException(e);
        }
    }

    public <T> T parse(Value v, Class<T> type) {
        try {
            return json.readValue(v.value(), type);
        } catch (Exception e) {
            throw new IllegalStateException("invalid consensus metadata", e);
        }
    }

    public record Value(String key, String value, long revision) {
    }
}
