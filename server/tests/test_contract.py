'''offline contract tests for the v2 managed-playback seam (no upstream, no NAS).
   Sections:
     A. TrackRef canonical identity + per-source required fields (K-01)
     B. scoped service credentials: v1 download key never grants v2 scopes (K-01)
     C. POST /v2/playback/resolve through the real HTTP seam with identity fakes (K-01)
   Run: XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_contract.py'''
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

from server import trackref
from server.config import Settings
from server.app import create_app
from server.adapters import AdapterError

PASSED, FAILED = 0, []


def check(name, cond, detail=''):
    global PASSED
    print(f'  {"PASS" if cond else "FAIL"} {name} {detail}')
    if cond: PASSED += 1
    else: FAILED.append(name)


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


def call(base, path, method='GET', body=None, headers=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {}


class IdentityFake:
    '''identity-aware stand-in for an adapter: records (id, quality, identity kwargs)
       and emulates the per-source identity contract of the real adapters.'''

    def __init__(self, source_key, ext='mp3', bitrate=320, ekey=None, probe_ok=True):
        self.source_key = source_key
        self.ext, self.bitrate, self.ekey, self.probe_ok = ext, bitrate, ekey, probe_ok
        self.calls = []

    def identity_kwargs(self, extra):
        if self.source_key == 'migu':
            hit = (extra or {}).get('copyrightId')
            if not hit: raise AdapterError(400, 'migu track_ref requires extra.copyrightId')
            return {'copyright_id': str(hit)}
        if self.source_key == 'bilibili':
            return {'cid': (extra or {}).get('cid'), 'page': (extra or {}).get('page')}
        return {}

    def identity_out(self, requested, result):
        out = dict(requested or {})
        if result.get('resolved_cid'): out['cid'] = str(result['resolved_cid'])
        if result.get('resolved_page'): out['page'] = int(result['resolved_page'])
        return out

    async def song_url(self, song_id, quality, **kw):
        self.calls.append((str(song_id), quality, kw))
        out = {'id': str(song_id), 'source': self.source_key, 'quality': quality,
               'url': f'http://example.test/{song_id}.{self.ext}', 'ext': self.ext,
               'size_bytes': 1024 * 1024, 'bitrate_kbps': self.bitrate, 'duration_s': 180,
               'cover': None, 'verified': self.probe_ok, 'headers': {}, 'parser': 'fake',
               'ekey': self.ekey, 'elapsed_ms': 1, 'cached': False}
        if self.source_key == 'bilibili':
            out['resolved_cid'] = str(kw.get('cid') or 1111)
            out['resolved_page'] = kw.get('page') or 1
        return out

    async def song_info(self, song_id, **kw):
        return {'id': str(song_id), 'source': self.source_key, 'name': 'fake',
                'singer': None, 'album': None, 'duration_s': 180, 'cover': None, 'raw': {}}


TOKENS = json.dumps({
    'play-tok': {'scopes': ['playback:issue'], 'generation': 1},
    'inv-tok': {'scopes': ['cache:invalidate'], 'generation': 1},
    'prep-tok': {'scopes': ['playback:issue', 'media:prepare'], 'generation': 1},
    'play-tok-g2': {'scopes': ['playback:issue'], 'generation': 2},
})


def v2(base, ref, quality='320k', token='play-tok', **extra):
    body = {'track_ref': ref, 'profile': {'quality': quality, **extra}}
    headers = {'X-Service-Token': token} if token else {}
    return call(base, '/v2/playback/resolve', 'POST', body, headers)


print('== v2 contract offline ==')

# ---- A: TrackRef identity rules ----
print('[A] TrackRef identity + canonical encoding')
r1 = trackref.make_ref('migu', '600902', {'copyrightId': 'C1'})
check('migu ref keeps copyrightId', r1['extra'] == {'copyrightId': 'C1'})
for label, args in (('migu without copyrightId', ('migu', '600902', {})),
                    ('bilibili without cid/page', ('bilibili', 'BV1xx', {})),
                    ('blank id', ('qq', '  ', {})),
                    ('bad cid', ('bilibili', 'BV1xx', {'cid': 'abc'}))):
    try:
        trackref.make_ref(*args)
        check(f'{label} -> RefError', False)
    except trackref.RefError:
        check(f'{label} -> RefError', True)
check('bilibili page normalized to int', trackref.make_ref('bilibili', 'BV1', {'page': '2'})['extra'] == {'page': 2})
try:
    trackref.make_ref('nope', 'x', {}, sources=('qq', 'kuwo'))
    check('unknown source -> RefError', False)
except trackref.RefError:
    check('unknown source -> RefError', True)

a = trackref.make_ref('bilibili', 'BV1', {'page': 2, 'cid': '99'})
b = trackref.make_ref('bilibili', 'BV1', {'cid': '99', 'page': '2'})   # key order differs
check('canonical stable across key order', trackref.canonical(a) == trackref.canonical(b))
c = trackref.make_ref('bilibili', 'BV1', {'page': 3, 'cid': '99'})
check('different page -> different digest', trackref.digest(a) != trackref.digest(c))
m1 = trackref.make_ref('migu', '600902', {'copyrightId': 'C1'})
m2 = trackref.make_ref('migu', '600902', {'copyrightId': 'C2'})
check('same migu id different copyright -> different digest', trackref.digest(m1) != trackref.digest(m2))
noise = trackref.make_ref('qq', 'song1', {'ekey': 'x', 'url': 'http://evil'})
check('non-identity extra is dropped', noise['extra'] == {} and trackref.digest(noise) == trackref.digest(trackref.make_ref('qq', 'song1')))
policy = {'quality': '320k', 'target': 'device'}
k1 = trackref.cache_key(a, policy, 1)
check('cache key carries identity/policy/generation',
      k1 != trackref.cache_key(c, policy, 1) and k1 != trackref.cache_key(a, {'quality': '128k', 'target': 'device'}, 1)
      and k1 != trackref.cache_key(a, policy, 2) and k1.startswith('v2:'))

# ---- B: scoped credentials ----
print('[B] scoped service credentials')
app = create_app(Settings(env={'API_KEY': 'download-key', 'TRUSTED_NETWORKS': '', 'UNTRUSTED_HOSTS': '',
                              'SERVICE_TOKENS': TOKENS, 'RATE_LIMIT': ''}))
base, server = start_app(app)
qfake, mfake, bfake = IdentityFake('qq'), IdentityFake('migu'), IdentityFake('bilibili', ext='mp3', bitrate=192)
app.state.adapters.update({'qq': qfake, 'migu': mfake, 'bilibili': bfake})

st, b = v2(base, {'source': 'qq', 'id': 's1'}, token='')
check('v2 without service token -> 401', st == 401 and b.get('code') == 401, f'status={st} code={b.get("code")}')
st, b = v2(base, {'source': 'qq', 'id': 's1'}, token='download-key')
check('download API key does NOT grant playback scope -> 403', st == 403 and b.get('code') == 403, f'status={st}')
st, b = v2(base, {'source': 'qq', 'id': 's1'}, token='inv-tok')
check('token without playback:issue -> 403', st == 403 and b.get('code') == 403, f'status={st}')

# ---- C: resolve through HTTP ----
print('[C] POST /v2/playback/resolve')
st, b = v2(base, {'source': 'migu', 'id': '600902'})
check('migu ref missing copyrightId -> 400', st == 400 and b.get('code') == 400, f'status={st} msg={b.get("msg")}')
st, b = v2(base, {'source': 'bilibili', 'id': 'BV1xx'})
check('bilibili ref missing cid/page -> 400', st == 400 and b.get('code') == 400, f'status={st} msg={b.get("msg")}')

st, b = v2(base, {'source': 'migu', 'id': '600902', 'extra': {'copyrightId': 'C1'}})
d = b.get('data') or {}
check('migu resolve ok', st == 200 and d.get('url', '').endswith('.mp3'), f'status={st}')
check('identity echoed in track_ref', (d.get('track_ref') or {}).get('extra') == {'copyrightId': 'C1'})
check('resolved_source equals actual source', d.get('resolved_source') == 'migu')
check('requested_quality echoes caller spelling', d.get('requested_quality') == '320k')
check('v2 never claims full verification', d.get('verified') is False
      and (d.get('verification') or {}).get('requires_byte_verification') is True)
check('cache_expires_at present', isinstance(d.get('cache_expires_at'), int))
v2(base, {'source': 'migu', 'id': '600902', 'extra': {'copyrightId': 'C1'}})
check('same migu identity -> cache hit, one resolve', len(mfake.calls) == 1, f'calls={len(mfake.calls)}')
st, b = v2(base, {'source': 'migu', 'id': '600902', 'extra': {'copyrightId': 'C2'}})
check('different copyrightId -> separate resolve', len(mfake.calls) == 2 and b['code'] == 200)
check('identity kwargs reached the adapter', mfake.calls[-1][2] == {'copyright_id': 'C2'})
st, b = v2(base, {'source': 'migu', 'id': '600902', 'extra': {'copyrightId': 'C1'}}, quality='128k')
check('different policy -> separate resolve', len(mfake.calls) == 3 and b['code'] == 200,
      f"calls={len(mfake.calls)} status={st} code={b.get('code')} msg={str(b.get('msg'))[:80]}")
st, b = v2(base, {'source': 'migu', 'id': '600902', 'extra': {'copyrightId': 'C1'}}, token='play-tok-g2')
check('new credential generation -> separate resolve', len(mfake.calls) == 4 and b['code'] == 200,
      f"calls={len(mfake.calls)} status={st} code={b.get('code')}")

st, b = v2(base, {'source': 'bilibili', 'id': 'BV1', 'extra': {'page': 2}})
d = b.get('data') or {}
check('bilibili page 2 resolves and echoes verified cid', st == 200
      and (d.get('track_ref') or {}).get('extra') == {'cid': '1111', 'page': 2},
      f"extra={(d.get('track_ref') or {}).get('extra')}")
check('bilibili identity kwargs carry page', bfake.calls[-1][2] == {'cid': None, 'page': 2})
st, b = v2(base, {'source': 'bilibili', 'id': 'BV1', 'extra': {'page': 3}})
check('different page -> separate resolve', len(bfake.calls) == 2, f'calls={len(bfake.calls)}')
st, b = v2(base, {'source': 'bilibili', 'id': 'BV1', 'extra': {'page': 2}})
check('same page -> cache hit', len(bfake.calls) == 2)

# v1 must stay untouched and keep its own cache namespace
qfake.source_key = 'qq'
st, b = call(base, '/qq/song/url?id=s1&quality=320k', headers={'X-API-Key': 'download-key'})
check('v1 song/url still works with the download key', st == 200 and b['code'] == 200)
st, b = call(base, '/qq/song/url?id=s1&quality=320k', headers={'X-API-Key': 'download-key'})
check('v1 url cache still keyed independently', b['data'].get('cached') is True)
st, b = call(base, '/status', headers={'X-API-Key': 'download-key'})
check('status exposes the v2 cache', 'v2_url' in ((b.get('data') or {}).get('caches') or {}))
st, b = call(base, '/qq/song/info?id=s1', headers={'X-API-Key': 'download-key'})
check('v1 song/info unaffected', st == 200 and b.get('code') == 200, f'status={st}')

# ---- D: strict playback profile (K-02) ----
print('[D] strict playback profile')
flac = IdentityFake('kuwo', ext='flac', bitrate=1000)
aac = IdentityFake('qianqian', ext='m4a', bitrate=192)
enc = IdentityFake('kugou', ext='mflac', bitrate=2000, ekey='SECRET-KEY')
fast = IdentityFake('netease', ext='mp3', bitrate=640)
down = IdentityFake('qq', ext='mp3', bitrate=192)


class ThinFake(IdentityFake):
    '''mp3 candidate with no bitrate/size/duration evidence at all'''
    async def song_url(self, song_id, quality, **kw):
        out = await super().song_url(song_id, quality, **kw)
        out.update(bitrate_kbps=None, size_bytes=None, duration_s=None)
        return out


app.state.adapters.update({'kuwo': flac, 'qianqian': aac, 'kugou': enc, 'netease': fast,
                           'qq': down, 'bilibili': ThinFake('bilibili', ext='mp3')})

st, b = v2(base, {'source': 'kuwo', 'id': 'k1'})
check('flac never reaches managed playback -> 415', st == 415 and b.get('code') == 415, f'status={st} msg={b.get("msg")}')
st, b = v2(base, {'source': 'kugou', 'id': 'e1'})
check('encrypted ekey candidate -> 415', st == 415 and b.get('code') == 415, f'status={st} msg={b.get("msg")}')
st, b = v2(base, {'source': 'netease', 'id': 'f1'})
check('mp3 claim above 320k -> 415', st == 415 and b.get('code') == 415, f'status={st} msg={b.get("msg")}')
st, b = v2(base, {'source': 'qianqian', 'id': 'a1'})
check('AAC direct delivery (target=device) -> 415', st == 415 and b.get('code') == 415, f'status={st} msg={b.get("msg")}')
st, b = v2(base, {'source': 'qianqian', 'id': 'a1'}, target='media_prepare')
check('media_prepare without media:prepare scope -> 403', st == 403 and b.get('code') == 403, f'status={st}')
st, b = v2(base, {'source': 'qianqian', 'id': 'a1'}, token='prep-tok', target='media_prepare')
d = b.get('data') or {}
check('Songloft prep scope: AAC admitted as transcode input', st == 200 and d.get('codec') == 'm4a'
      and (d.get('verification') or {}).get('requires_transcode') is True
      and (d.get('verification') or {}).get('requires_byte_verification') is True
      and d.get('ready') is False, f'status={st} ready={d.get("ready")}')
check('AAC input is not claimed as a delivered quality', d.get('delivered_quality') is None)
before = len(flac.calls)
v2(base, {'source': 'kuwo', 'id': 'k1'})
check('rejected flac candidate never cached', len(flac.calls) == before + 1, f'calls={len(flac.calls)}')
st, b = v2(base, {'source': 'qq', 'id': 'd1'})
d = b.get('data') or {}
check('honest downgrade: 320k request -> 192k delivery', st == 200 and d.get('delivered_quality') == '192k'
      and 'downgraded' in (d.get('fallback_reason') or '') and d.get('ready') is True,
      f"delivered={d.get('delivered_quality')} reason={d.get('fallback_reason')}")
st, b = v2(base, {'source': 'bilibili', 'id': 'BV1', 'extra': {'page': 1}})
d = b.get('data') or {}
check('insufficient evidence -> ready=false + byte verification required', st == 200
      and d.get('ready') is False and (d.get('verification') or {}).get('requires_byte_verification') is True
      and 'insufficient evidence' in (d.get('fallback_reason') or ''), f"reason={d.get('fallback_reason')}")
st, b = v2(base, {'source': 'qq', 'id': 'd1'}, quality='master')
check('lossless request is rejected, not rewritten to auto -> 400', st == 400 and b.get('code') == 400, f'status={st} msg={b.get("msg")}')
st, b = v2(base, {'source': 'qq', 'id': 'd1'}, quality='weird')
check('unknown quality spelling -> 400', st == 400 and b.get('code') == 400, f'status={st}')
st, b = v2(base, {'source': 'qq', 'id': 'd1'}, target='nope')
check('unknown profile target -> 400', st == 400 and b.get('code') == 400, f'status={st}')
# v1 keeps its own verified/quality contract untouched (v2 reports verified=false)
st, b = call(base, '/qq/song/url?id=d1&quality=320k', headers={'X-API-Key': 'download-key'})
d = b.get('data') or {}
check('v1 verified/quality contract unchanged', st == 200 and b.get('code') == 200
      and d.get('verified') is True and d.get('quality') == '320k',
      f"status={st} verified={d.get('verified')} quality={d.get('quality')}")

server.should_exit = True

print(f'\nRESULT: {PASSED} passed, {len(FAILED)} failed' + (f' -> {FAILED}' if FAILED else ''))
sys.exit(1 if FAILED else 0)
