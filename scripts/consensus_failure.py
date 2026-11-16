#!/usr/bin/env python3
"""Real 3-etcd + 4-storage + 2-gateway failure suite. Requires ETCD_BIN and loopback sockets.
Transport proxy cuts etcd access for one gateway without changing its data-plane access.
"""
import base64
import concurrent.futures
import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
etcd_bin = shutil.which(os.environ.get('ETCD_BIN', 'etcd'))
if not etcd_bin:
    raise SystemExit('etcd not found: run python3 scripts/install-etcd.py and export ETCD_BIN as printed')
etcdctl_bin = shutil.which(os.environ.get('ETCDCTL_BIN', str(Path(etcd_bin).with_name('etcdctl'))))
if not etcdctl_bin:
    raise SystemExit('etcdctl not found: install it alongside etcd or set ETCDCTL_BIN')
if not (root / 'target/distributed-cache-0.1.0.jar').is_file():
    raise SystemExit('packaged jar not found: run mvn clean verify first')
secure = os.environ.get('CACHE_SECURE_TEST') == '1'
root_token = '';
tls_context = None;
cert_directory = None;
certs = None
scheme = 'https' if secure else 'http'
if secure:
    from pki import generate

    cert_directory = tempfile.TemporaryDirectory(prefix='cache-test-pki-');
    certs = generate(cert_directory.name)
    tls_context = ssl.create_default_context(cafile=str(certs / 'ca.crt'));
    tls_context.load_cert_chain(str(certs / 'client.crt'), str(certs / 'client.key'))
env = dict(os.environ, CACHE_CLIENT_TOKEN='client-test-token-123', CACHE_INTERNAL_TOKEN='internal-test-token-123',
           CACHE_ADMIN_TOKEN='admin-test-token-123')
processes = [];
logs = [];
blocked = False;
hold_publication = False
publication_waiting = threading.Event();
release_publication = threading.Event();
publication_rejected = threading.Event()


def request_json(url, body=None, token=None, timeout=4, context=None):
    headers = {'Content-Type': 'application/json'}
    if url.startswith('https:') and token is None: token = root_token
    if token: headers['Authorization'] = token if url.startswith('https:') else 'Bearer ' + token
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout,
                                context=context if context is not None else tls_context if url.startswith(
                                    'https:') else None) as response:
        return json.load(response)


def b64(s): return base64.b64encode(s.encode()).decode()


def eventually(action, seconds=35):
    end = time.monotonic() + seconds;
    last = None
    while time.monotonic() < end:
        try:
            result = action()
            if result: return result
        except Exception as e:
            last = e
        time.sleep(.3)
    raise AssertionError(f'condition timed out: {last}')


def launch(args, label):
    log = open(root / f'target/consensus-{label}.log', 'w');
    logs.append(log)
    proc = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT);
    processes.append(proc);
    return proc


class Proxy(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        global hold_publication
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        delayed = False
        if self.path == '/v3/kv/txn' and hold_publication:
            transaction = json.loads(body)
            if any('/keys/' in base64.b64decode(step.get('request_put', {}).get('key', '')).decode() for step in
                   transaction.get('success', [])):
                hold_publication = False;
                delayed = True;
                publication_waiting.set();
                release_publication.wait(20)
        if blocked: self.send_error(503);return
        for port in (33379, 33381, 33383):
            try:
                req = urllib.request.Request(f'{scheme}://127.0.0.1:{port}' + self.path, data=body,
                                             headers={'Content-Type': 'application/json', **(
                                                 {'Authorization': self.headers['Authorization']} if self.headers.get(
                                                     'Authorization') else {})})
                with urllib.request.urlopen(req, timeout=1.5, context=tls_context) as r:
                    content = r.read()
                if delayed and not json.loads(content).get('succeeded', False): publication_rejected.set()
                try:
                    self.send_response(200);
                    self.end_headers();
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            except Exception:
                pass
        self.send_error(503)

    def log_message(self, *args):
        pass


# Fail before testing if another application owns any test port.
for test_port in [33379, 33380, 33381, 33382, 33383, 33384, 33400, 31080, 31081, 31082, 31091, 31092, 31093, 31094]:
    with socket.socket() as probe:
        # Reuse closed connections from the preceding suite, while refusing live listeners.
        if probe.connect_ex(('127.0.0.1', test_port)) == 0:
            raise SystemExit(f'test port {test_port} already has a listener')
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', test_port))
proxy = http.server.ThreadingHTTPServer(('127.0.0.1', 33400), Proxy)
if secure:
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);
    server_context.load_cert_chain(str(certs / 'server.crt'), str(certs / 'server.key'));
    server_context.load_verify_locations(str(certs / 'ca.crt'));
    server_context.verify_mode = ssl.CERT_REQUIRED
    proxy.socket = server_context.wrap_socket(proxy.socket, server_side=True)
