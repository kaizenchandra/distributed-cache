#!/usr/bin/env python3
"""Local end-to-end login, frontend authorization and cache smoke test. No secrets printed."""
import argparse
import base64
import http.cookiejar
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(
    line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
BASE = 'http://localhost:3000'


class LoginForm(HTMLParser):
    action = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'kc-form-login':
            self.action = attrs.get('action')


def request(opener, url, data=None, json_body=False):
    headers = {}
    if data is not None:
        headers = {'Content-Type': 'application/json' if json_body else 'application/x-www-form-urlencoded',
                   'Origin': BASE}
        data = (json.dumps(data) if json_body else urllib.parse.urlencode(data)).encode()
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=20) as response:
            body = response.read().decode()
            return response.status, body
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def login(username, password):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    status, body = request(opener, BASE + '/api/auth/csrf')
    assert status == 200, f'CSRF endpoint: {status}'
    status, body = request(opener, BASE + '/api/auth/signin/keycloak',
                           {'csrfToken': json.loads(body)['csrfToken'], 'callbackUrl': BASE, 'json': 'true'})
    assert status == 200, f'Signin endpoint: {status}'
    url = json.loads(body)['url']
    assert url.startswith('http://localhost:8180/'), 'Unexpected identity provider redirect'
    status, body = request(opener, url)
    parser = LoginForm();
    parser.feed(body)
    assert parser.action, 'Keycloak login form missing'
    # Browsers allow Secure cookies on localhost HTTP; urllib does not.
    # Reproduce that localhost-only browser exception in this development test.
    for cookie in jar:
        if cookie.domain == 'localhost.local' and cookie.path.startswith('/realms/cache/'):
            cookie.secure = False
    status, _ = request(opener, parser.action, {'username': username, 'password': password, 'credentialId': ''})
    assert status == 200, f'Login callback: {status}'
    status, body = request(opener, BASE + '/api/auth/session')
    session = json.loads(body)
    assert session.get('user') and not session.get('expired'), 'Authenticated session missing'
    assert 'accessToken' not in body and 'refreshToken' not in body, 'Token leaked to browser session'
    return opener, session, jar


def proxy(opener, action, payload=None):
    status, body = request(opener, BASE + '/api/cache', {'action': action, 'payload': payload}, True)
    return status, json.loads(body)


def session_token(jar):
    cookies = {c.name: c.value for c in jar if c.name.startswith('next-auth.session-token')}
    if 'next-auth.session-token' in cookies:
        return cookies['next-auth.session-token']
    return ''.join(cookies[name] for name in sorted(cookies, key=lambda n: int(n.rsplit('.', 1)[1])))


def jwt_helper(action, data):
    # Keep credentials out of command arguments, logs and browser session JSON.
    code = """
const fs = require('node:fs');
const { decode, encode } = require('./frontend/node_modules/next-auth/jwt');
(async () => {
 const input = JSON.parse(fs.readFileSync(0, 'utf8'));
 const result = input.action === 'decode'
   ? await decode({ token: input.token, secret: input.secret })
   : await encode({ token: input.claims, secret: input.secret, maxAge: 3600 });
 process.stdout.write(JSON.stringify(result));
})().catch(() => { process.stderr.write('Session helper failed'); process.exit(1); });
"""
    response = subprocess.run(['node', '-e', code],
                              input=json.dumps({'action': action, 'secret': ENV['NEXTAUTH_SECRET'], **data}), text=True,
                              capture_output=True, check=True, cwd=ROOT)
    return json.loads(response.stdout)


