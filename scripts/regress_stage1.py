'''stage-1 regression: verify core changes are non-breaking and effective'''
import os, sys, time, json, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(PROJ, '.regress_tmp')
from musicdl.modules.sources.qq import QQMusicClient
from musicdl.modules.sources.kuwo import KuwoMusicClient
from musicdl.modules.utils import SongInfo

ok_count, fail_count = 0, []
def check(name, cond, detail=''):
    global ok_count
    if cond: ok_count += 1; print(f'  PASS {name} {detail}')
    else: fail_count.append(name); print(f'  FAIL {name} {detail}')

print('== T1: audio_link_tester_timeout configurable ==')
c = QQMusicClient(search_size_per_source=1, disable_print=True, work_dir=TMP, audio_link_tester_timeout=(2, 5))
check('tester timeout stored', c.audio_link_tester_timeout == (2, 5))
check('tester applied', getattr(c.audio_link_tester, 'timeout', None) == (2, 5), f'got {getattr(c.audio_link_tester, "timeout", None)}')

print('== T2: metamemo caches meta (qq) ==')
calls = {'n': 0}
orig_post = c.post
def counting_post(url, **kw):
    if 'songinfo' in str(kw.get('json', '')): calls['n'] += 1
    return orig_post(url, **kw)
c.post = counting_post
mid = '0039MnYb0qxYhV'
m1 = c._getsongmetainfo(mid); m2 = c._getsongmetainfo(mid)
check('meta fetched once', calls['n'] == 1, f'post-calls={calls["n"]}')
check('meta identical & deepcopied', m1 == m2 and m1 is not m2)

print('== T3: metamemo caches meta (kuwo) ==')
k = KuwoMusicClient(search_size_per_source=1, disable_print=True, work_dir=TMP)
kcalls = {'n': 0}
orig_get = k.get
def counting_get(url, **kw):
    if 'songinfoandlrc' in url or 'play_detail' in url: kcalls['n'] += 1
    return orig_get(url, **kw)
k.get = counting_get
rid = '228908'
km1 = k._getsongmetainfo(rid)
calls_after_first = kcalls['n']          # may be 1 (h5 ok) or 2 (h5 -> html fallback), both normal
km2 = k._getsongmetainfo(rid)
check('second call hits cache (zero requests)', kcalls['n'] == calls_after_first, f'first={calls_after_first} total={kcalls["n"]}')
check('meta non-empty & identical', bool(km1) and km1 == km2, f'keys={list(km1)[:5]}')

print('== T4: by-id fast path still works after changes (live) ==')
t0 = time.perf_counter()
info_qq = QQMusicClient._parsewiththirdpartapis(c, {'mid': mid}, {})
ms = round((time.perf_counter() - t0) * 1000)
# note: unbound call to reuse the counting_post instance
check('qq by-id ok', bool(info_qq.with_valid_download_url), f'{ms}ms ext={info_qq.ext}')
t0 = time.perf_counter()
info_kw = KuwoMusicClient._parsewiththirdpartapis(k, {'musicrid': f'MUSIC_{rid}'}, {})
ms = round((time.perf_counter() - t0) * 1000)
check('kuwo by-id ok', bool(info_kw.with_valid_download_url), f'{ms}ms ext={info_kw.ext}')

print(f'\nRESULT: {ok_count} passed, {len(fail_count)} failed' + (f' -> {fail_count}' if fail_count else ''))
shutil.rmtree(TMP, ignore_errors=True); shutil.rmtree(os.path.join(PROJ, '.spike_tmp'), ignore_errors=True)
sys.exit(1 if fail_count else 0)
