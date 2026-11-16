#!/usr/bin/env python3
"""Own an isolated Compose cluster, verify APIs, optionally inject controlled failures."""
import argparse
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['legacy', 'consensus'], default='consensus')
    parser.add_argument('--chaos', action='store_true')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--keep', action='store_true', help='Leave dedicated test cluster running for load tests')
    args = parser.parse_args()
    project = 'cache-verify-' + args.mode
    compose = ['docker', 'compose', '-p', project, '-f',
               str(ROOT / ('docker-compose.yaml' if args.mode == 'legacy' else 'compose.consensus.yaml')),
               '-f', str(ROOT / f'deploy/compose.{args.mode}-test.yaml')]
    env = dict(os.environ)
    # init-env.py writes simple KEY=VALUE lines; never print the credentials.
    for line in (ROOT / '.env').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env.setdefault(key, value)
    output = ROOT / 'target' / ('compose-' + args.mode)
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    paused = set()
    recovery_probe_failures = []

    def dc(*command, capture=False):
        return subprocess.run(compose + list(command), cwd=ROOT, env=env, check=True,
                              stdout=subprocess.PIPE if capture else None, text=True).stdout

    def call(path, body=None, port=18080, admin=False, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer ' + env['CACHE_ADMIN_TOKEN' if admin else 'CACHE_CLIENT_TOKEN']
        request = urllib.request.Request(f'http://localhost:{port}' + path,
                                         data=None if body is None else json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read()
            return json.loads(data) if 'json' in response.headers.get('Content-Type', '') else data.decode()

    def eventually(action, seconds=90):
        end = time.monotonic() + seconds
        last = None
        while time.monotonic() < end:
            try:
                result = action()
                if result: return result
            except Exception as error:
                last = error
                recovery_probe_failures.append(type(error).__name__ + ':' + str(getattr(error, 'code', 'transport')))
            time.sleep(.5)
        raise AssertionError(f'condition timed out: {last}')

    def op(kind, key='compose-key', port=18080, **options):
        return call('/api/v1/operation',
                    dict(operation=kind, key=base64.urlsafe_b64encode(key.encode()).decode().rstrip('='),
                         value='dmFsdWU=', ttlMillis=-1, **options), port=port)

    def write_probe(prefix, port=18080):
        # Each probe has a fresh key: never replay an ambiguous mutation.
        key = prefix + '-' + uuid.uuid4().hex
        return op('SET', key, port=port)['found'] and op('GET', key, port=port)['found']

    def rejected(action, status):
        try:
            action()
        except urllib.error.HTTPError as error:
            assert error.code == status, (error.code, error.read())
        else:
            raise AssertionError(f'expected HTTP {status}')

    def passed(message):
        checks.append(message)
        print('PASS ' + message, flush=True)

    def pause(service):
        dc('pause', service)
        paused.add(service)

    def resume(service):
        dc('unpause', service)
        paused.remove(service)

    success = False
    try:
        dc('up', '-d', *([] if args.skip_build else ['--build']))
        ports = [18080, 18081] if args.mode == 'consensus' else [18080]
        for port in ports:
            eventually(lambda: call('/actuator/health', port=port)['status'] == 'UP')
        if args.mode == 'legacy':
            topology = call('/admin/topology', admin=True)
            if not topology['ready']: call('/admin/bootstrap', {}, admin=True)
        else:
            eventually(lambda: len(call('/admin/topology', admin=True)['topology']['members']) == 4)
        op('SET')
        assert op('GET', port=ports[-1])['value'] == 'dmFsdWU='
        rejected(lambda: call('/admin/topology', auth=False), 401)
        assert 'jvm_memory' in call('/actuator/prometheus', admin=True)
        batch = call('/api/v1/cache/batch', {'operations': [
            dict(operation='CAS', key='Y29tcG9zZS1rZXk', value='dmFsdWU=', ttlMillis=-1, expectedVersion=0),
            dict(operation='GET', key='Y29tcG9zZS1rZXk', ttlMillis=-1)]})
        assert [item['status'] for item in batch] == [409, 200]
        call('/api/v1/operation', dict(operation='SET', key='dHRs', value='dmFsdWU=', ttlMillis=100))
        time.sleep(.2)
        assert not op('GET', 'ttl')['found']
        op('SET', 'deleted')
        op('DELETE', 'deleted')
        assert not op('GET', 'deleted', port=ports[-1])['found']
        passed('Compose routing, cross-gateway reads, CAS conflict, batch, TTL, DELETE, auth and metrics')
        if args.chaos and args.mode == 'legacy':
            dc('kill', '-s', 'SIGKILL', 'node-a')
            rejected(lambda: op('SET'), 503)
            rejected(lambda: op('SET', 'after-failure'), 503)
            passed('legacy storage crash closes mutations; automatic recovery is unsupported')
        elif args.chaos:
            # Pause represents a hung process; kill/restart represents a new empty incarnation.
            pause('etcd-0')
            eventually(lambda: op('GET', port=18081)['found'])
            eventually(lambda: write_probe('one-etcd-down'))
            resume('etcd-0')
            passed('one paused etcd member permits bounded recovery and new writes after election')

            def manifest():
                key = base64.urlsafe_b64encode(b'compose-key').decode().rstrip('=')
                address = '/cache/compose/keys/' + base64.urlsafe_b64encode(key.encode()).decode().rstrip('=')
                return json.loads(
                    dc('exec', '-T', 'etcd-0', 'etcdctl', 'get', address, '--print-value-only', capture=True))

            primary = manifest()['owners'][0]
            victim = urllib.parse.urlparse(primary['url']).hostname
            assert victim in {'node-0', 'node-1', 'node-2', 'node-3'}

            def repaired(restarted=False):
                owners = manifest()['owners']
                live = call('/admin/topology', admin=True)['topology']['members']
                return (len(owners) == 3 and all(owner in live for owner in owners)
                        and (not restarted or any(owner['url'] == primary['url'] and
                                                  owner['incarnation'] != primary['incarnation'] for owner in owners)))

            dc('kill', '-s', 'SIGKILL', victim)
            eventually(lambda: len(call('/admin/topology', admin=True)['topology']['members']) == 3)
            assert op('GET')['found']
            eventually(lambda: repaired())
            dc('up', '-d', victim)
            eventually(lambda: len(call('/admin/topology', admin=True)['topology']['members']) == 4)
            assert op('GET', port=18081)['found']
            eventually(lambda: repaired(restarted=True))
            passed('actual primary SIGKILL, replica repair and empty restart preserve committed value')
            pause('gateway-0')
            op('SET', 'gateway-outage', port=18081)
            assert op('GET', 'gateway-outage', port=18081)['found']
            resume('gateway-0')
            eventually(lambda: op('GET', 'gateway-outage')['found'])
            passed('gateway pause leaves second gateway available; resumed gateway catches up')
            pause('etcd-0')
            pause('etcd-1')
            rejected(lambda: op('GET'), 503)
            rejected(lambda: op('SET', 'no-quorum'), 503)
            resume('etcd-0')
            resume('etcd-1')
            eventually(lambda: op('GET')['found'])
            eventually(lambda: write_probe('recovered'))
            passed('loss of etcd quorum rejects reads/writes and restoration recovers service')
        success = True
    finally:
        for service in list(paused):
            try:
                resume(service)
            except subprocess.CalledProcessError:
                pass
        (output / 'result.json').write_text(json.dumps(
            dict(mode=args.mode, chaos=args.chaos, success=success, checks=checks,
                 recovery_probe_failures=recovery_probe_failures), indent=2) + '\n')
        try:
            (output / 'containers.json').write_text(dc('ps', '-a', '--format', 'json', capture=True))
            (output / 'containers.log').write_text(dc('logs', '--no-color', capture=True))
        finally:
            if not args.keep: dc('down', '-v', '--remove-orphans')


if __name__ == '__main__':
    main()
