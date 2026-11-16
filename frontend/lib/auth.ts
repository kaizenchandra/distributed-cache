import type { NextAuthOptions } from 'next-auth';
import KeycloakProvider from 'next-auth/providers/keycloak';
export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: 'jwt', maxAge: 8 * 60 * 60 },
  providers: [KeycloakProvider({
    clientId: process.env.KEYCLOAK_CLIENT_ID || 'cache-console',
    clientSecret: process.env.KEYCLOAK_CLIENT_SECRET || '',
    issuer: process.env.KEYCLOAK_ISSUER || 'http://localhost:8180/realms/cache',
    checks: ['pkce', 'state'],
    // Explicit endpoints allow browser-facing issuer and container-only back channel.
    ...(process.env.KEYCLOAK_INTERNAL_URL ? {
      wellKnown: undefined,
      authorization: { url: `${process.env.KEYCLOAK_ISSUER}/protocol/openid-connect/auth`, params: { scope: 'openid profile email', prompt: 'login' } },
      token: `${process.env.KEYCLOAK_INTERNAL_URL}/protocol/openid-connect/token`,
      userinfo: `${process.env.KEYCLOAK_INTERNAL_URL}/protocol/openid-connect/userinfo`,
      jwks_endpoint: `${process.env.KEYCLOAK_INTERNAL_URL}/protocol/openid-connect/certs`,
    } : {}),
  })],
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        token.accessToken = account.access_token;
        token.accessExpires = account.expires_at;
        // Claims come only from the provider token received via validated OIDC login.
        const claims = JSON.parse(Buffer.from(account.access_token!.split('.')[1], 'base64url').toString());
        token.roles = Array.isArray(claims.realm_access?.roles) ? claims.realm_access.roles : [];
      }
      return token;
    },
    async session({ session, token }) {
      // Never expose access/refresh tokens to the session endpoint or client JavaScript.
      session.roles = token.roles || [];
      session.expired = !token.accessExpires || Date.now() >= token.accessExpires * 1000;
      return session;
    },
  },
};
