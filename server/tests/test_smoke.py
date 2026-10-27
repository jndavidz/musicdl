'''stage-2 smoke test: real-chain endpoint verification against a running server'''
import sys
import json
import time
import base64
import urllib.request
import urllib.parse

args = sys.argv[1:]
BASE = args[0] if args and not args[0].startswith('--') else 'http://127.0.0.1:3003'
ALL = '--all' in args   # full tier: adds checks that need NAS containers (kugou-api / ncm-api)
AUTH = None
if '--auth' in args:
    AUTH = base64.b64encode(args[args.index('--auth') + 1].encode()).decode()
PASSED, FAILED = 0, []


def get(path, timeout=30):
    t0 = time.perf_counter()
    req = urllib.request.Request(BASE + path)
    if AUTH: req.add_header('Authorization', f'Basic {AUTH}')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode('utf-8'))
    return body, round((time.perf_counter() - t0) * 1000)


def raw(path, timeout=30):
    '''returns (status, body_bytes) without raising on upstream 4xx/5xx —
       passthrough endpoints relay upstream errors verbatim by design.'''
    req = urllib.request.Request(BASE + path)
    if AUTH: req.add_header('Authorization', f'Basic {AUTH}')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(name, cond, detail=''):
    global PASSED
    print(f'  {"PASS" if cond else "FAIL"} {name} {detail}')
    if cond: PASSED += 1
    else: FAILED.append(name)


def find_song_id(source, keywords):
    body, _ = get(f'/{source}/search?keywords={urllib.parse.quote(keywords)}&limit=5')
    items = (body.get('data') or {}).get('items') or []
    first = items[0] if items else {}   # empty upstream result must degrade to a FAIL, not crash
    return first.get('id'), first.get('name'), (first.get('extra') or {})


print(f'== smoke against {BASE} ==')

b, ms = get('/healthz'); check('healthz up', b['code'] == 200 and b['data']['status'] == 'up', f'{ms}ms')
b, _ = get('/status'); check('status shape', 'parsers' in b['data'])

def get_retry(path, timeout=45, retries=1):
    '''one retry: first failure cools down dead parsers, second attempt usually succeeds'''
    last = None
    for i in range(1 + retries):
        try:
            return get(path, timeout=timeout)
        except Exception as e:
            last = e
            print(f'  .. retry {i+1}/{retries} after {type(e).__name__}: {str(e)[:80]}')
    raise last


# per-source live checks. Default tier = sources reachable without NAS containers or
# account cookies (public anonymous endpoints). --all adds the NAS-container sources.
# (source, keywords, needs_copyright, has_lyric)
DEFAULT_SOURCES = [
    ('kuwo', '林俊杰 江南', False, True),
    ('qq', '邓紫棋 光年之外', False, True),
    ('migu', '周杰伦 晴天', True, False),
    ('qianqian', '林俊杰 江南', False, False),
]
ALL_SOURCES = [
    ('kugou', '林俊杰 江南', False, True),       # needs kugou-api container (NAS). Container /lyric
                                                 # stably 400s error_code 20010 (2026-10-27) —
                                                 # adapter falls back to the official lyric chain,
                                                 # so non-empty is assertable again.
    ('bilibili', '周杰伦 晴天', False, False),   # bilibili has no standard lyrics; empty is expected
]


