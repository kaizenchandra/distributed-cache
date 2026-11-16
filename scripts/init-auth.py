#!/usr/bin/env python3
"""Append missing local OIDC secrets; preserve existing cache/auth credentials."""
import os
import secrets
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run(['python3', str(root / 'scripts/init-env.py')], check=True)
path = root / '.env'
existing = dict(
    line.split('=', 1) for line in path.read_text().splitlines() if '=' in line and not line.startswith('#'))
with path.open('a') as file:
    file.write('\n')
    for key in ('NEXTAUTH_SECRET', 'KEYCLOAK_CLIENT_SECRET', 'KEYCLOAK_BOOTSTRAP_PASSWORD', 'KEYCLOAK_USER_PASSWORD',
                'KEYCLOAK_ADMIN_PASSWORD'):
        if key not in existing:
            existing[key] = secrets.token_hex(32)
            file.write(f'{key}={existing[key]}\n')
os.chmod(path, 0o600)
frontend = root / 'frontend/.env.local'
if not frontend.exists():
    fd = os.open(frontend, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(
            'CACHE_API_URL=http://localhost:8080\nNEXTAUTH_URL=http://localhost:3000\nKEYCLOAK_ISSUER=http://localhost:8180/realms/cache\nKEYCLOAK_CLIENT_ID=cache-console\n')
        for key in ('NEXTAUTH_SECRET', 'KEYCLOAK_CLIENT_SECRET'):
            file.write(f'{key}={existing[key]}\n')
print(
    'Auth secrets ready in .env (passwords are not printed). Existing frontend/.env.local is preserved; see docs/authentication.md.')
