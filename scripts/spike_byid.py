'''
Function:
    Stage-0 Spike: verify by-id fast path via minimal search_result dict.
    - QQ:   {'mid': <songmid>}          -> QQMusicClient._parsewiththirdpartapis
    - Kuwo: {'musicrid': 'MUSIC_<id>'} -> KuwoMusicClient._parsewiththirdpartapis
    Collects per-parser success-rate & latency baseline + official low-tier endpoints test.
Usage:
    XDG_STATE_HOME=<proj>/.state python scripts/spike_byid.py --platform qq|kuwo --hot 5 --cold 5
Output:
    scripts/spike_results_<platform>.json + console summary
'''
import os
import sys
import json
import time
import argparse
import statistics
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from musicdl.modules.sources.qq import QQMusicClient
from musicdl.modules.sources.kuwo import KuwoMusicClient
from musicdl.modules.utils import AudioLinkTester

HOT_KEYWORDS = ['周杰伦 晴天', '林俊杰', '邓紫棋 光年之外', '五月天 倔强', '薛之谦 演员']
COLD_KEYWORDS = ['地下录音 小众', '昭和歌谣 翻唱', '独立后摇 demo', '方言民谣 现场', '冷门纯音乐 钢琴']


'''collect candidate ids via raw search endpoints (no parse chain)'''
def collect_ids_qq(client, keyword, limit):
    from musicdl.modules.utils.qqutils import QQMusicClientUtils, SearchType, Credential
    payload = QQMusicClientUtils.buildrequestdata(
        params={'searchid': QQMusicClientUtils.randomsearchid(), 'query': keyword, 'search_type': SearchType.SONG.value,
                'num_per_page': limit * 2, 'page_num': 1, 'highlight': 0, 'grp': 1},
        module="music.search.SearchCgiService", method="DoSearchForQQMusicMobile", credential=Credential())
    resp = client.post(QQMusicClientUtils.endpoint, data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    items = resp.json()['music.search.SearchCgiService.DoSearchForQQMusicMobile']['data']['body']['item_song']
    return [{'id': it.get('mid'), 'name': f"{it.get('title')} - {'/'.join(s.get('name','') for s in it.get('singer') or [])}", 'album': (it.get('album') or {}).get('title')} for it in items if it.get('mid')][:limit]


def collect_ids_kuwo(client, keyword, limit):
    from urllib.parse import urlencode
    rule = {"vipver": "1", "client": "kt", "ft": "music", "cluster": "0", "strategy": "2012", "encoding": "utf8",
            "rformat": "json", "mobi": "1", "issubtitle": "1", "show_copyright_off": "1", "pn": "0", "rn": str(limit * 2), "all": keyword}
    resp = client.get('http://www.kuwo.cn/search/searchMusicBykeyWord?' + urlencode(rule))
    items = resp.json().get('abslist') or []
    return [{'id': str(it.get('MUSICRID') or it.get('musicrid')).removeprefix('MUSIC_'),
             'name': f"{it.get('SONGNAME')} - {it.get('ARTIST')}", 'album': it.get('ALBUM')} for it in items if (it.get('MUSICRID') or it.get('musicrid'))][:limit]


'''wrap every third-party parser with timing/probe recording'''
def instrument(client, stats):
    def wrap(name):
        orig = getattr(client, name)
        def wrapped(search_result, request_overrides=None):
            t0 = time.perf_counter()
            try:
                result = orig(search_result, request_overrides)
                ms = (time.perf_counter() - t0) * 1000
                ok = bool(result.with_valid_download_url and result.ext in AudioLinkTester.VALID_AUDIO_EXTS)
                st = stats.setdefault(name, {'attempts': 0, 'ok': 0, 'ms': []})
                st['attempts'] += 1; st['ok'] += int(ok); st['ms'].append(ms)
                if ok: result.raw_data['spike_parser'] = name
                return result
            except Exception as err:
                st = stats.setdefault(name, {'attempts': 0, 'ok': 0, 'ms': []})
                st['attempts'] += 1; st.setdefault('errors', []).append(f'{type(err).__name__}: {err}')
                raise
        setattr(client, name, wrapped)
    return wrap


'''official low-tier direct tests (no third-party chain)'''
def official_lowtier_qq(client, song_mid):
    from musicdl.modules.utils.qqutils import QQMusicClientUtils, Credential
    results = {}
    for prefix, ext in [('M800', 'mp3'), ('M500', 'mp3')]:
        t0 = time.perf_counter()
        try:
            params = {"filename": [f"{prefix}{song_mid}{song_mid}.{ext}"], "guid": QQMusicClientUtils.randomguid(), "songmid": [song_mid], 'songtype': [0]}
            rule = QQMusicClientUtils.buildrequestdata(params=params, module="music.vkey.GetVkey", method="UrlGetVkey", credential=Credential(), common_override={"ct": "19"})
            resp = client.post(QQMusicClientUtils.endpoint, data=json.dumps(rule, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            data = resp.json().get('music.vkey.GetVkey.UrlGetVkey', {}).get('data', {})
            purl = ((data.get('midurlinfo') or [{}])[0].get('purl')) or ''
            results[prefix] = {'ok': bool(purl), 'ms': round((time.perf_counter() - t0) * 1000)}
        except Exception as err:
            results[prefix] = {'ok': False, 'error': str(err)[:120]}
    return results


def official_lowtier_kuwo(client, song_id):
    from musicdl.modules.utils.kuwoutils import KuwoMusicClientUtils
    results = {}
    for fmt in ['320kmp3', '128kmp3']:
        t0 = time.perf_counter()
        try:
            query = f"user=0&corp=kuwo&source=kwplayer_ar_5.1.0.0_B_jiakong_vh.apk&p2p=1&type=convert_url2&sig=0&format={fmt}&rid={song_id}"
            resp = client.get(f"http://mobi.kuwo.cn/mobi.s?f=kuwo&q={KuwoMusicClientUtils.encryptquery(query)}", headers={'user-agent': 'okhttp/3.10.0'})
            text = resp.text or ''
            import re as _re
            m = _re.search(r'http[^\s$"]+', text)
            results[fmt] = {'ok': bool(m and m.group(0).startswith('http')), 'ms': round((time.perf_counter() - t0) * 1000),
                            'bitrate_hint': (text.split('bitrate=')[1].split('\n')[0] if 'bitrate=' in text else None)}
        except Exception as err:
            results[fmt] = {'ok': False, 'error': str(err)[:120]}
    return results


'''main spike flow per platform'''
def run(platform, n_hot, n_cold):
    work_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.spike_tmp')
    common = dict(search_size_per_source=1, disable_print=True, work_dir=work_dir, max_retries=2)
    if platform == 'qq':
        client, min_dict, collect_ids, official_test = QQMusicClient(**common), lambda sid: {'mid': sid}, collect_ids_qq, official_lowtier_qq
    else:
        client, min_dict, collect_ids, official_test = KuwoMusicClient(**common), lambda sid: {'musicrid': f'MUSIC_{sid}'}, collect_ids_kuwo, official_lowtier_kuwo

    stats, details = {}, []
    # instrument all third-party parsers listed in _parsewiththirdpartapis source order
    import re as _re
    src_names = []
    import inspect
    chain_src = inspect.getsource(type(client)._parsewiththirdpartapis)
    for m in _re.finditer(r'self\.(_parsewith\w+)', chain_src):
        if m.group(1) not in src_names: src_names.append(m.group(1))
    for name in src_names: instrument(client, stats)(name)

    candidates = []
    for kw in HOT_KEYWORDS[:max(n_hot, 1)]:
        try: candidates += [('hot', c) for c in collect_ids(client, kw, 2)]
        except Exception as err: print(f'[warn] hot search failed: {kw}: {err}')
    for kw in COLD_KEYWORDS[:max(n_cold, 1)]:
        try: candidates += [('cold', c) for c in collect_ids(client, kw, 2)]
        except Exception as err: print(f'[warn] cold search failed: {kw}: {err}')
    seen = set(); uniq = []
    for tag, c in candidates:
        if c['id'] in seen: continue
        seen.add(c['id']); uniq.append((tag, c))
        if len([t for t, _ in uniq]) >= n_hot and len([t for t, _ in uniq if t == 'cold']) >= n_cold: break
    sample = [c for t, c in uniq if t == 'hot'][:n_hot] + [c for t, c in uniq if t == 'cold'][:n_cold]
    print(f'[{platform}] testing {len(sample)} songs ({len(sample[:n_hot])} hot + {len(sample[n_hot:])} cold)...')

    for idx, cand in enumerate(sample):
        t0 = time.perf_counter()
        try:
            info = client._parsewiththirdpartapis(min_dict(cand['id']), {})
            elapsed = round((time.perf_counter() - t0) * 1000)
            ok = bool(info.with_valid_download_url and info.ext in AudioLinkTester.VALID_AUDIO_EXTS)
            details.append({'idx': idx, 'tag': 'hot' if idx < n_hot else 'cold', 'id': cand['id'], 'name': cand.get('name'), 
                            'ok': ok, 'ext': info.ext if ok else None, 'size_mb': round(info.file_size_bytes / 1048576, 2) if ok and info.file_size_bytes else None,
                            'ms': elapsed, 'parser': info.raw_data.get('spike_parser') if ok else None,
                            'meta_fetched': bool(len(min_dict(cand['id'])) < len(info.raw_data.get('search') or {}))})
            print(f'  [{idx+1}/{len(sample)}] {"OK " if ok else "FAIL"} {elapsed:>6}ms ext={info.ext or "-":<5} parser={info.raw_data.get("spike_parser") or "-":<28} {str(cand.get("name"))[:40]}')
        except Exception as err:
            details.append({'idx': idx, 'id': cand['id'], 'name': cand.get('name'), 'ok': False, 'error': str(err)[:200]})
            print(f'  [{idx+1}/{len(sample)}] EXC {str(err)[:80]}')

    # official low-tier on first 5 songs
    official = {}
    for cand in sample[:5]:
        official[cand['id']] = official_test(client, cand['id'])
        print(f'  [official] {cand["id"]} -> {json.dumps(official[cand["id"]], ensure_ascii=False)}')

    oks = [d for d in details if d.get('ok')]
    allms = sorted(d['ms'] for d in oks)
    summary = {
        'platform': platform, 'tested_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'total': len(details),
        'success': len(oks), 'success_rate': round(len(oks) / len(details), 3) if details else 0,
        'latency_ms': {'p50': round(statistics.median(allms)) if allms else None, 'avg': round(sum(allms) / len(allms)) if allms else None,
                       'min': round(allms[0]) if allms else None, 'max': round(allms[-1]) if allms else None},
        'ext_distribution': {ext: sum(1 for d in oks if d.get('ext') == ext) for ext in set(d.get('ext') for d in oks)},
        'per_parser': {k: {'attempts': v['attempts'], 'ok': v['ok'], 'avg_ms': round(sum(v['ms']) / len(v['ms'])) if v['ms'] else None,
                           'errors_sample': (v.get('errors') or [])[:2]} for k, v in stats.items()},
        'official_lowtier': official, 'details': details,
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'spike_results_{platform}.json')
    with open(out_path, 'w', encoding='utf-8') as fp: json.dump(summary, fp, ensure_ascii=False, indent=2)
    print(f'\n===== [{platform}] SUMMARY =====')
    print(f"success: {summary['success']}/{summary['total']} ({summary['success_rate']*100:.0f}%)  latency p50={summary['latency_ms']['p50']}ms avg={summary['latency_ms']['avg']}ms")
    print(f"ext dist: {summary['ext_distribution']}")
    for k, v in summary['per_parser'].items(): print(f"  {k:<30} attempts={v['attempts']:<3} ok={v['ok']:<3} avg={v['avg_ms']}ms")
    print(f'report saved -> {out_path}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--platform', choices=['qq', 'kuwo'], required=True)
    ap.add_argument('--hot', type=int, default=5)
    ap.add_argument('--cold', type=int, default=5)
    args = ap.parse_args()
    run(args.platform, args.hot, args.cold)
