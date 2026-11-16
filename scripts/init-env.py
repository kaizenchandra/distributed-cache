#!/usr/bin/env python3
"""Create local Compose credentials without replacing existing configuration."""
import os
import secrets
from pathlib import Path


def main():
    path = Path(__file__).resolve().parents[1] / ".env"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"Keeping existing {path}")
        return
    with os.fdopen(fd, "w") as env:
        for role in ("CLIENT", "INTERNAL", "ADMIN"):
            env.write(f"CACHE_{role}_TOKEN={secrets.token_hex(32)}\n")
    print(f"Created {path} with random local credentials")


if __name__ == "__main__":
    main()
