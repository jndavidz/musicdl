'''offline smoke: cross-cutting contracts verified WITHOUT any upstream or NAS dependency.
   Starts the real app in-process (uvicorn thread) with controlled settings; swaps in a
   FakeAdapter to exercise routing/caching/envelope through real HTTP, checks the auth
   guard against a key-protected instance, and cross-checks quality tag tables between
   webgui and the server adapters via ast (no import side effects).
   Run: XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_offline.py'''
import ast
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
from server.quality import ALIASES, resolve as resolve_quality
from server.app import create_app
from server.cache import TTLCache

PASSED, FAILED = 0, []


def check(name, cond, detail=''):
    global PASSED
    print(f'  {"PASS" if cond else "FAIL"} {name} {detail}')
    if cond: PASSED += 1
    else: FAILED.append(name)


def _free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


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


def raw(base, path, timeout=10, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers or {}), timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {}


def raw_h(base, path, timeout=10, headers=None):
    '''like raw() but also returns response headers (for X-RateLimit assertions)'''
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers or {}), timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8')), dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8')), dict(e.headers)
        except Exception:
            return e.code, {}, {}


def raw_text(base, path, timeout=10):
    '''plain-text getter (metrics exposition is not enveloped JSON)'''
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as resp:
            return resp.status, resp.read().decode('utf-8'), resp.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='ignore'), ''


class FakeAdapter:
    '''records calls, returns canned url data — lets us assert route semantics
       (alias normalization, cache keys, cached flags) through the real HTTP seam.'''
    source_key = 'qq'

    def __init__(self):
        self.calls = []

    async def search_items(self, keywords, limit, page=1):
        self.calls.append(('search', keywords, limit, page))
        return [{'id': 'f1', 'name': 'fake song', 'singer': None, 'album': None, 'ext': 'mp3',
                 'size_bytes': None, 'duration_s': 180, 'cover': None, 'source': self.source_key}]

    async def song_url(self, song_id, quality, **kw):
        self.calls.append(('url', song_id, quality, kw))
        return {'id': song_id, 'source': self.source_key, 'quality': quality,
                'url': 'http://example.test/a.mp3', 'ext': 'mp3', 'size_bytes': 1000,
                'bitrate_kbps': 320, 'duration_s': 180, 'cover': None, 'verified': True,
                'headers': {}, 'parser': 'fake', 'elapsed_ms': 1, 'cached': False}

    async def song_info(self, song_id, **kw):
        self.calls.append(('info', song_id, kw))
        return {'id': song_id, 'source': self.source_key, 'name': 'fake song', 'singer': None,
                'album': None, 'duration_s': 180, 'cover': None, 'raw': {}}

    async def lyric(self, song_id, **kw):
        self.calls.append(('lyric', song_id, kw))
        return 'x' * 120

    async def album(self, name, artist='', page=1):
        self.calls.append(('album', name, artist, page))
        return {'albums': [{'id': 'a1', 'name': name, 'artist': artist or None, 'size': 3,
                            'cover': None, 'source': self.source_key, 'extra': {}}],
                'items': [{'id': f'f{i}', 'name': f'track{i}', 'singer': None, 'album': name,
                           'ext': 'mp3', 'size_bytes': None, 'duration_s': 180, 'cover': None,
                           'source': self.source_key, 'track_no': i} for i in (1, 2, 3)]}


print('== offline smoke ==')

# ---- section 1: app state seam + envelope/routing semantics via FakeAdapter ----
app = create_app(Settings(env={'API_KEY': ''}))
base, server = start_app(app)
fake = FakeAdapter()
app.state.adapters['qq'] = fake

st, b = raw(base, '/healthz')
check('healthz envelope shape', st == 200 and b['code'] == 200 and set(b) >= {'code', 'msg', 'data', 'timestamp'})
st, b = raw(base, '/nope/search?keywords=x')
check('unknown source: HTTP 200 + code 404 (business miss)', st == 200 and b['code'] == 404, f"code={b.get('code')}")
st, b = raw(base, '/qq/search?keywords=test')
check('search via fake adapter', st == 200 and (b['data'].get('items') or [{}])[0].get('id') == 'f1')
check('search cached (adapter called once)', len(fake.calls) == 1 and fake.calls[0][0] == 'search')
raw(base, '/qq/search?keywords=test')
check('search cache hit on repeat', len(fake.calls) == 1)

