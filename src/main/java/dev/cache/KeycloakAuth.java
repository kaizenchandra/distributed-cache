package dev.cache;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.oauth2.core.*;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.stereotype.Component;
import java.util.*;

/** Validates human/API tokens; internal RPC credentials are handled separately. */
@Component
@ConditionalOnProperty(name = "cache.auth-mode", havingValue = "keycloak")
public final class KeycloakAuth {
    private final JwtDecoder decoder;
    public KeycloakAuth(@Value("${cache.oidc.issuer}") String issuer,
                        @Value("${cache.oidc.jwk-set-uri}") String jwks,
                        @Value("${cache.oidc.audience:cache-api}") String audience) {
        var jwt = NimbusJwtDecoder.withJwkSetUri(jwks).build();
        jwt.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
            JwtValidators.createDefaultWithIssuer(issuer),
            token -> token.getAudience().contains(audience) && token.getExpiresAt() != null
                ? OAuth2TokenValidatorResult.success()
                : OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token", "Audience or expiry missing", null))));
        decoder = jwt;
    }
    int authorize(String authorization, String path) {
        if (authorization == null || !authorization.startsWith("Bearer ")) return 401;
        try {
            var jwt = decoder.decode(authorization.substring(7));
            Object access = jwt.getClaims().get("realm_access");
            Object roles = access instanceof Map<?, ?> map ? map.get("roles") : null;
            if (!(roles instanceof Collection<?> list)) return 403;
            boolean allowed = list.contains("cache-admin") || path.startsWith("/api/") && list.contains("cache-user");
            return allowed ? 200 : 403;
        } catch (JwtException | IllegalArgumentException e) { return 401; }
    }
}
