#!/usr/bin/env python3
"""Install pinned native test tools locally; no system changes or elevated privileges."""
import argparse
import hashlib
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = '3.6.5'
# Official GitHub v3.6.5 release asset SHA-256 digests.
DIGESTS = {
    'darwin-arm64': '14d7743f9ed07950a8e85491646e067e394a09e049e42083e2f6473fefa717a8',
    'darwin-amd64': 'ab1286184ea8f27a921730d494b7dea4f9a0d3b176e70ab48fcdf77448e1ac57',
    'linux-arm64': '7010161787077b07de29b15b76825ceacbbcedcb77fe2e6832f509be102cab6b',
    'linux-amd64': '66bad39ed920f6fc15fd74adcb8bfd38ba9a6412f8c7852d09eb11670e88cac3',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Use a previously downloaded official archive (checksum required)')
    args = parser.parse_args()
    system = platform.system().lower()
    machine = {'aarch64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine().lower(), platform.machine().lower())
    target = f'{system}-{machine}'
    if target not in DIGESTS:
        parser.error(f'unsupported platform: {target}; install etcd/etcdctl manually and set ETCD_BIN/ETCDCTL_BIN')
    name = f'etcd-v{VERSION}-{target}'
    destination = Path(__file__).resolve().parents[1] / '.tools' / name
    with tempfile.TemporaryDirectory(prefix='cache-etcd-install-') as temporary:
        temporary = Path(temporary)
        extension = '.zip' if system == 'darwin' else '.tar.gz'
        archive = args.archive or temporary / (name + extension)
        if not args.archive:
            url = f'https://github.com/etcd-io/etcd/releases/download/v{VERSION}/{name}{extension}'
            with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != DIGESTS[target]:
            raise SystemExit('archive SHA-256 mismatch; installation aborted')
        # Extract only the two executables, after validating the official archive digest.
        binaries = {}
        if system == 'darwin':
            with zipfile.ZipFile(archive) as bundle:
                for binary in ('etcd', 'etcdctl'):
                    binaries[binary] = bundle.read(f'{name}/{binary}')
        else:
            with tarfile.open(archive) as bundle:
                for binary in ('etcd', 'etcdctl'):
                    with bundle.extractfile(f'{name}/{binary}') as source:
                        binaries[binary] = source.read()
        destination.mkdir(parents=True, exist_ok=True)
        for binary, data in binaries.items():
            path = destination / binary
            path.write_bytes(data)
            path.chmod(0o755)
        subprocess.run([str(destination / 'etcd'), '--version'], check=True)
        subprocess.run([str(destination / 'etcdctl'), 'version'], check=True)
    print(f'Installed verified test tools at {destination}')
    print(f'export ETCD_BIN="{destination}/etcd"')


if __name__ == '__main__':
    main()
