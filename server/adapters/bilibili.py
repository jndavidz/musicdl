'''
Function:
    Bilibili adapter — UGC video platform; audio extracted from DASH streams.
    Anonymous works end-to-end via dynamic device fingerprint (finger/spi),
    audio capped at 192k AAC. BILI_SESSDATA unlocks Hi-Res FLAC / Dolby tracks.
    CDN requires Referer header — returned to clients in song/url `headers` field.
'''
import time
import json as _json
import urllib.request
import urllib.parse
from .base import SourceAdapter, AdapterError
from ..cache import TTLCache
from ..quality import resolve as resolve_quality, requires_lossless


class BilibiliAdapter(SourceAdapter):
    source_key = 'bilibili'
    # B站音质id表（bilibili-API-collect 社区文档）
    QUALITY_IDS = {30216: '64k', 30232: '132k', 30280: '192k', 30250: 'dolby', 30251: 'hires'}
    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131'

    def _build_client(self):
        from musicdl.modules.sources.bilibili import BilibiliMusicClient
        # 清空过期内置cookie，保持干净匿名态（动态指纹由本类自行管理）
        return BilibiliMusicClient(search_size_per_source=self.settings.search_size_max,
                                   search_size_per_page=25, disable_print=True,
                                   work_dir='/tmp/kwqq-bili', max_retries=2,
                                   default_search_cookies={}, default_parse_cookies={},
                                   default_download_cookies={})

    '''动态设备指纹：finger/spi 匿名换取 buvid3/buvid4（TTL 缓存 7 天）'''
    def _get_buvid(self) -> str:
        cache = getattr(self, '_buvid_cache', None)
        if cache is None:
            cache = self._buvid_cache = TTLCache(ttl_seconds=86400 * 7)
        cookie = cache.get('buvid')
        if cookie is None:
            resp = self.client.get('https://api.bilibili.com/x/frontend/finger/spi', timeout=self.io_timeout)
            d = _json.loads(resp.text) if hasattr(resp, 'text') else {}
            b3 = (d.get('data') or {}).get('b_3', '')
            b4 = (d.get('data') or {}).get('b_4', '')
            cookie = f'buvid3={b3}; buvid4={b4}'
            cache.set('buvid', cookie)
        return cookie

    def _api_get(self, url: str) -> dict:
        cookie = self._get_buvid()
        sessdata = getattr(self.settings, 'bili_sessdata', '')
        if sessdata:
            cookie += f'; SESSDATA={sessdata}'
        resp = self.client.get(url, headers={
            'User-Agent': self.UA, 'Referer': 'https://www.bilibili.com/', 'Cookie': cookie},
                               timeout=self.io_timeout)
        return resp.json() if hasattr(resp, 'json') else {}

    '''metadata-only search via web-interface video search — MUST go through
       _api_get: since 2026-10-27 bilibili 412s anonymous search requests without
       the dynamic buvid cookie (search used to hit the endpoint bare).'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        rule = {'search_type': 'video', 'keyword': keywords, 'page': page, 'page_size': limit}
        try:
            data = self._api_get('https://api.bilibili.com/x/web-interface/search/type?' + urlencode(rule))
            return ((data.get('data') or {}).get('result')) or []
        except Exception:
            return []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        import re as _re
        title = _re.sub(r'<[^>]+>', '', raw.get('title') or '')  # strip <em> highlight
        dur_raw = str(raw.get('duration') or '')
        try:
            parts = [int(x) for x in dur_raw.split(':')]
            duration = [0, 0] + parts if len(parts) < 3 else parts
            duration_s = duration[-1] + duration[-2] * 60 + (duration[-3] * 3600 if len(duration) > 2 else 0)
        except Exception:
            duration_s = None
        return {'id': str(raw.get('bvid') or ''), 'name': title,
                'singer': raw.get('author'), 'album': None, 'ext': None, 'size_bytes': None,
                'duration_s': duration_s or None,
                'cover': ('https:' + raw['pic']) if raw.get('pic', '').startswith('//') else raw.get('pic'),
                'source': 'bilibili'}

    '''resolve DASH audio track by quality tier.
       v2 passes the verified identity (cid and/or page); a bare bvid must not
       silently play pages[0] because multi-P videos are distinct media.'''
    async def song_url(self, song_id: str, quality: str, cid=None, page=None) -> dict:
        q = resolve_quality(self.source_key, quality)  # 192k request -> 320k (no native 192k tier)
        t0 = time.perf_counter()
        sessdata = getattr(self.settings, 'bili_sessdata', '')
        # buvid may need a network round-trip on a cold cache: measured execution,
        # never on the event loop (K-03)
        buvid = await self.run(self._get_buvid)
        cookie = buvid + (f'; SESSDATA={sessdata}' if sessdata else '')

        def _view():
            from urllib.request import urlopen, Request
            req = Request(f'https://api.bilibili.com/x/web-interface/view?bvid={song_id}',
                          headers={'User-Agent': self.UA, 'Cookie': cookie})
            return _json.loads(urlopen(req, timeout=self.io_timeout[1]).read())
        view = await self.run(_view)
        pages = (view.get('data') or {}).get('pages') or []
        if not pages: raise AdapterError(404, 'video not found')
        selected, page_index = self._select_page(pages, cid, page)
        cid_resolved, root_title = selected['cid'], (view.get('data') or {}).get('title', '')

        def _playurl():
            from urllib.request import urlopen, Request
            req = Request(f'https://api.bilibili.com/x/player/playurl?fnval=208&bvid={song_id}&cid={cid_resolved}',
                          headers={'User-Agent': self.UA, 'Cookie': cookie})
            return _json.loads(urlopen(req, timeout=self.io_timeout[1]).read())
        p = await self.run(_playurl)
        dash = ((p.get('data') or {}).get('dash')) or {}

        def pick(candidates):
            for a in candidates:
                u = a.get('baseUrl') or a.get('base_url')
                if u and str(u).startswith('http'): return a
            return None
        tiers = {'128k': [30232, 30280], '320k': [30280, 30251, 30250, 30232],
                 'auto': [30280, 30251, 30250, 30232]}
        want_ids = {'flac': [30251], 'hires': [30251]}[q] if requires_lossless(q) else tiers[q]
        if requires_lossless(q) and not sessdata:
            raise AdapterError(403, 'Hi-Res/Dolby needs BILI_SESSDATA (bilibili account)')
        all_audio = ((dash.get('flac') or {}).get('audio') or []) + \
                    ((dash.get('dolby') or {}).get('audio') or []) + (dash.get('audio') or [])
        chosen = next((a for wid in want_ids for a in all_audio if a.get('id') == wid), None)
        if chosen is None and all_audio:  # fallback: highest bandwidth
            chosen = max(all_audio, key=lambda a: a.get('bandwidth', 0))
        if not chosen: raise AdapterError(404, 'no audio track found')

        base = chosen.get('baseUrl') or chosen.get('base_url')
        status = await self.run(self.client.audio_link_tester.test, base)
        final_url = status.get('download_url') or base
        ext = 'm4a' if status.get('ext') in {'m4s', 'mp4', None} else status.get('ext')
        data = self.url_data(song_id, q,
                             url=final_url, ext=ext, size_bytes=status.get('file_size_bytes'),
                             bitrate_kbps=int(chosen.get('bandwidth', 0)) // 1000 or None,
                             duration_s=int(float(dash.get('duration') or 0)) or None,
                             verified=bool(status.get('ok')),
                             headers={'Referer': 'www.bilibili.com', 'User-Agent': self.UA},
                             parser=f'bili.dash.{chosen.get("id")}',
                             elapsed_ms=round((time.perf_counter() - t0) * 1000))
        data['resolved_cid'] = str(cid_resolved)
        data['resolved_page'] = page_index
        return data

    @staticmethod
    def _select_page(pages: list, cid=None, page=None):
        '''verified single-page selection. cid wins when both are given, but a
           disagreeing page/cid pair is a client error (identity is ambiguous).'''
        by_cid = None
        if cid is not None:
            want = str(cid).strip()
            by_cid = next(((i, p) for i, p in enumerate(pages, 1) if str(p.get('cid')) == want), None)
            if by_cid is None:
                raise AdapterError(404, f'cid {want} not found in this video (pages={len(pages)})')
        if page is not None:
            idx = int(page)
            if idx < 1 or idx > len(pages):
                raise AdapterError(404, f'page {idx} out of range (pages={len(pages)})')
            if by_cid is not None and by_cid[0] != idx:
                raise AdapterError(400, f'cid {cid} belongs to page {by_cid[0]}, not page {idx}')
            return pages[idx - 1], idx
        if by_cid is not None:
            return by_cid[1], by_cid[0]
        return pages[0], 1   # v1 path: unchanged pages[0] behavior

    '''v2 identity: cid/page drive the resolve call'''
    def identity_kwargs(self, extra: dict) -> dict:
        extra = extra or {}
        return {'cid': extra.get('cid'), 'page': extra.get('page')}

    '''v2 identity: echo the VERIFIED cid/page actually resolved'''
    def identity_out(self, requested: dict, result: dict) -> dict:
        out = dict(requested or {})
        if result.get('resolved_cid'): out['cid'] = str(result['resolved_cid'])
        if result.get('resolved_page'): out['page'] = int(result['resolved_page'])
        return out

    '''song meta via view endpoint. Also surfaces the part list so a caller can
       complete a v2 TrackRef (bvid + verified cid/page) for the SELECTED item —
       this is the sanctioned per-item completion, never a per-candidate N+1.'''
    async def song_info(self, song_id: str) -> dict:
        def _fetch():
            from urllib.request import urlopen, Request
            req = Request(f'https://api.bilibili.com/x/web-interface/view?bvid={song_id}',
                          headers={'User-Agent': self.UA})
            return _json.loads(urlopen(req, timeout=self.io_timeout[1]).read())
        v = await self.run(_fetch)
        d = v.get('data') or {}
        if not d: raise AdapterError(404, 'video not found')
        pages = [{'cid': str(p.get('cid')), 'page': p.get('page') or i, 'part': p.get('part')}
                 for i, p in enumerate(d.get('pages') or [], 1)]
        first = pages[0] if pages else {}
        return {'id': str(song_id), 'source': self.source_key, 'name': d.get('title'),
                'singer': (d.get('owner') or {}).get('name'), 'album': f"BV{d.get('bvid','')}",
                'duration_s': int(float(d.get('duration') or 0)) or None,
                'cover': d.get('pic'),
                'extra': ({'cid': first['cid'], 'page': first['page']} if first else {}),
                'raw': {'pages': pages}}

    '''bilibili videos have no standard lyrics; AI subtitles need login — keep empty'''
    async def lyric(self, song_id: str) -> str:
        return ''
