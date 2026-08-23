'''stage-2 smoke test: real-chain endpoint verification against a running server'''
import sys
import json
import time
import base64
import urllib.request
import urllib.parse

args = sys.argv[1:]
BASE = args[0] if args else 'http://127.0.0.1:3003'
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


def check(name, cond, detail=''):
    global PASSED
    print(f'  {"PASS" if cond else "FAIL"} {name} {detail}')
    if cond: PASSED += 1
    else: FAILED.append(name)


def find_song_id(source, keywords):
    body, _ = get(f'/{source}/search?keywords={urllib.parse.quote(keywords)}&limit=5')
    items = (body.get('data') or {}).get('items') or []
    return (items[0] or {}).get('id'), (items[0] or {}).get('name')


print(f'== smoke against {BASE} ==')

b, ms = get('/healthz'); check('healthz up', b['code'] == 200 and b['data']['status'] == 'up', f'{ms}ms')
b, _ = get('/status'); check('status shape', 'sources' in b['data'])

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


for source, keywords in [('kuwo', '林俊杰 江南'), ('qq', '邓紫棋 光年之外')]:
    sid, sname = find_song_id(source, keywords)
    check(f'{source} search', bool(sid), f'id={sid} name={sname}')
    b, ms = get_retry(f'/{source}/song/url?id={sid}&quality=auto')
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
    b2, ms2 = get(f'/{source}/song/url?id={sid}&quality=auto', timeout=10)
    check(f'{source} url cached', (b2.get('data') or {}).get('cached') is True, f'{ms2}ms')
    b3, ms3 = get(f'/{source}/song/info?id={sid}')
    check(f'{source} song/info', b3['code'] == 200 and bool((b3.get('data') or {}).get('name')), f'{ms3}ms')
    b4, ms4 = get(f'/{source}/lyric?id={sid}', timeout=30)
    lyric_text = (b4.get('data') or {}).get('lyric') or ''
    check(f'{source} lyric non-empty', len(lyric_text) > 50, f'{ms4}ms len={len(lyric_text)}')

b, _ = get('/qq/song/url?id=0039MnYb0qxYhV&quality=flac')
check('lossless gated by default', b['code'] == 403, f"code={b['code']}")

print(f'\nRESULT: {PASSED} passed, {len(FAILED)} failed' + (f' -> {FAILED}' if FAILED else ''))
sys.exit(1 if FAILED else 0)
