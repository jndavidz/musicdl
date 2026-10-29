'''offline tests for singleflight, upstream cooldown and scoped invalidation (K-04).
   Sections:
     A. SingleFlight primitive (waiter cancellation isolation, leader failure)
     B. HTTP singleflight: N concurrent same-key resolves -> ONE upstream call
     C. leader failure leaves no bad cache; identities never merge
     D. 429 cooldown: logical-name cooling, Retry-After, no success caching,
        local vs upstream rate-limit classification
     E. scoped invalidation: exact identity only, cross-scope rejected
   Run: XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_resilience.py'''
import asyncio
import concurrent.futures
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from server.config import Settings
from server.app import create_app
from server.adapters.base import AdapterError, SourceAdapter
from server.parsers_health import ParserHealth, is_rate_limited, retry_after_from
from server.singleflight import SingleFlight

PASSED, FAILED = 0, []


def check(name, cond, detail=''):
    global PASSED
    print(f'  {"PASS" if cond else "FAIL"} {name} {detail}')
    if cond: PASSED += 1
    else: FAILED.append(name)


print('== resilience offline ==')

# ---- A: SingleFlight primitive ----
print('[A] SingleFlight primitive')


async def case_flight():
    flight = SingleFlight()
    started, release = asyncio.Event(), asyncio.Event()
    calls = {'n': 0}

    async def work():
        calls['n'] += 1
        started.set()
        await release.wait()
        return 'value'

    leader_caller = asyncio.create_task(flight.run('k', work))
    await started.wait()
    waiter = asyncio.create_task(flight.run('k', work))
    await asyncio.sleep(0.05)
    waiter.cancel()
    cancelled = waiter.cancelled() or waiter.cancelling() > 0
    try:
        await waiter
    except asyncio.CancelledError:
        cancelled = True
    release.set()
    leader_value = await leader_caller
    return flight, calls['n'], cancelled, leader_value


flight, calls, cancelled, value = asyncio.run(case_flight())
check('one leader for same key', calls == 1, f'calls={calls}')
check('cancelling one waiter does not cancel the leader', cancelled and value == 'value')
check('flight registry empties when the leader finishes', flight.inflight == 0)


async def case_flight_failure():
    flight = SingleFlight()
    state = {'fail': True, 'calls': 0}

    async def work():
        state['calls'] += 1
        if state['fail']:
            raise RuntimeError('boom')
        return 'ok'

    first = None
    try:
        await flight.run('k', work)
    except RuntimeError as err:
        first = str(err)
    state['fail'] = False
    second = await flight.run('k', work)
    return state['calls'], first, second


calls, first, second = asyncio.run(case_flight_failure())
check('failed leader leaves no negative cache (retry works)', calls == 2 and first == 'boom' and second == 'ok')


# ---- shared app fixtures ----
class FakeAdapter:
    source_key = 'qq'

    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()
        self.delay = 0.0
        self.fail = None

    def identity_kwargs(self, extra):
        return {}

    def identity_out(self, requested, result):
        return dict(requested or {})

    async def song_url(self, song_id, quality, **kw):
        with self.lock:
            self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return {'id': song_id, 'source': self.source_key, 'quality': quality,
                'url': f'http://example.test/{song_id}.mp3', 'ext': 'mp3',
                'size_bytes': 1024 * 1024, 'bitrate_kbps': 320, 'duration_s': 180,
                'cover': None, 'verified': True, 'headers': {}, 'parser': 'fake',
                'elapsed_ms': 1, 'cached': False}


def _free_port() -> int:
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close(); return port


def start_app(app):
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    base = f'http://127.0.0.1:{port}'
    for _ in range(50):
        try:
            urllib.request.urlopen(base + '/healthz', timeout=1)
            return base, server
        except Exception:
            time.sleep(0.2)
    raise RuntimeError('app did not start')


TOKENS = json.dumps({
    'play': {'scopes': ['playback:issue'], 'generation': 1},
    'inv': {'scopes': ['cache:invalidate'], 'generation': 1},
})


def post(base, path, body, token='play'):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json',
                                          'X-Service-Token': token})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8')), dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8')), dict(e.headers)
        except Exception:
            return e.code, {}, dict(e.headers)


app = create_app(Settings(env={'API_KEY': 'dl', 'TRUSTED_NETWORKS': '', 'UNTRUSTED_HOSTS': '',
                              'RATE_LIMIT': '', 'SERVICE_TOKENS': TOKENS}))
base, server = start_app(app)
fake = FakeAdapter()
app.state.adapters['qq'] = fake

