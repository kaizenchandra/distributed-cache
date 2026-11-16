# Keycloak authentication and authorization

Both Compose topologies include Keycloak and the Next.js console. This is a local development deployment: Keycloak uses
`start-dev`, HTTP, and its persistent development database. Use HTTPS and a supported external database before deploying
beyond localhost.

## Start

```sh
python3 scripts/init-auth.py
docker compose up --build -d
# Alternative, instead of the legacy stack:
# docker compose -f compose.consensus.yaml up --build -d
```

Open **http://localhost:3000** and sign in. Use localhost consistently (not 127.0.0.1), because the registered OIDC
redirect is `http://localhost:3000/api/auth/callback/keycloak`.

The setup script preserves existing secrets and appends random missing secrets to root `.env`. It creates
`frontend/.env.local` only when absent. If you previously created that file, add NEXTAUTH_URL, NEXTAUTH_SECRET,
KEYCLOAK_ISSUER, KEYCLOAK_CLIENT_ID and KEYCLOAK_CLIENT_SECRET from `.env.example`, using the generated secrets from
root `.env`. No secrets use the NEXT_PUBLIC_ prefix.

| Account                       | Password variable in root .env | Access                                        |
|-------------------------------|--------------------------------|-----------------------------------------------|
| cache-user                    | KEYCLOAK_USER_PASSWORD         | All cache operations and batches              |
| cache-admin                   | KEYCLOAK_ADMIN_PASSWORD        | Cache operations, topology, bootstrap, repair |
| admin (Keycloak console only) | KEYCLOAK_BOOTSTRAP_PASSWORD    | Identity administration                       |

The Keycloak admin console is **http://localhost:8180/admin**. Assign the `cache-user` or `cache-admin` realm role to
additional users in the `cache` realm. The bootstrap admin is not a cache application user.

Wait for Keycloak startup and realm import before logging in. On fresh legacy nodes, sign in as cache-admin and use
**Bootstrap / reconcile** in Cluster administration. Bootstrap refuses already initialized legacy nodes. Consensus
reconciles membership automatically; the same button requests reconciliation. Topology migration is legacy-only; repair
status is consensus-only. The UI labels these limits, and unsupported endpoints return backend errors.

## Authorization model

The frontend uses authorization code with PKCE/state and a confidential Keycloak client. NextAuth stores the access
token inside an encrypted HttpOnly session cookie and does not include it in the browser session JSON. The proxy checks
session expiry and required roles, then forwards the user's access token. Backend authorization remains authoritative:
RS256 signature, issuer, audience `cache-api`, expiry and realm roles are checked independently.

- `/api/**`: cache-user or cache-admin.
- `/admin/**` and metrics: cache-admin.
- `/internal/**`: only the separate CACHE_INTERNAL_TOKEN; human Keycloak tokens are rejected.
- `/actuator/health`: public for health probes; the frontend proxy still requires login.

In Keycloak mode static client/admin credentials cannot bypass JWT validation. Missing/invalid/expired tokens return
401; valid tokens without the role return 403. Cache roles permit access to all cache keys; this is not per-tenant
isolation. Browser hiding of admin controls is only a convenience; the proxy and backend enforce the same role rules.

Access tokens expire after five minutes. The console requires another login when they expire, rather than retaining
refresh tokens. Sign out removes the local application session; the Keycloak SSO session persists. In the container
deployment login explicitly prompts for credentials. Role changes take effect on newly issued tokens; already issued
JWTs remain valid until expiry.

Keycloak advertises `http://localhost:8180/realms/cache` as the issuer. Backend containers fetch signing keys from
`http://keycloak:8080/.../certs` while validating the public issuer. Frontend containers likewise use explicit internal
token/JWKS endpoints and the public authorization URL, with issuer validation retained. Never disable TLS verification
to solve issuer/address mismatches in a real deployment.

## Local frontend development

```sh
python3 scripts/init-auth.py
docker compose up -d keycloak node-a node-b node-c coordinator
cd frontend
npm ci
npm run dev
```

Use http://localhost:3000. Root `.env` and frontend `.env.local` must share NEXTAUTH_SECRET and KEYCLOAK_CLIENT_SECRET
values. If running Java outside Docker set CACHE_AUTH_MODE=keycloak and use the default local issuer/JWKS addresses in
application.properties.

## Persistence and compatibility

Realm imports run only if the realm does not exist. Editing the import JSON or changing password/client-secret
environment variables does not modify an existing realm. Update the realm through the Keycloak admin console, or
explicitly remove its development volume only if you intend to discard identity data. `docker compose down` preserves
the volume; `down -v` destroys all stack data.

The original native scripts and typed Java clients still support static-token mode. Native Java defaults to
`CACHE_AUTH_MODE=token`. Compose defaults to Keycloak; to run legacy token-based Compose scripts set CACHE_AUTH_MODE=
token explicitly and run init-auth.py first (the Compose auth services still require their configuration). The frontend
always requires Keycloak; token-mode backends are intended for existing non-browser tests. A Java client may also pass a
valid Keycloak access token as its bearer credential in Keycloak mode.

References: [Keycloak containers and realm import](https://www.keycloak.org/server/containers), [Keycloak hostname configuration](https://www.keycloak.org/server/hostname), [NextAuth session configuration](https://next-auth.js.org/configuration/options).

## Verification

```sh
mvn test
cd frontend && npm run build
# From project root, with either Compose stack running:
python3 scripts/auth-test.py
# Require consensus mode and its extra membership/cross-gateway checks:
python3 scripts/auth-test.py --mode consensus
```

The integration test logs in through the real authorization-code flow for both demo accounts, checks
anonymous/user/admin access, runs all seven cache operations plus batches, TTL expiration, CAS conflicts, Unicode, size
limits and negative authorization cases, and deletes its generated keys. In consensus mode it also checks membership,
reconciliation, repair status and cross-gateway visibility. It bootstraps only if legacy topology reports `ready=false`.
The test reads passwords from `.env` without printing them. Do not run it against shared production data.
