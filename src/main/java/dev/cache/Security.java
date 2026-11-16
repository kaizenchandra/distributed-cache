package dev.cache;

import jakarta.servlet.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Component
public class Security implements Filter {
    private final String client, internal, admin;
    private final KeycloakAuth keycloak;

    public Security(@Value("${cache.client-token}") String c, @Value("${cache.internal-token}") String i, @Value("${cache.admin-token}") String a, org.springframework.beans.factory.ObjectProvider<KeycloakAuth> auth, @Value("${cache.auth-mode:token}") String mode) {
        if (!java.util.Set.of("token", "keycloak").contains(mode))
            throw new IllegalArgumentException("cache.auth-mode must be token or keycloak");
        keycloak = auth.getIfAvailable();
        if (mode.equals("keycloak") && keycloak == null)
            throw new IllegalArgumentException("Keycloak validator required");
        client = c;
        internal = i;
        admin = a;
        if (c.length() < 16 || i.length() < 16 || a.length() < 16 || c.equals(i) || c.equals(a) || a.equals(i))
            throw new IllegalArgumentException("three distinct tokens of at least 16 characters required");
    }

    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain) throws IOException, ServletException {
        HttpServletRequest r = (HttpServletRequest) request;
        HttpServletResponse s = (HttpServletResponse) response;
        if (r.getRequestURI().equals("/actuator/health")) {
            chain.doFilter(r, s);
            return;
        }
        String expected = r.getRequestURI().startsWith("/internal/") ? internal : r.getRequestURI().startsWith("/api/") ? client : admin;
        String supplied = r.getHeader("Authorization");
        if (keycloak != null && !r.getRequestURI().startsWith("/internal/")) {
            int status = keycloak.authorize(supplied, r.getRequestURI());
            if (status != 200) {
                s.sendError(status);
                return;
            }
        } else if (supplied == null || !MessageDigest.isEqual(("Bearer " + expected).getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8))) {
            s.sendError(401);
            return;
        }
        if (r.getContentLengthLong() > 100000) {
            s.sendError(413);
            return;
        }
        // Also enforce the bound for chunked bodies before JSON allocation.
        if (!r.getMethod().equals("GET")) {
            byte[] body = r.getInputStream().readNBytes(100001);
            if (body.length > 100000) {
                s.sendError(413);
                return;
            }
            HttpServletRequestWrapper wrapper = new HttpServletRequestWrapper(r) {
                public ServletInputStream getInputStream() {
                    var input = new java.io.ByteArrayInputStream(body);
                    return new ServletInputStream() {
                        public int read() {
                            return input.read();
                        }

                        public boolean isFinished() {
                            return input.available() == 0;
                        }

                        public boolean isReady() {
                            return true;
                        }

                        public void setReadListener(ReadListener l) {
                            throw new UnsupportedOperationException();
                        }
                    };
                }
            };
            chain.doFilter(wrapper, s);
        } else chain.doFilter(r, s);
    }
}
