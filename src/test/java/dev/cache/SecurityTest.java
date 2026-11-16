package dev.cache;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.net.InetSocketAddress;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SecurityTest {
    static HttpServer server;
    static RSAKey key;
    static KeycloakAuth auth;

    @BeforeAll
    static void setup() throws Exception {
        key = new RSAKeyGenerator(2048).keyID("test").generate();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/jwks", exchange -> {
            byte[] body = new JWKSet(key.toPublicJWK()).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            try (var out = exchange.getResponseBody()) {
                out.write(body);
            }
        });
        server.start();
        auth = new KeycloakAuth("https://issuer.example/realms/cache", "http://127.0.0.1:" + server.getAddress().getPort() + "/jwks", "cache-api");
    }

    @AfterAll
    static void stop() {
        if (server != null) server.stop(0);
    }

    static String token(String issuer, String audience, String role, long seconds, RSAKey signingKey) throws Exception {
        var claims = new JWTClaimsSet.Builder().issuer(issuer).audience(audience).subject("test-user")
                .issueTime(new Date()).expirationTime(Date.from(Instant.now().plusSeconds(seconds)))
                .claim("realm_access", Map.of("roles", List.of(role))).build();
        var jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("test").build(), claims);
        jwt.sign(new RSASSASigner(signingKey));
        return "Bearer " + jwt.serialize();
    }

    static String token(String role) throws Exception {
        return token("https://issuer.example/realms/cache", "cache-api", role, 300, key);
    }

    @Test
    void rolesAndMalformedTokens() throws Exception {
        assertEquals(401, auth.authorize(null, "/api/v1/operation"));
        assertEquals(401, auth.authorize("Bearer malformed", "/api/v1/operation"));
        assertEquals(200, auth.authorize(token("cache-user"), "/api/v1/operation"));
        assertEquals(200, auth.authorize(token("cache-user"), "/api/v1/cache/batch"));
        assertEquals(403, auth.authorize(token("cache-user"), "/admin/topology"));
        assertEquals(200, auth.authorize(token("cache-admin"), "/admin/bootstrap"));
        assertEquals(200, auth.authorize(token("cache-admin"), "/api/v1/operation"));
        assertEquals(403, auth.authorize(token("other"), "/api/v1/operation"));
    }

    @Test
    void validatesSignatureIssuerAudienceAndExpiry() throws Exception {
        assertEquals(401, auth.authorize(token("https://evil.example", "cache-api", "cache-admin", 300, key), "/api/v1/operation"));
        assertEquals(401, auth.authorize(token("https://issuer.example/realms/cache", "other-api", "cache-admin", 300, key), "/api/v1/operation"));
        assertEquals(401, auth.authorize(token("https://issuer.example/realms/cache", "cache-api", "cache-admin", -300, key), "/api/v1/operation"));
        assertEquals(401, auth.authorize(token("https://issuer.example/realms/cache", "cache-api", "cache-admin", 300, new RSAKeyGenerator(2048).generate()), "/api/v1/operation"));
    }

    Security filter(boolean oidc) {
        var factory = new StaticListableBeanFactory();
        if (oidc) factory.addBean("auth", auth);
        return new Security("client-token-123456789", "internal-token-123456", "admin-token-123456789", factory.getBeanProvider(KeycloakAuth.class), oidc ? "keycloak" : "token");
    }

    int request(Security security, String path, String token, String body) throws Exception {
        var req = new MockHttpServletRequest(body == null ? "GET" : "POST", path);
        if (token != null) req.addHeader("Authorization", token);
        if (body != null) req.setContent(body.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        var res = new MockHttpServletResponse();
        security.doFilter(req, res, (r, s) -> ((jakarta.servlet.http.HttpServletResponse) s).setStatus(204));
        return res.getStatus();
    }

    @Test
    void separatesInternalCredentialsAndRejectsStaticBypass() throws Exception {
        var filter = filter(true);
        assertEquals(204, request(filter, "/actuator/health", null, null));
        assertEquals(401, request(filter, "/api/v1/operation", "Bearer client-token-123456789", "{}"));
        assertEquals(401, request(filter, "/admin/topology", "Bearer admin-token-123456789", null));
        assertEquals(401, request(filter, "/internal/stats", token("cache-admin"), null));
        assertEquals(204, request(filter, "/internal/stats", "Bearer internal-token-123456", null));
        assertEquals(413, request(filter, "/api/v1/operation", token("cache-user"), "x".repeat(100001)));
        assertEquals(403, request(filter, "/admin/bootstrap", token("cache-user"), "{}"));
        assertEquals(204, request(filter(false), "/api/v1/operation", "Bearer client-token-123456789", "{}"));
    }
}