st, b = raw(base, '/qq/song/url?id=f1&quality=SUPER')
check('quality alias normalized (SUPER->320k)', st == 200 and b['data']['quality'] == '320k')
st, b = raw(base, '/qq/song/url?id=f1&quality=weird')
check('unknown quality falls back to auto', st == 200 and b['data']['quality'] == 'auto')
st, b = raw(base, '/qq/song/url?id=f1&quality=320k')
check('song/url cached flag on hit', (b['data'] or {}).get('cached') is True)
url_calls = [c for c in fake.calls if c[0] == 'url']
check('url cache keyed by normalized quality (one resolve)', len(url_calls) == 2, f'resolves={len(url_calls)}')
st, b = raw(base, '/qq/lyric?id=f1')
check('lyric envelope', st == 200 and len((b['data'] or {}).get('lyric') or '') > 50)
st, b = raw(base, '/qq/lyric?id=f1')
check('lyric cached flag on hit', (b['data'] or {}).get('cached') is True)

# P6 album: ordered tracks via adapter album(); unsupported source -> 501 envelope
st, b = raw(base, '/qq/album?name=%E5%8F%B6%E6%83%A0%E7%BE%8E&artist=%E5%91%A8%E6%9D%B0%E4%BC%A6')
nos = [i.get('track_no') for i in (b['data'] or {}).get('items') or []]
check('album via fake adapter (ordered track_no 1..n)', st == 200 and b['code'] == 200 and nos == [1, 2, 3], f'nos={nos}')
check('album cached (adapter called once)', len([c for c in fake.calls if c[0] == 'album']) == 1)
st, b = raw(base, '/qianqian/album?name=x')
check('album unsupported source -> 501 envelope (HTTP 501, not business-miss class)', st == 501 and b['code'] == 501, f"status={st} code={b.get('code')}")

# real qianqian adapter lossless gate: raises before any network when ENABLE_LOSSLESS=false
st, b = raw(base, '/qianqian/song/url?id=whatever&quality=flac')
check('lossless gate 403 (offline, pre-network)', st == 200 and b['code'] == 403, f"code={b.get('code')}")

server.should_exit = True

# ---- section 2: auth guard (isolated settings: key set, no trusted networks) ----
app2 = create_app(Settings(env={'API_KEY': 'k', 'TRUSTED_NETWORKS': '', 'UNTRUSTED_HOSTS': ''}))
base2, server2 = start_app(app2)
app2.state.adapters['qq'] = FakeAdapter()
st, _ = raw(base2, '/healthz')
check('healthz exempt from api key', st == 200)
st, b = raw(base2, '/qq/search?keywords=x')
check('missing key -> 401', st == 401 and b.get('code') == 401)
st, b = raw(base2, '/qq/search?keywords=x', headers={'X-API-Key': 'k'})
check('x-api-key accepted', st == 200)
import base64 as _b64
st, b = raw(base2, '/qq/search?keywords=x', headers={'Authorization': 'Basic ' + _b64.b64encode(b'k:').decode()})
check('basic auth accepted (plugin pattern)', st == 200)
server2.should_exit = True

# ---- section 3: TTLCache semantics (expiry + capacity eviction) ----
# interface clamps: ttl >= 1s, max_items >= 16 — tests use real values
c = TTLCache(ttl_seconds=1, max_items=16)
c.set('a', 1)
check('cache set/get', c.get('a') == 1)
time.sleep(1.1)
check('cache expires after ttl', c.get('a') is None)
c2 = TTLCache(ttl_seconds=60, max_items=16)
for k in 'abcdefghijklmnopq':
    c2.set(k, k)
check('cache evicts under capacity pressure', c2.get('a') is None and c2.get('q') == 'q')
check('cache keeps recent entries after eviction', c2.get('p') is not None)
st = c2.stats()
check('cache stats expose hit/miss counters', st['hits'] >= 2 and st['misses'] >= 1
      and st['hit_rate'] is not None and 0 < st['hit_rate'] < 1, f"hits={st['hits']} misses={st['misses']}")

# ---- section 4: quality tier domain invariants (server/quality.py, ADR-0003) ----
check('alias: MusicFree four tiers', ALIASES['low'] == '128k' and ALIASES['standard'] == '192k'
      and ALIASES['high'] == '320k' and ALIASES['super'] == '320k')
check('alias: surround5.1 spellings collapse', ALIASES['surround5.1'] == 'surround51'
      and ALIASES['5.1'] == 'surround51')