threading.Thread(target=proxy.serve_forever, daemon=True).start()
endpoints = ','.join(f'{scheme}://127.0.0.1:{p}' for p in (33379, 33381, 33383))


def java(port, gateway=False, isolatable=False, bad_password=False):
    args = ['java', '-Xmx128m', '-jar', str(root / 'target/distributed-cache-0.1.0.jar'), f'--server.port={port}',
            '--cache.mode=consensus', f'--cache.coordinator={str(gateway).lower()}',
            f'--cache.node-url=http://127.0.0.1:{port}', '--cache.namespace=failure-test',
            '--cache.metadata-max-entries=64',
            '--cache.etcd=' + (f'{scheme}://127.0.0.1:33400' if isolatable else endpoints)]
    if secure: args += ['--cache.etcd-security.enabled=true', '--cache.etcd-security.username=cache',
                        f'--cache.etcd-security.password-file={certs}/' + (
                            'wrong-password' if bad_password else 'cache-password'),
                        f'--cache.etcd-security.key-store={certs}/client.p12',
                        f'--cache.etcd-security.key-password-file={certs}/store-password',
                        f'--cache.etcd-security.trust-store={certs}/trust.p12',
                        f'--cache.etcd-security.trust-password-file={certs}/store-password']
    return launch(args, str(port))


def api(port, path, body=None, role='CLIENT'):
    return request_json(f'http://127.0.0.1:{port}' + path, body, env['CACHE_' + role + '_TOKEN'])


def op(port, kind, key='key0', value='dmFsdWU=', version=None):
    return api(port, '/api/v1/operation',
               dict(operation=kind, key=key, value=value, ttlMillis=-1, expectedVersion=version))


def etcd(path, body):
    global root_token
    last = None
    for port in (33379, 33381, 33383):
        try:
            return request_json(f'{scheme}://127.0.0.1:{port}/v3/' + path, body, timeout=2)
        except urllib.error.HTTPError as e:
            detail = e.read().decode();
            last = str(e) + " " + detail
            if secure and path != 'auth/authenticate' and json.loads(detail).get('code') == 16:
                root_token = request_json(f'{scheme}://127.0.0.1:{port}/v3/auth/authenticate',
                                          {'name': 'root', 'password': root_password}, token='')['token']
                return request_json(f'{scheme}://127.0.0.1:{port}/v3/' + path, body, timeout=2)
        except Exception as e:
            last = e
    raise AssertionError(f'etcd unavailable: {last}')


def metadata():
    values = etcd('kv/range',
                  {'key': b64('/cache/failure-test/keys/'), 'range_end': b64('/cache/failure-test/keys0')}).get('kvs',
                                                                                                                [])
    return [json.loads(base64.b64decode(v['value'])) for v in values]


def manifest(key): return next(m for m in metadata() if m['key'] == key)


def all_repaired(key):
    m = manifest(key);
    t = api(31081, '/admin/topology', role='ADMIN')['topology']['members']
    if len(m['owners']) != min(3, len(t)) or any(o not in t for o in m['owners']): return False
    for owner in m['owners']:
        r = request_json(owner['url'] + '/internal/consensus/fetch',
                         {'incarnation': owner['incarnation'], 'payload': m['payload']}, env['CACHE_INTERNAL_TOKEN'])
        if not r or r['version'] != m['version']: return False
    return True


