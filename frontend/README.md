# Cache Lab

Next.js workbench for both cache modes, authenticated with Keycloak. See [authentication setup](../docs/authentication.md) for Compose startup, accounts, local development and role assignments.

```sh
# From project root:
python3 scripts/init-auth.py
docker compose up --build -d
```

Open http://localhost:3000. Cache users can run GET, SET, DELETE, EXISTS, TTL, EXPIRE, CAS and batches. Cache admins can also inspect topology, bootstrap/reconcile, inspect consensus repair and apply legacy topology changes.

Keys are UTF-8 encoded to unpadded Base64url; values use standard Base64. TTL is milliseconds: -1 permanent, 0 deletes immediately. CAS uses the version from GET; version 0 conditionally creates. Batch input uses plain text keys/values in a JSON array of 1–100 operations and defaults omitted TTL to -1. Batches are sequential and non-atomic: inspect individual statuses. A timeout does not establish that a mutation failed; read before retrying.

History keeps the last 50 requests in memory until reload/logout. Binary values remain visible as raw Base64. Tokens stay in encrypted HttpOnly session cookies; the proxy forwards the user's identity and enforces role checks. Access-token expiry requires login again.

```sh
npm ci
npm run typecheck
npm run build
npm run dev
```

Set `.env.local` as described in the setup guide. The development server binds to loopback. Container hosting binds inside the container with only localhost port publication.