# ---- B: HTTP singleflight ----
print('[B] HTTP singleflight')
fake.delay = 0.4
body = {'track_ref': {'source': 'qq', 'id': 'sf1'}, 'profile': {'quality': '320k'}}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(lambda _: post(base, '/v2/playback/resolve', body), range(6)))
codes = [r[0] for r in results]
urls = {(r[1].get('data') or {}).get('url') for r in results}
check('all concurrent requests succeed', codes == [200] * 6, f'codes={codes}')
check('N concurrent same-key resolves -> ONE upstream call', fake.calls == 1, f'calls={fake.calls}')
check('all waiters share the leader result', len(urls) == 1, f'urls={urls}')
fake.delay = 0.0

# ---- C: leader failure + identity separation ----
print('[C] leader failure / identity separation')
fake.fail = AdapterError(502, 'upstream failure: fake')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    failed = list(pool.map(lambda _: post(base, '/v2/playback/resolve',
                                          {'track_ref': {'source': 'qq', 'id': 'bad1'}}), range(4)))
check('failed leader propagates to every waiter', [r[0] for r in failed] == [502] * 4,
      f'codes={[r[0] for r in failed]}')
fake.fail = None
st, b, _ = post(base, '/v2/playback/resolve', {'track_ref': {'source': 'qq', 'id': 'bad1'}})
check('failure is not cached: next request resolves', st == 200 and (b.get('data') or {}).get('url'), f'status={st}')

before = fake.calls
migu_fake = FakeAdapter()
migu_fake.source_key = 'migu'
migu_fake.delay = 0.3
app.state.adapters['migu'] = migu_fake
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(lambda i: post(base, '/v2/playback/resolve',
                                 {'track_ref': {'source': 'migu', 'id': '9001',
                                                'extra': {'copyrightId': f'C{i}'}}}), range(4)))
check('different identities are never merged', migu_fake.calls == 4, f'calls={migu_fake.calls}')
migu_fake.delay = 0.0

# ---- D: cooldown ----
print('[D] upstream 429 cooldown')
fake.fail = AdapterError(429, 'qq: upstream rate limited (qq:relay.yuanli)', retry_after=7)
st, b, headers = post(base, '/v2/playback/resolve', {'track_ref': {'source': 'qq', 'id': 'rl1'}})
h = {k.lower(): v for k, v in headers.items()}
check('429 surfaces as HTTP 429 envelope', st == 429 and b.get('code') == 429, f'status={st}')
check('upstream 429 classified separately from local limits', h.get('x-ratelimit-scope') == 'upstream',
      f"scope={h.get('x-ratelimit-scope')}")
check('Retry-After is preserved', h.get('retry-after') == '7', f"retry={h.get('retry-after')}")
fake.fail = None
st, b, _ = post(base, '/v2/playback/resolve', {'track_ref': {'source': 'qq', 'id': 'rl1'}})
check('429 is never cached as success', st == 200 and fake.calls >= 3, f'status={st} calls={fake.calls}')

# health-level: logical name cooling is host-agnostic and blocks every alias
health = ParserHealth(fail_threshold=3, cooldown_s=60)
wait = health.record_throttle('kuwo:relay.haitangw', retry_after=2, error='HTTP 429')
check('record_throttle keeps Retry-After', 1.9 <= wait <= 2.1, f'wait={wait}')
check('cooldown is shared by every alias of the logical name', health.cooldown_remaining('kuwo:relay.haitangw') > 0)
check('a different logical parser is not cooled', health.cooldown_remaining('kuwo:relay.xcloudv') == 0)


class Entry:
    '''counts requests per "host" while sharing ONE logical cooldown name'''

    def __init__(self):
        self.hits = []

    def primary(self):
        self.hits.append('primary')
        raise Fake429('Retry-After', '5')

    def mirror(self):
        self.hits.append('mirror')
        return 'mirror-result'


class Fake429(Exception):
    def __init__(self, header, value):
        super().__init__('429 Too Many Requests')
        self.response = type('R', (), {'status_code': 429,
                                       'headers': {'Retry-After': value}})()


class CooldownAdapter(SourceAdapter):
    source_key = 'cd'

    def _build_client(self):
        class Dummy:
            pass
        return Dummy()


async def case_cooldown_adapter():
    st = Settings(env={'MAX_CONCURRENCY': '2', 'HARD_TIMEOUT_S': '5'})
    h = ParserHealth(fail_threshold=3, cooldown_s=60)
    adapter = CooldownAdapter(st, h)
    entry = Entry()
    first = None
    try:
        await adapter.run_guarded('cd:primary', entry.primary)
    except AdapterError as err:
        first = err
    # the "mirror" is another host of the SAME logical endpoint: zero requests
    second = None
    try:
        await adapter.run_guarded('cd:primary', entry.mirror)
    except AdapterError as err:
        second = err
    adapter.shutdown()
    return first, second, entry.hits, h