def run_source(source, keywords, needs_copyright, has_lyric):
    sid, sname, extra = find_song_id(source, keywords)
    check(f'{source} search', bool(sid), f'id={sid} name={sname}')
    if not sid:
        return
    cr = str(extra.get('copyrightId') or '')
    if needs_copyright:
        check(f'{source} copyright in extra', bool(cr), f'copyrightId={cr or "MISSING"}')
        if not cr:
            return
    qs = f'&copyright={urllib.parse.quote(cr)}' if cr and needs_copyright else ''
    b, ms = get_retry(f'/{source}/song/url?id={sid}&quality=auto{qs}')
    d = b.get('data') or {}
    check(f'{source} song/url ok', b['code'] == 200 and bool(d.get('url')), f"{ms}ms ext={d.get('ext')} kbps={d.get('bitrate_kbps')} parser={d.get('parser')}")
    url = d.get('url') or ''
    if url.startswith('http'):
        req = urllib.request.Request(url, headers={'Range': 'bytes=0-8191', **(d.get('headers') or {})})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                sample = resp.read(1024)
                check(f'{source} url downloadable', resp.status in (200, 206) and len(sample) > 512, f'status={resp.status} bytes={len(sample)}')
        except Exception as e:
            check(f'{source} url downloadable', False, str(e)[:100])
    b2, ms2 = get(f'/{source}/song/url?id={sid}&quality=auto{qs}', timeout=10)
    check(f'{source} url cached', (b2.get('data') or {}).get('cached') is True, f'{ms2}ms')
    b3, ms3 = get(f'/{source}/song/info?id={sid}{qs}')
    check(f'{source} song/info', b3['code'] == 200 and bool((b3.get('data') or {}).get('name')), f'{ms3}ms')
    b4, ms4 = get(f'/{source}/lyric?id={sid}', timeout=30)
    lyric_text = (b4.get('data') or {}).get('lyric') or ''
    if has_lyric:
        check(f'{source} lyric non-empty', len(lyric_text) > 50, f'{ms4}ms len={len(lyric_text)}')
    else:
        check(f'{source} lyric endpoint (empty ok)', b4['code'] == 200, f'{ms4}ms')


for cfg in DEFAULT_SOURCES:
    run_source(*cfg)

# P6 album (netease-first): one call -> candidates + ordered tracks of best match
b5, ms5 = get('/netease/album?name=%E5%8F%B6%E6%83%A0%E7%BE%8E&artist=%E5%91%A8%E6%9D%B0%E4%BC%A6')
items5 = (b5.get('data') or {}).get('items') or []
nos = [i.get('track_no') for i in items5]
check('netease album ordered tracks (P6)', b5['code'] == 200 and len(items5) >= 5
      and nos == list(range(1, len(items5) + 1)), f'{ms5}ms items={len(items5)} nos[:3]={nos[:3]}')
albums5 = (b5.get('data') or {}).get('albums') or []
check('netease album artist-hint ranking', b5['code'] == 200 and albums5
      and '周杰伦' in (albums5[0].get('artist') or ''), f"first={(albums5[0] or {}).get('name')}/(albums5[0] or {}).get('artist')" if albums5 else 'none')
b6, _ = get('/kuwo/album?name=x')
check('album unsupported source -> 501 envelope', b6['code'] == 501, f"code={b6['code']}")

b, _ = get('/status')
lossless_enabled = (b.get('data') or {}).get('settings', {}).get('enable_lossless')
b, _ = get('/qq/song/url?id=0039MnYb0qxYhV&quality=flac')
# the gate must HONOR the server switch, whatever the deployment chose:
# ENABLE_LOSSLESS=false -> business miss (HTTP 200 + code 403); true -> resolvable
if lossless_enabled:
    check('lossless gate honors switch (enabled -> 200)', b['code'] == 200, f"code={b['code']}")
else:
    check('lossless gate honors switch (disabled -> 403)', b['code'] == 403, f"code={b['code']}")

st, body = raw('/kugou/api/user/logout')
check('passthrough blocked path', st == 403 and b'blocked' in body, f'status={st}')

if ALL:
    for cfg in ALL_SOURCES:
        run_source(*cfg)
    st, body = raw('/kugou/api/search?keywords=%E6%9E%97%E4%BF%8A%E6%9D%B0')
    ok_json = st == 200 and body[:1] in (b'{', b'[')
    check('kugou passthrough search', ok_json, f'status={st} bytes={len(body)}')
    st, body = raw('/netease/api/search?keywords=%E6%9E%97%E4%BF%8A%E6%9D%B0')
    ok_json = st == 200 and b'"result"' in body
    check('netease passthrough search (anonymous ok)', ok_json, f'status={st} bytes={len(body)}')
    st, body = raw('/netease/api/__no_such_endpoint__')
    # verbatim relay = upstream status passes through (ncm-api answers HTML 404 here);
    # the invariant is that OUR error handler did not wrap it as 502/504
    check('passthrough relays upstream error verbatim', st not in {502, 504} and len(body) > 0, f'status={st} bytes={len(body)}')

print(f'\nRESULT: {PASSED} passed, {len(FAILED)} failed' + (f' -> {FAILED}' if FAILED else ''))
sys.exit(1 if FAILED else 0)