def backend(path, token=None, payload=None, port=8080):
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    data = None if payload is None else json.dumps(payload).encode()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f'http://localhost:{port}' + path, data=data, headers=headers),
                timeout=20) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as error:
        return error.code, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['legacy', 'consensus'])
    args = parser.parse_args()
    checks = 0

    def check(condition, label):
        nonlocal checks
        assert condition, label
        checks += 1
        print(f'PASS {checks:02}: {label}')

    anon = urllib.request.build_opener()
    check(proxy(anon, 'health')[0] == 401, 'anonymous frontend proxy request rejected')
    try:
        login('cache-user', 'intentionally-wrong-' + uuid.uuid4().hex)
        raise AssertionError('invalid password accepted')
    except AssertionError as error:
        check(str(error) == 'Authenticated session missing', 'Keycloak rejects incorrect password')
    user, session, user_jar = login('cache-user', ENV['KEYCLOAK_USER_PASSWORD'])
    check('cache-user' in session['roles'] and 'cache-admin' not in session['roles'],
          'Keycloak user login and role claims; no token in session JSON')
    for action, payload in [('topology', None), ('repair', None), ('bootstrap', {}), ('changeTopology', {'nodes': []})]:
        check(proxy(user, action, payload)[0] == 403, f'user forbidden from frontend {action}')
    req = urllib.request.Request(BASE + '/api/cache', data=b'{"action":"health"}',
                                 headers={'Content-Type': 'application/json', 'Origin': 'https://untrusted.example'})
    try:
        user.open(req, timeout=10)
        raise AssertionError('cross-origin request accepted')
    except urllib.error.HTTPError as error:
        check(error.code == 403, 'frontend rejects cross-origin requests with a valid session')
    admin, session, admin_jar = login('cache-admin', ENV['KEYCLOAK_ADMIN_PASSWORD'])
    check('cache-admin' in session['roles'], 'Keycloak admin login and role claims')
    user_claims = jwt_helper('decode', {'token': session_token(user_jar)})
    admin_claims = jwt_helper('decode', {'token': session_token(admin_jar)})
    for path, payload in [('/admin/topology', None), ('/admin/repair', None), ('/admin/bootstrap', {})]:
        check(backend(path, user_claims['accessToken'], payload)[0] == 403, f'backend independently denies user {path}')
    check(backend('/api/v1/operation', payload={})[0] == 401, 'backend rejects anonymous operation')
    check(backend('/api/v1/operation', ENV['CACHE_CLIENT_TOKEN'], {})[0] == 401,
          'static client credential cannot bypass Keycloak')
    check(backend('/admin/topology', ENV['CACHE_ADMIN_TOKEN'])[0] == 401,
          'static admin credential cannot bypass Keycloak')
    check(backend('/internal/stats', admin_claims['accessToken'])[0] == 401,
          'human admin token cannot access internal RPC')
    parts = user_claims['accessToken'].split('.')
    claims = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
    claims['realm_access'] = {'roles': ['cache-admin']}
    parts[1] = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    check(backend('/admin/topology', '.'.join(parts))[0] == 401, 'forged admin role fails JWT signature validation')
    expired_claims = {**user_claims, 'accessExpires': int(time.time()) - 60}
    expired_cookie = jwt_helper('encode', {'claims': expired_claims})
    req = urllib.request.Request(BASE + '/api/cache', data=b'{"action":"health"}',
                                 headers={'Content-Type': 'application/json', 'Origin': BASE,
                                          'Cookie': 'next-auth.session-token=' + expired_cookie})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError('expired access token accepted')
    except urllib.error.HTTPError as error:
        check(error.code == 401, 'frontend rejects expired access token in an otherwise valid session')
    check(proxy(user, 'health')[1].get('status') == 'UP', 'authenticated frontend gateway health')
    status, topology = proxy(admin, 'topology')
    check(status == 200, 'admin reads topology through frontend')
    mode = 'consensus' if 'topology' in topology else 'legacy'
    check(not args.mode or args.mode == mode, f'backend mode is {mode}')
    if mode == 'consensus':
        cluster = topology['topology']
        check(len(cluster['members']) == 4 and cluster['replicas'] == 3 and cluster['minimumCopies'] == 2,
              'four storage members, three replicas, two minimum copies')
        check(proxy(admin, 'bootstrap', {})[0] == 200, 'admin reconciles consensus membership through frontend')
        status, repair = proxy(admin, 'repair')
        check(status == 200 and 'scanned' in repair, 'admin reads consensus repair status through frontend')
        check(proxy(admin, 'changeTopology', {'nodes': []})[0] in (404, 405),
              'legacy topology mutation unavailable in consensus mode')
        status, other = backend('/admin/topology', admin_claims['accessToken'], port=8081)
        check(status == 200 and other['topology'] == cluster,
              'second active gateway sees the same consensus membership')
    elif topology.get('ready') is False:
        check(proxy(admin, 'bootstrap', {})[0] == 200, 'admin bootstraps fresh legacy nodes')
    keys = []

    def new_key(suffix):
        text = 'auth-e2e:' + uuid.uuid4().hex + ':' + suffix
        key = base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')
        keys.append(key)
        return key

    key = new_key('main')

    def operation(op, target=key, **kwargs):
        return proxy(user, 'operation', {'operation': op, 'key': target, 'ttlMillis': -1, **kwargs})

    def value(text):
        return base64.b64encode(text.encode()).decode()

    def wait_missing(target):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            status, result = operation('GET', target)
            if status == 200 and not result['found']: return result
            time.sleep(.1)
        raise AssertionError('key did not expire')

    try:
        check(operation('GET')[1] == {'found': False, 'value': None, 'version': 0, 'ttlMillis': -2},
              'GET missing key sentinel values')
        check(not operation('EXISTS')[1]['found'] and operation('TTL')[1]['ttlMillis'] == -2,
              'EXISTS and TTL on missing key')
        check(not operation('EXPIRE', ttlMillis=1000)[1]['found'], 'EXPIRE missing key is a miss')
        check(operation('SET', value=value('hello'))[0] == 200, 'SET permanent value')
        status, result = operation('GET')
        check(status == 200 and result['value'] == value('hello') and result['version'] > 0,
              'GET returns exact value and version')
        version = result['version']
        check(operation('EXISTS')[1]['found'] is True, 'EXISTS present key')
        check(operation('TTL')[1]['ttlMillis'] == -1, 'TTL permanent sentinel')
        if mode == 'consensus':
            status, other = backend('/api/v1/operation', user_claims['accessToken'],
                                    {'operation': 'GET', 'key': key, 'ttlMillis': -1}, port=8081)
            check(status == 200 and other == result, 'frontend write visible through second gateway')
        check(operation('CAS', value=value('world'), expectedVersion=version)[0] == 200,
              'CAS succeeds for current version')
        check(operation('CAS', value=value('bad'), expectedVersion=version)[0] == 409, 'CAS stale version rejected')
        check(operation('GET')[1]['value'] == value('world'), 'failed CAS preserves current value')
        check(operation('EXPIRE', ttlMillis=1000)[0] == 200, 'EXPIRE applies deadline')
        check(0 < operation('TTL')[1]['ttlMillis'] <= 1000, 'TTL shows decreasing deadline')
        check(wait_missing(key)['ttlMillis'] == -2, 'value expires and GET returns missing')
        check(operation('SET', value=value('short'), ttlMillis=250)[0] == 200, 'SET with TTL')
        check(not wait_missing(key)['found'], 'SET TTL expires naturally')
        check(operation('SET', value=value('delete now'))[0] == 200 and
              operation('SET', value=value('gone'), ttlMillis=0)[0] == 200 and not operation('GET')[1]['found'],
              'TTL zero deletes immediately')
        check(operation('CAS', value=value('created'), expectedVersion=0)[0] == 200,
              'CAS version zero creates absent key')
        check(operation('CAS', value=value('overwrite'), expectedVersion=0)[0] == 409,
              'CAS version zero cannot overwrite present key')
        check(operation('EXPIRE', ttlMillis=-1)[1]['ttlMillis'] == -1, 'EXPIRE minus one makes value permanent')
        check(operation('EXPIRE', ttlMillis=0)[0] == 200 and not operation('EXISTS')[1]['found'],
              'EXPIRE zero deletes immediately')
        unicode_key = new_key('नमस्ते-🌍')
        text = 'नमस्ते 🌍\ncache ✓'
        check(operation('SET', unicode_key, value=value(text))[0] == 200 and operation('GET', unicode_key)[1][
            'value'] == value(text), 'Unicode key and multiline UTF-8 value round trip')
        check(operation('SET', unicode_key, value='')[0] == 200 and operation('GET', unicode_key)[1]['value'] == '',
              'empty value round trip')
        big_key = new_key('64k')
        check(operation('SET', big_key, value=value('x' * 65536))[0] == 200 and operation('GET', big_key)[1][
            'value'] == value('x' * 65536), '64 KiB maximum value round trip')
        check(operation('SET', value=value('x' * 65537))[0] == 400, 'oversized value rejected')
        check(operation('SET', value=value('bad TTL'), ttlMillis=-2)[0] == 400, 'invalid TTL rejected')
        check(operation('CAS', value=value('missing version'))[0] == 400, 'CAS requires expected version')
        batch_key = new_key('batch')

        def item(op, **extra):
            return {'operation': op, 'key': batch_key, 'ttlMillis': -1, **extra}

        status, results = proxy(user, 'batch', {'operations': [item('SET', value=value('batch')), item('GET'),
                                                               item('CAS', value=value('fail'), expectedVersion=0),
                                                               item('GET'), item('DELETE'), item('EXISTS')]})
        check(status == 200 and [r['status'] for r in results] == [200, 200, 409, 200, 200, 200],
              'batch returns individual success and conflict statuses')
        check(
            results[1]['result']['value'] == value('batch') and results[3]['result']['value'] == value('batch') and not
            results[-1]['result']['found'], 'batch preserves order, continues after conflict, and deletes')
        check(proxy(user, 'batch', {'operations': []})[0] == 400, 'empty batch rejected')
        status, _ = proxy(user, 'batch',
                          {'operations': [item('SET', value=value('should not write')), item('INVALID')]})
        check(status == 400 and not operation('GET', batch_key)[1]['found'],
              'malformed batch rejected before any mutation')
        check(operation('SET', value=value('delete me'))[0] == 200 and operation('DELETE')[0] == 200 and not
        operation('GET')[1]['found'], 'DELETE removes existing key')
        check(operation('DELETE')[0] == 200, 'DELETE missing key is idempotent')
        check(proxy(admin, 'operation', {'operation': 'GET', 'key': key, 'ttlMillis': -1})[0] == 200,
              'admin can also execute cache operations')
    finally:
        for target in keys:
            status, _ = operation('DELETE', target)
            if status != 200: print('WARNING: cleanup failed for a generated test key')
    # Local app logout uses NextAuth CSRF protection and invalidates the browser session.
    status, body = request(user, BASE + '/api/auth/csrf')
    status, _ = request(user, BASE + '/api/auth/signout',
                        {'csrfToken': json.loads(body)['csrfToken'], 'callbackUrl': BASE, 'json': 'true'})
    check(status == 200 and proxy(user, 'health')[0] == 401, 'logout clears frontend access')
    print(f'PASS: {checks} end-to-end HTTP checks in {mode} mode. Generated cache keys deleted.')


if __name__ == '__main__':
    main()