first, second, hits, h = asyncio.run(case_cooldown_adapter())
check('429 from the primary host cools the logical entry', first is not None and first.code == 429
      and first.retry_after == 5, f'code={getattr(first, "code", None)} retry={getattr(first, "retry_after", None)}')
check('no request reaches the backup host while cooling', hits == ['primary']
      and second is not None and second.code == 429, f'hits={hits}')


async def case_expiry():
    st = Settings(env={'MAX_CONCURRENCY': '2', 'HARD_TIMEOUT_S': '5'})
    h = ParserHealth(fail_threshold=3, cooldown_s=60)
    adapter = CooldownAdapter(st, h)
    h.record_throttle('cd:primary', retry_after=1)
    blocked = None
    try:
        await adapter.run_guarded('cd:primary', lambda: 'x')
    except AdapterError as err:
        blocked = err
    await asyncio.sleep(1.1)
    allowed = await adapter.run_guarded('cd:primary', lambda: 'ok')
    adapter.shutdown()
    return blocked, allowed


blocked, allowed = asyncio.run(case_expiry())
check('request is refused while cooling', blocked is not None and blocked.code == 429)
check('after the cooldown expires the entry is usable again', allowed == 'ok')

exc = Fake429('Retry-After', '9')
check('retry_after_from reads the upstream header', retry_after_from(exc) == 9.0)
check('is_rate_limited detects a 429 status', is_rate_limited(exc))

# local limiter scope
app2 = create_app(Settings(env={'API_KEY': '', 'RATE_LIMIT': '1/minute', 'TRUSTED_NETWORKS': '',
                               'UNTRUSTED_HOSTS': '', 'SERVICE_TOKENS': TOKENS}))
base2, server2 = start_app(app2)
app2.state.adapters['qq'] = FakeAdapter()
post(base2, '/v2/playback/resolve', {'track_ref': {'source': 'qq', 'id': 'a'}})
st, b, headers = post(base2, '/v2/playback/resolve', {'track_ref': {'source': 'qq', 'id': 'a'}})
h2 = {k.lower(): v for k, v in headers.items()}
check('local limiter is classified as local', st == 429 and h2.get('x-ratelimit-scope') == 'local',
      f'status={st} scope={h2.get("x-ratelimit-scope")}')
server2.should_exit = True

# ---- E: scoped invalidation ----
print('[E] scoped invalidation')
inv_body = {'track_ref': {'source': 'qq', 'id': 'inv1'}, 'profile': {'quality': '320k'}}
start_calls = fake.calls
post(base, '/v2/playback/resolve', inv_body)
post(base, '/v2/playback/resolve', inv_body)
check('identity cached before invalidation', fake.calls == start_calls + 1, f'delta={fake.calls - start_calls}')
st, b, _ = post(base, '/v2/cache/invalidate', inv_body, token='play')
check('playback-only token cannot invalidate -> 403', st == 403 and b.get('code') == 403, f'status={st}')
st, b, _ = post(base, '/v2/cache/invalidate', inv_body, token='inv')
check('invalidation scope evicts the exact identity', st == 200 and (b.get('data') or {}).get('invalidated') is True,
      f'status={st} data={b.get("data")}')
post(base, '/v2/playback/resolve', inv_body)
check('invalidated identity re-resolves exactly once', fake.calls == start_calls + 2, f'delta={fake.calls - start_calls}')

other = {'track_ref': {'source': 'qq', 'id': 'inv2'}, 'profile': {'quality': '320k'}}
post(base, '/v2/playback/resolve', other)
calls_before = fake.calls
st, b, _ = post(base, '/v2/cache/invalidate',
                {'track_ref': {'source': 'qq', 'id': 'inv-never-resolved'}, 'profile': {'quality': '320k'}},
                token='inv')
check('invalidating an uncached identity reports a miss (no wildcard)',
      (b.get('data') or {}).get('invalidated') is False, f'data={b.get("data")}')
post(base, '/v2/playback/resolve', other)
check('unrelated identity cache is untouched', fake.calls == calls_before, f'delta={fake.calls - calls_before}')

st, b, _ = post(base, '/v2/playback/resolve', {'track_ref': {'source': 'qq', 'id': 'inv4'},
                                               'profile': {'quality': '320k'}, 'freshness': 'sometimes'})
check('unknown freshness is a request error', st == 400 and b.get('code') == 400, f'status={st}')

server.should_exit = True

print(f'\nRESULT: {PASSED} passed, {len(FAILED)} failed' + (f' -> {FAILED}' if FAILED else ''))
sys.exit(1 if FAILED else 0)
