#!/usr/bin/env python3
"""Verify manifests in a disposable namespace on an explicitly selected Kubernetes cluster."""
import argparse
import base64
import json
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', type=Path, required=True, help='Explicit test-cluster credentials; current context is never changed')
    parser.add_argument('--mode', choices=['legacy', 'consensus'], default='consensus')
    parser.add_argument('--reuse', action='store_true', help='Reuse only the reserved disposable namespace, retaining its existing test Secret')
    parser.add_argument('--keep', action='store_true', help='Keep namespace and PVCs for inspection even if verification fails')
    a = parser.parse_args()
    if not a.kubeconfig.is_file(): parser.error('kubeconfig does not exist')
    namespace = 'cache-verify-' + a.mode
    output = ROOT / 'target' / ('kubernetes-' + a.mode)
    output.mkdir(parents=True, exist_ok=True)
    base = ['kubectl', '--kubeconfig', str(a.kubeconfig.resolve()), '--request-timeout=30s']

    def k(*args, data=None):
        return subprocess.check_output(base + ['-n', namespace, *args], input=data, text=True)

    def object_(*args): return json.loads(k(*args, '-o', 'json'))

    def eventually(action, seconds=180):
        end = time.monotonic() + seconds
        last = None
        while time.monotonic() < end:
            try:
                value = action()
                if value: return value
            except (OSError, ValueError, subprocess.CalledProcessError) as error: last = error
            time.sleep(.5)
        raise AssertionError(f'condition timed out: {last}')

    exists = subprocess.run(base + ['get', 'namespace', namespace], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if exists and not a.reuse: parser.error(f'{namespace} already exists; use --reuse only for this disposable test namespace')
    if not exists: subprocess.run(base + ['create', 'namespace', namespace], check=True)
    checks = []
    forward = None
    port = None
    forward_log = (output / 'port-forward.log').open('w')
    success = False

    def passed(message):
        checks.append(message)
        print('PASS ' + message, flush=True)

    def start_forward():
        nonlocal forward, port
        if forward is not None:
            forward.terminate()
            forward.wait(timeout=10)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        service = 'cache-gateway' if a.mode == 'consensus' else 'cache-coordinator'
        forward = subprocess.Popen(base + ['-n', namespace, 'port-forward', 'service/' + service, f'{port}:8080', '--address=127.0.0.1'],
                                   stdout=forward_log, stderr=subprocess.STDOUT)
        eventually(lambda: api('/actuator/health')['status'] == 'UP', seconds=30)

    def api(path, body=None, admin=False, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth: headers['Authorization'] = 'Bearer ' + tokens['CACHE_ADMIN_TOKEN' if admin else 'CACHE_CLIENT_TOKEN']
        request = urllib.request.Request(f'http://127.0.0.1:{port}' + path,
                    data=None if body is None else json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()
            return json.loads(data) if 'json' in response.headers.get('Content-Type', '') else data.decode()

    def op(kind, key='azhz', **options):
        return api('/api/v1/operation', dict(operation=kind, key=key, value='dmFsdWU=', ttlMillis=-1, **options))

    def topology(): return api('/admin/topology', admin=True)

    def ready_new_pod(name, old_uid):
        pod = object_('get', 'pod', name)
        return pod['metadata']['uid'] != old_uid and any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod.get('status', {}).get('conditions', []))

    try:
        if exists:
            secret = object_('get', 'secret', 'cache-tokens')['data']
            tokens = {key: base64.b64decode(value).decode() for key, value in secret.items()}
        else:
            tokens = {f'CACHE_{role}_TOKEN': secrets.token_urlsafe(32) for role in ['CLIENT', 'ADMIN', 'INTERNAL']}
            secret = dict(apiVersion='v1', kind='Secret', metadata=dict(name='cache-tokens'), stringData=tokens)
            k('apply', '-f', '-', data=json.dumps(secret))
        manifest = ROOT / 'deploy' / ('kubernetes-consensus.yaml' if a.mode == 'consensus' else 'kubernetes.yaml')
        k('apply', '--dry-run=server', '-f', str(manifest))
        k('apply', '-f', str(manifest))
        if a.mode == 'consensus': k('rollout', 'status', 'statefulset/etcd', '--timeout=240s')
        k('rollout', 'status', 'statefulset/cache', '--timeout=240s')
        gateway = 'cache-gateway' if a.mode == 'consensus' else 'cache-coordinator'
        k('rollout', 'status', 'deployment/' + gateway, '--timeout=240s')
        start_forward()
        if a.mode == 'legacy':
            if not topology()['ready']: api('/admin/bootstrap', {}, admin=True)
        else:
            eventually(lambda: len(topology()['topology']['members']) == 4)
            claims = object_('get', 'pvc')['items']
            assert len(claims) == 3 and all(p['status']['phase'] == 'Bound' for p in claims)
        op('SET')
        assert op('GET')['value'] == 'dmFsdWU='
        try:
            api('/admin/topology', auth=False)
            raise AssertionError('unauthenticated admin accepted')
        except urllib.error.HTTPError as e: assert e.code == 401
        assert 'jvm_memory' in api('/actuator/prometheus', admin=True)
        batch = api('/api/v1/cache/batch', {'operations': [
            dict(operation='CAS', key='azhz', value='dmFsdWU=', ttlMillis=-1, expectedVersion=0),
            dict(operation='GET', key='azhz', ttlMillis=-1)]})
        assert [item['status'] for item in batch] == [409, 200]
        api('/api/v1/operation', dict(operation='SET', key='dHRs', value='dmFsdWU=', ttlMillis=100))
        time.sleep(.2)
        assert not op('GET', 'dHRs')['found']
        op('SET', 'ZGVsZXRl')
        op('DELETE', 'ZGVsZXRl')
        assert not op('GET', 'ZGVsZXRl')['found']
        passed('server schema validation, pod readiness, Service routing, auth, batch/CAS, TTL, DELETE and metrics')
        if a.mode == 'consensus':
            def manifest_():
                address = '/cache/kubernetes/keys/' + base64.urlsafe_b64encode(b'azhz').decode().rstrip('=')
                return json.loads(k('exec', 'etcd-0', '--', '/usr/local/bin/etcdctl', 'get', address, '--print-value-only'))

            primary = manifest_()['owners'][0]
            victim = urllib.parse.urlparse(primary['url']).hostname.split('.')[0]
            assert victim in {'cache-0', 'cache-1', 'cache-2', 'cache-3'}
            old_uid = object_('get', 'pod', victim)['metadata']['uid']
            k('delete', 'pod', victim, '--wait=true')
            eventually(lambda: ready_new_pod(victim, old_uid))

            def repaired():
                owners = manifest_()['owners']
                members = topology()['topology']['members']
                return len(owners) == 3 and all(owner in members for owner in owners) and any(
                    owner['url'] == primary['url'] and owner['incarnation'] != primary['incarnation'] for owner in owners)

            eventually(repaired)
            assert op('GET')['found']
            passed('actual primary pod replacement, changed incarnation and replica repair preserve committed value')
            k('scale', 'statefulset/cache', '--replicas=5')
            k('rollout', 'status', 'statefulset/cache', '--timeout=240s')
            eventually(lambda: len(topology()['topology']['members']) == 5)
            assert op('GET')['found']
            k('scale', 'statefulset/cache', '--replicas=4')
            eventually(lambda: len(topology()['topology']['members']) == 4)
            eventually(repaired)
            assert op('GET')['found']
            passed('online storage scale 4→5→4 preserves committed value and repairs ownership')
            k('rollout', 'restart', 'deployment/cache-gateway')
            k('rollout', 'status', 'deployment/cache-gateway', '--timeout=240s')
            start_forward()
            assert op('GET')['found']
            passed('rolling gateway restart retains access to committed data')
            def etcd_member():
                return json.loads(k('exec', 'etcd-0', '--', '/usr/local/bin/etcdctl', 'endpoint', 'status', '-w', 'json'))[0]['Status']['header']['member_id']
            member_id = etcd_member()
            old_uid = object_('get', 'pod', 'etcd-0')['metadata']['uid']
            k('delete', 'pod', 'etcd-0', '--wait=true')
            eventually(lambda: ready_new_pod('etcd-0', old_uid))
            assert etcd_member() == member_id
            eventually(lambda: op('GET')['found'])
            passed('etcd pod replacement reuses persistent member identity and retained metadata')
        success = True
    finally:
        if forward is not None:
            forward.terminate()
            forward.wait(timeout=10)
        forward_log.close()
        (output / 'result.json').write_text(json.dumps(dict(mode=a.mode, success=success, checks=checks), indent=2) + '\n')
        try:
            (output / 'resources.json').write_text(k('get', 'pods,svc,pdb,pvc', '-o', 'json'))
            (output / 'events.txt').write_text(k('get', 'events', '--sort-by=.metadata.creationTimestamp'))
            pods = object_('get', 'pods')['items']
            for pod in pods:
                name = pod['metadata']['name']
                try: (output / (name + '.log')).write_text(k('logs', name, '--all-containers', '--tail=300'))
                except subprocess.CalledProcessError: pass
        finally:
            if not a.keep: subprocess.run(base + ['delete', 'namespace', namespace, '--wait=true', '--timeout=120s'], check=True)


if __name__ == '__main__':
    main()