try:
    with tempfile.TemporaryDirectory(prefix='cache-etcd-') as directory:
        cluster = ','.join(f'e{i}={scheme}://127.0.0.1:{33380 + 2 * i}' for i in range(3))
        etcds = []
        for i in range(3):
            client = 33379 + 2 * i;
            peer = client + 1
            etcds.append(launch(
                [etcd_bin, '--name', f'e{i}', '--data-dir', directory + f'/e{i}', '--listen-client-urls',
                 f'{scheme}://127.0.0.1:{client}', '--advertise-client-urls', f'{scheme}://127.0.0.1:{client}',
                 '--listen-peer-urls', f'{scheme}://127.0.0.1:{peer}', '--initial-advertise-peer-urls',
                 f'{scheme}://127.0.0.1:{peer}', '--initial-cluster', cluster, '--initial-cluster-token',
                 'cache-failure-tests'] + (
                    ['--cert-file', str(certs / 'server.crt'), '--key-file', str(certs / 'server.key'),
                     '--trusted-ca-file', str(certs / 'ca.crt'), '--client-cert-auth', '--auth-token-ttl=5',
                     '--tls-min-version=TLS1.2', '--peer-cert-file', str(certs / 'server.crt'), '--peer-key-file',
                     str(certs / 'server.key'), '--peer-trusted-ca-file', str(certs / 'ca.crt'),
                     '--peer-client-cert-auth'] if secure else []), f'etcd{i}'))
        eventually(lambda: etcd('kv/range', {'key': b64('health')}))
        if secure:
            root_password = (certs / 'root-password').read_text();
            cache_password = (certs / 'cache-password').read_text()
            etcd('auth/user/add', {'name': 'root', 'password': root_password});
            etcd('auth/user/grant', {'user': 'root', 'role': 'root'})
            etcd('auth/role/add', {'name': 'cache-role'})
            etcd('auth/role/grant', {'name': 'cache-role',
                                     'perm': {'permType': 'READWRITE', 'key': b64('/cache/failure-test/'),
                                              'range_end': b64('/cache/failure-test0')}})
            etcd('auth/user/add', {'name': 'cache', 'password': cache_password});
            etcd('auth/user/grant', {'user': 'cache', 'role': 'cache-role'});
            etcd('auth/enable', {})
            root_token = etcd('auth/authenticate', {'name': 'root', 'password': root_password})['token']
            untrusted = ssl.create_default_context();
            untrusted.load_cert_chain(str(certs / 'client.crt'), str(certs / 'client.key'))
            for context in [ssl.create_default_context(cafile=str(certs / 'ca.crt')), untrusted]:
                try:
                    request_json('https://127.0.0.1:33379/v3/kv/range', {'key': b64('negative')},
                                 context=context);
                    raise AssertionError('invalid TLS identity trusted')
                except (urllib.error.URLError, ssl.SSLError, ConnectionError):
                    pass
            for path, body in [('kv/range', {'key': b64('/cache/failure-test/topology')}),
                               ('auth/authenticate', {'name': 'cache', 'password': 'incorrect'})]:
                try:
                    request_json('https://127.0.0.1:33379/v3/' + path, body, token='');
                    raise AssertionError(
                        'unauthenticated request accepted')
                except urllib.error.HTTPError as e:
                    assert e.code in (400, 401, 403)
            cache_token = etcd('auth/authenticate', {'name': 'cache', 'password': cache_password})['token']
            try:
                request_json('https://127.0.0.1:33379/v3/kv/put',
                             {'key': b64('/outside-namespace'), 'value': b64('bad')},
                             token=cache_token);
                raise AssertionError('namespace escape accepted')
            except urllib.error.HTTPError as e:
                assert e.code in (401, 403)
            print(
                'PASS mTLS rejects missing certificate/untrusted CA; auth rejects absent/wrong credentials and namespace escape',
                flush=True)
            (certs / 'wrong-password').write_text('wrong-credential');
            (certs / 'wrong-password').chmod(0o600)
            bad_gateway = java(31082, True, bad_password=True)
            eventually(lambda: request_json('http://127.0.0.1:31082/actuator/health').get('status') == 'UP')
            try:
                op(31082, 'SET', 'must-not-publish');
                raise AssertionError(
                    'Java gateway accepted invalid etcd credentials')
            except urllib.error.HTTPError as e:
                assert e.code == 503
            bad_gateway.terminate();
            bad_gateway.wait(timeout=15)
            print('PASS Java gateway fails closed with incorrect etcd credentials', flush=True)
        nodes = {p: java(p) for p in range(31091, 31095)}
        gateways = {31080: java(31080, True, True), 31081: java(31081, True)}
        for port in list(nodes) + list(gateways): eventually(
            lambda p=port: request_json(f'http://127.0.0.1:{p}/actuator/health').get('status') == 'UP')
        eventually(lambda: len(api(31081, '/admin/topology', role='ADMIN')['topology']['members']) == 4)
        assert all(p.poll() is None for p in
                   etcds + list(nodes.values()) + list(gateways.values())), 'a test process exited during startup'
        assert all(
            request_json(f'{scheme}://127.0.0.1:{33379 + 2 * i}/version')['etcdserver'].startswith('3.6.') for i in
            range(3))
        batch = api(31080, '/api/v1/cache/batch', {'operations': [
            dict(operation='SET', key='batch-key', value='dmFsdWU=', ttlMillis=-1),
            dict(operation='CAS', key='batch-key', value='dmFsdWU=', ttlMillis=-1, expectedVersion=0),
            dict(operation='GET', key='batch-key', ttlMillis=-1)]})
        assert [item['status'] for item in batch] == [200, 409, 200]
        assert batch[2]['result']['value'] == 'dmFsdWU='
        assert op(31081, 'GET', 'batch-key')['found']
        api(31080, '/api/v1/operation', dict(operation='SET', key='ttl-key', value='dmFsdWU=', ttlMillis=150))
        time.sleep(.2)
        assert not op(31081, 'GET', 'ttl-key')['found']
        op(31081, 'DELETE', 'batch-key')
        assert not op(31080, 'GET', 'batch-key')['found']
        print('PASS consensus batch partial success, cross-gateway TTL and deletion', flush=True)
        first = op(31080, 'SET');
        assert op(31081, 'GET')['value'] == 'dmFsdWU='


        def cas(i):
            try:
                op(31080 + i % 2, 'CAS', version=first['version']);
                return 1
            except urllib.error.HTTPError as e:
                assert e.code == 409;
                return 0


        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            assert sum(pool.map(cas, range(16))) == 1
        print('PASS cross-gateway CAS and committed reads', flush=True)
        old_topology = api(31081, '/admin/topology', role='ADMIN');
        old = manifest('key0');
        primary = old['owners'][0];
        primary_port = int(primary['url'].rsplit(':', 1)[1])
        hold_publication = True


        def inflight():
            try:
                op(31080, 'SET', 'inflight');
                return 200
            except urllib.error.HTTPError as e:
                return e.code


        worker = concurrent.futures.ThreadPoolExecutor(1);
        pending = worker.submit(inflight)
        assert publication_waiting.wait(10), 'publication did not reach delay gate'
        nodes[primary_port].kill();
        nodes[primary_port].wait()
        eventually(lambda: len(api(31081, '/admin/topology', role='ADMIN')['topology']['members']) == 3)
        release_publication.set();
        assert pending.result(timeout=10) in (409, 503);
        worker.shutdown()
        assert publication_rejected.wait(10), 'late publication was not rejected'
        assert not op(31081, 'GET', 'inflight')['found']
        assert op(31081, 'GET')['found'];
        eventually(lambda: all_repaired('key0'))
        print('PASS primary crash, automatic ownership change and repair to spare', flush=True)
        # Restart same URL empty: incarnation must change and copies must be reconstructed.
        nodes[primary_port] = java(primary_port)
        eventually(lambda: request_json(primary['url'] + '/actuator/health').get('status') == 'UP')
        eventually(lambda: len(api(31081, '/admin/topology', role='ADMIN')['topology']['members']) == 4)
        eventually(lambda: all_repaired('key0'))
        stale = {'topologyRevision': old_topology['revision'], 'incarnation': primary['incarnation'],
                 'entry': {'key': '00000000-0000-0000-0000-000000000001', 'value': 'YmFk', 'version': 999,
                           'expiresAt': 0, 'deleted': False}}
        try:
            api(primary_port, '/internal/consensus/stage', stale, 'INTERNAL');
            raise AssertionError(
                'stale primary accepted')
        except urllib.error.HTTPError as e:
            assert e.code == 503
        current_incarnation = api(primary_port, '/internal/consensus/stats', role='INTERNAL')['incarnation']
        stale['incarnation'] = current_incarnation
        try:
            api(primary_port, '/internal/consensus/stage', stale, 'INTERNAL');
            raise AssertionError(
                'stale topology accepted')
        except urllib.error.HTTPError as e:
            assert e.code == 503
        rejected = etcd('kv/txn', {'compare': [
            {'key': b64('/cache/failure-test/topology'), 'target': 'MOD', 'result': 'EQUAL',
             'mod_revision': str(old_topology['revision'])}], 'success': [
            {'request_put': {'key': b64('/cache/failure-test/stale-publication'), 'value': b64('bad')}}]})
        assert not rejected.get('succeeded', False)
        print('PASS empty restart repair, obsolete-primary fencing and stale publication rejection', flush=True)
        blocked = True
        try:
            op(31080, 'SET', 'isolated');
            raise AssertionError('isolated gateway accepted mutation')
        except urllib.error.HTTPError as e:
            assert e.code == 503
        op(31081, 'SET', 'majority-side');
        assert op(31081, 'GET', 'majority-side')['found']
        blocked = False
        eventually(lambda: op(31080, 'GET', 'majority-side')['found'])
        print('PASS gateway partition fails closed; majority gateway continues', flush=True)
        # Delete pointer cannot be replaced by old staged bytes, even after topology changes.
        op(31081, 'DELETE');
        assert not op(31080, 'GET')['found']
        gateways[31080].kill();
        gateways[31080].wait()
        assert op(31081, 'GET', 'majority-side')['found']
        gateways[31080] = java(31080, True, True)
        eventually(lambda: request_json('http://127.0.0.1:31080/actuator/health').get('status') == 'UP')
        assert not op(31080, 'GET')['found']
        print('PASS gateway crash/restart and delete visibility', flush=True)
        identities = {port: api(port, '/admin/repair', role='ADMIN')['identity'] for port in gateways}


        def current_worker():
            values = etcd('kv/range', {'key': b64('/cache/failure-test/repair-worker')}).get('kvs', [])
            return base64.b64decode(values[0]['value']).decode() if values else ''


        # A crashed gateway's leased identity can remain until its lease expires.
        # Wait for a live incarnation before choosing the process to kill.
        leader_identity = eventually(
            lambda: (identity if (identity := current_worker()) in identities.values() else None))
        repair_gateway = next(port for port, identity in identities.items() if identity == leader_identity)
        survivor = next(port for port in gateways if port != repair_gateway)
        gateways[repair_gateway].kill();
        gateways[repair_gateway].wait()
        eventually(lambda: current_worker() == identities[survivor])
        assert op(survivor, 'GET', 'majority-side')['found']
        gateways[repair_gateway] = java(repair_gateway, True, repair_gateway == 31080)
        eventually(lambda: request_json(f'http://127.0.0.1:{repair_gateway}/actuator/health').get('status') == 'UP')
        print('PASS repair-worker crash and leased handoff to surviving gateway', flush=True)
        # A single etcd failure preserves quorum; losing two must close operations.
        # Exceed the old 32-slot size without losing any unrelated key.
        for i in range(40): op(31081, 'SET', 'index' + str(i))
        for i in range(40): assert op(31081, 'GET', 'index' + str(i))['found']


        def create(i):
            try:
                op(31080 + i % 2, 'SET', 'capacity' + str(i));
                return 200
            except urllib.error.HTTPError as e:
                assert e.code in (409, 507);
                return e.code


        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(create, range(40)))
        for i in range(30):
            try:
                op(31081, 'SET', 'fill' + str(i))
            except urllib.error.HTTPError as e:
                assert e.code == 507;
                break
        assert len(metadata()) == 64
        try:
            op(31081, 'SET', 'over-limit');
            raise AssertionError('metadata bound exceeded')
        except urllib.error.HTTPError as e:
            assert e.code == 507
        for i in range(40): assert op(31081, 'GET', 'index' + str(i))['found']
        op(31081, 'SET', 'majority-side')
        print('PASS collision-free index and concurrent hard-cap admission without unrelated eviction', flush=True)
        ctl_options = ['--cacert=' + str(certs / 'ca.crt'), '--cert=' + str(certs / 'client.crt'),
                       '--key=' + str(certs / 'client.key')] if secure else []
        ctl_env = dict(os.environ, ETCDCTL_USER='root:' + root_password) if secure else os.environ
        status_json = subprocess.check_output(
            [etcdctl_bin, '--endpoints=' + endpoints,
             'endpoint', 'status', '--write-out=json'] + ctl_options, timeout=10, env=ctl_env)
        statuses = json.loads(status_json)
        leader = next(i for i, item in enumerate(statuses) if
                      str(item['Status']['header']['member_id']) == str(item['Status']['leader']))
        etcds[leader].kill();
        etcds[leader].wait()
        eventually(lambda: op(31081, 'GET', 'majority-side')['found'])
        eventually(lambda: op(31081, 'SET', 'majority-side')['found'])
        second = (leader + 1) % 3
        etcds[second].kill();
        etcds[second].wait()
        for kind in ('GET', 'SET'):
            try:
                op(31081, kind);
                raise AssertionError('operation accepted without quorum')
            except urllib.error.HTTPError as e:
                assert e.code == 503
        print('PASS etcd leader crash elects replacement; quorum loss rejects reads and writes', flush=True)
        print('PASS all consensus failure scenarios', flush=True)
finally:
    blocked = False;
    release_publication.set();
    proxy.shutdown();
    proxy.server_close()
    for proc in processes:
        if proc.poll() is None: proc.terminate()
    for proc in processes:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill();
            proc.wait()
    for log in logs: log.close()
    if cert_directory: cert_directory.cleanup()