check('alias: auto maps to itself', ALIASES['auto'] == 'auto')
check('192k rule: netease keeps real tier', resolve_quality('netease', '192k') == '192k')
check('192k rule: bilibili snaps to 320k (was: fell to auto)', resolve_quality('bilibili', '192k') == '320k')
check('192k rule: kuwo/qq snap to 320k', resolve_quality('kuwo', '192k') == '320k'
      and resolve_quality('qq', '192k') == '320k')
check('whitelist: qq has no master tier -> auto', resolve_quality('qq', 'master') == 'auto')
check('whitelist: kuwo keeps master/surround51', resolve_quality('kuwo', 'surround5.1') == 'surround51'
      and resolve_quality('kuwo', 'master') == 'master')
check('resolve is idempotent', resolve_quality('qq', resolve_quality('qq', 'SUPER')) == '320k')

# ---- section 5: dual-side quality tag tables stay in sync (ast, no import) ----
def _extract_dict(path, varname):
    tree = ast.parse(open(path, encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == varname:
                    return ast.literal_eval(node.value)
    return None

webgui_tier = _extract_dict(os.path.join(REPO, 'examples', 'musicdlwebgui', 'app.py'), 'PLATFORM_TAG_TIER')
server_tag = _extract_dict(os.path.join(REPO, 'server', 'adapters', 'kuwo.py'), 'ZHENPIN_BR')
if webgui_tier and server_tag:
    # known vocabulary divergence (batch-2 quality module will unify it):
    # server calls the 2000kflac tier 'flac', webgui calls it 'lossless'
    webgui_alias = {'flac': 'lossless'}
    drift = {tier: (tag, webgui_tier.get(tag)) for tier, tag in server_tag.items()
             if webgui_tier.get(tag) not in {tier, webgui_alias.get(tier)}}
    check('webgui/server kuwo tag tables consistent', not drift, f'drift={drift or "none"}')
else:
    check('webgui/server kuwo tag tables consistent', False,
          f'extract failed: webgui={bool(webgui_tier)} server={bool(server_tag)}')

# ---- section 6: /metrics exposition + untrusted-only rate limit (roadmap C1/C2) ----
app3 = create_app(Settings(env={'API_KEY': '', 'RATE_LIMIT': '3/minute', 'TRUSTED_NETWORKS': ''}))
base3, server3 = start_app(app3)
app3.state.adapters['qq'] = FakeAdapter()

for _ in range(3):
    raw(base3, '/qq/search?keywords=x')
st4, b4, h4 = raw_h(base3, '/qq/search?keywords=x')
h4 = {k.lower(): v for k, v in h4.items()}
check('untrusted 4th request -> 429 envelope', st4 == 429 and b4.get('code') == 429, f'status={st4} code={b4.get("code")}')
check('429 carries X-RateLimit + Retry-After', h4.get('x-ratelimit-limit') == '3' and h4.get('retry-after') in ('59', '60')
      and h4.get('x-ratelimit-remaining') == '0', f"limit={h4.get('x-ratelimit-limit')} retry={h4.get('retry-after')}")
st, _ = raw(base3, '/healthz')
check('healthz exempt from rate limit', st == 200)

st, body, ctype = raw_text(base3, '/metrics')
check('metrics: 200 text exposition', st == 200 and 'text/plain' in ctype, f'ctype={ctype}')
for fragment in ('# TYPE kwqq_request_latency_seconds histogram', 'kwqq_requests_total', 'kwqq_cache_hit_rate{cache="url"}'):
    check(f'metrics: exposes {fragment.split()[2] if fragment.startswith("#") else fragment}',
          fragment in body)
check('metrics: 429 recorded on request counter', 'kwqq_requests_total{endpoint="other",status="429"}' in body)
server3.should_exit = True

app4 = create_app(Settings(env={'API_KEY': '', 'RATE_LIMIT': '1/minute', 'TRUSTED_NETWORKS': '127.0.0.0/8'}))
base4, server4 = start_app(app4)
app4.state.adapters['qq'] = FakeAdapter()
codes = [raw(base4, '/qq/search?keywords=x')[0] for _ in range(5)]
check('trusted client bypasses rate limit', codes == [200] * 5, f'codes={codes}')
server4.should_exit = True

print(f'\nRESULT: {PASSED} passed, {len(FAILED)} failed' + (f' -> {FAILED}' if FAILED else ''))
sys.exit(1 if FAILED else 0)
