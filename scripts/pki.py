#!/usr/bin/env python3
"""Generate short-lived LOCAL TEST certificates and PKCS12 stores. Not a production CA."""
import os
import secrets
import subprocess
from pathlib import Path


def generate(directory):
    p = Path(directory);
    p.mkdir(parents=True, exist_ok=True)

    def run(*args):
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    (p / 'store-password').write_text(secrets.token_urlsafe(24))
    (p / 'cache-password').write_text(secrets.token_urlsafe(24))
    (p / 'root-password').write_text(secrets.token_urlsafe(24))
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(p / 'ca.key'), '-out',
        str(p / 'ca.crt'), '-days', '2', '-subj', '/CN=Cache Local Test CA', '-addext',
        'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-addext',
        'subjectKeyIdentifier=hash')
    for name, cn, ext in [('server', 'etcd-server',
                           'subjectAltName=IP:127.0.0.1,DNS:localhost,DNS:etcd-0,DNS:etcd-1,DNS:etcd-2\nextendedKeyUsage=serverAuth,clientAuth\n'),
                          ('client', 'transport-client', 'extendedKeyUsage=clientAuth\n')]:
        (p / (name + '.ext')).write_text(
            ext + 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
        run('openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(p / (name + '.key')), '-out',
            str(p / (name + '.csr')), '-subj', '/O=cache-transport' if name == 'client' else '/CN=' + cn)
        run('openssl', 'x509', '-req', '-in', str(p / (name + '.csr')), '-CA', str(p / 'ca.crt'), '-CAkey',
            str(p / 'ca.key'), '-CAcreateserial', '-out', str(p / (name + '.crt')), '-days', '2', '-extfile',
            str(p / (name + '.ext')))
    run('openssl', 'pkcs12', '-export', '-inkey', str(p / 'client.key'), '-in', str(p / 'client.crt'), '-certfile',
        str(p / 'ca.crt'), '-name', 'cache', '-out', str(p / 'client.p12'), '-passout',
        'file:' + str(p / 'store-password'))
    run('keytool', '-importcert', '-noprompt', '-alias', 'cache-ca', '-file', str(p / 'ca.crt'), '-keystore',
        str(p / 'trust.p12'), '-storetype', 'PKCS12', '-storepass:file', str(p / 'store-password'))
    for f in p.iterdir(): f.chmod(0o600)
    return p


if __name__ == '__main__':
    import sys

    generate(sys.argv[1])
