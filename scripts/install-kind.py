#!/usr/bin/env python3
"""Install checksum-pinned kind locally without changing system tools or kubeconfig."""
import argparse
import hashlib
import platform
import subprocess
import urllib.request
from pathlib import Path

VERSION = '0.33.0'
DIGESTS = {
    'darwin-amd64': '5a99f26f57246dc9319dd294803313197a0f34d33c525b3ea8b655db5916ece0',
    'darwin-arm64': '0c8c7dbe5e23594a198b786c4bc13dacc101fa6196b0cb0b23a1ca44e61f4b4f',
    'linux-amd64': 'aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d',
    'linux-arm64': '20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2',
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, help='Verify and install an already downloaded official binary')
    a = p.parse_args()
    machine = platform.machine().lower()
    target = platform.system().lower() + '-' + {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(machine, machine)
    if target not in DIGESTS: p.error('unsupported platform; install kind manually')
    if a.binary:
        data = a.binary.read_bytes()
    else:
        with urllib.request.urlopen(
                f'https://github.com/kubernetes-sigs/kind/releases/download/v{VERSION}/kind-{target}',
                timeout=60) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != DIGESTS[target]: raise SystemExit(
        'kind SHA-256 mismatch; installation aborted')
    destination = Path(__file__).resolve().parents[1] / '.tools' / 'kind'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    destination.chmod(0o755)
    subprocess.run([str(destination), 'version'], check=True)
    print(f'Installed verified kind at {destination}; no cluster or context was changed')


if __name__ == '__main__': main()
