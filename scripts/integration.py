#!/usr/bin/env python3
"""Real JVM cluster test. No Docker required; uses an already packaged jar."""
import concurrent.futures
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = dict(os.environ, CACHE_CLIENT_TOKEN='client-test-token-123', CACHE_INTERNAL_TOKEN='internal-test-token-123',
           CACHE_ADMIN_TOKEN='admin-test-token-123')
processes = []


def call(port, path, body=None, admin=False):
    token = env['CACHE_ADMIN_TOKEN' if admin else 'CACHE_CLIENT_TOKEN']
    req = urllib.request.Request(f'http://localhost:{port}' + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if hasattr(e, 'add_note'):
            e.add_note(f'{path}: {e.read().decode("utf-8", errors="replace")}\n'
                       f'JVM logs: {root / "target" / "process-*.log"}')
        raise


def op(kind, key='aw', value='dmFsdWU=', ttl=-1, version=None):
    return call(19080, '/api/v1/operation',
                dict(operation=kind, key=key, value=value, ttlMillis=ttl, expectedVersion=version))


# Refuse occupied ports before starting children, avoiding tests against unrelated services.
for port in range(19080, 19085):
    with socket.socket() as probe:
        probe.bind(('localhost', port))

try:
    for port in range(19080, 19085):
        args = ['java', '-Xmx128m', '-jar', str(root / 'target/distributed-cache-0.1.0.jar'), f'--server.port={port}']
        if port == 19080: args += ['--cache.coordinator=true',
                                   '--cache.nodes=' + ','.join(f'http://localhost:{n}' for n in range(19081, 19084))]
        log = open(root / f'target/process-{port}.log', 'w')
        processes.append(subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT));
        log.close()
    for port in range(19080, 19085):
        for attempt in range(90):
            try:
                urllib.request.urlopen(f'http://localhost:{port}/actuator/health', timeout=1);
                break
            except Exception:
                time.sleep(.25)
        else:
            raise AssertionError(f'{port} not healthy')
    assert all(p.poll() is None for p in processes), 'a test JVM exited during startup'
    call(19080, '/admin/bootstrap', {}, True)
    batch = call(19080, '/api/v1/cache/batch', {'operations': [
        dict(operation='SET', key='YmF0Y2g', value='dmFsdWU=', ttlMillis=-1),
        dict(operation='CAS', key='YmF0Y2g', value='dmFsdWU=', ttlMillis=-1, expectedVersion=0),
        dict(operation='GET', key='YmF0Y2g', ttlMillis=-1)]})
    assert [item['status'] for item in batch] == [200, 409, 200]
    assert batch[2]['result']['value'] == 'dmFsdWU='
    for invalid in [dict(operation='SET', key='aw', ttlMillis=-1),
                    dict(operation='INVALID', key='aw', ttlMillis=-1)]:
        try:
            call(19080, '/api/v1/operation', invalid)
            raise AssertionError('invalid request accepted')
        except urllib.error.HTTPError as e:
            assert e.code == 400

    first = op('SET');
    assert op('GET')['value'] == 'dmFsdWU='
    for port in range(19081, 19084):
        req = urllib.request.Request(f'http://localhost:{port}/internal/entry?key=aw',
                                     headers={'Authorization': 'Bearer ' + env['CACHE_INTERNAL_TOKEN']})
        with urllib.request.urlopen(req) as response:
            replica = json.load(response);
            assert replica['value'] == 'dmFsdWU=' and replica['version'] == first['version']
    req = urllib.request.Request('http://localhost:19081/internal/apply', data=json.dumps({'epoch': 0,
                                                                                           'entry': {'key': 'aw',
                                                                                                     'value': 'c3RhbGU=',
                                                                                                     'version': 999,
                                                                                                     'expiresAt': 0,
                                                                                                     'deleted': False}}).encode(),
                                 headers={'Authorization': 'Bearer ' + env['CACHE_INTERNAL_TOKEN'],
                                          'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req);
        raise AssertionError('stale epoch accepted')
    except urllib.error.HTTPError as e:
        assert e.code == 503
    assert op('GET')['value'] == 'dmFsdWU='
    req = urllib.request.Request('http://localhost:19080/actuator/prometheus',
                                 headers={'Authorization': 'Bearer ' + env['CACHE_ADMIN_TOKEN']})
    with urllib.request.urlopen(req) as response:
        assert b'jvm_memory' in response.read()


    def cas(_):
        try:
            op('CAS', version=first['version']);
            return 1
        except urllib.error.HTTPError as e:
            assert e.code == 409;
            return 0


    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(cas, range(20))) == 1
    op('SET', 'ttl', ttl=100);
    time.sleep(.15);
    assert not op('GET', 'ttl')['found']
    op('DELETE');
    assert not op('GET')['found']
    op('SET', 'migrate')
    call(19080, '/admin/topology', {'nodes': [f'http://localhost:{n}' for n in range(19081, 19085)]}, True)
    assert op('GET', 'migrate')['value'] == 'dmFsdWU='
    assert not op('GET', 'ttl')['found'], 'migration resurrected expired value'
    assert not op('GET')['found'], 'migration resurrected deleted value'
    try:
        urllib.request.urlopen('http://localhost:19080/admin/topology');
        raise AssertionError('auth missing')
    except urllib.error.HTTPError as e:
        assert e.code == 401
    processes[1].kill();
    processes[1].wait()
    for key in range(100):
        try:
            op('SET', 'failed' + str(key))
        except urllib.error.HTTPError as e:
            assert e.code == 503;
            break
    else:
        raise AssertionError('failed node was never detected')
    try:
        op('SET', 'unavailable');
        raise AssertionError('coordinator did not pause')
    except urllib.error.HTTPError as e:
        assert e.code == 503
    print(
        'PASS: five JVMs; routing, replication acknowledgment, CAS race, TTL, DELETE, four-node migration, authentication, failure closes writes')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    for process in processes:
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
