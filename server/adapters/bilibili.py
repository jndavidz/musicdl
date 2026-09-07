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

    '''动态设备指纹：finger/spi 匿名换取 buvid3/buvid4（进程级缓存）'''
    def _get_buvid(self) -> str:
        cache = getattr(self, '_buvid_cache', None)
        if cache and time.time() - cache['at'] < 86400 * 7:
            return cache['cookie']
        resp = self.client.get('https://api.bilibili.com/x/frontend/finger/spi')
        d = _json.loads(resp.text) if hasattr(resp, 'text') else {}
        b3 = (d.get('data') or {}).get('b_3', '')
        b4 = (d.get('data') or {}).get('b_4', '')
        cookie = f'buvid3={b3}; buvid4={b4}'
        self._buvid_cache = {'cookie': cookie, 'at': time.time()}
        return cookie

    def _api_get(self, url: str) -> dict:
        cookie = self._get_buvid()
        sessdata = getattr(self.settings, 'bili_sessdata', '')
        if sessdata:
            cookie += f'; SESSDATA={sessdata}'
        resp = self.client.get(url, headers={
            'User-Agent': self.UA, 'Referer': 'https://www.bilibili.com/', 'Cookie': cookie})
        return resp.json() if hasattr(resp, 'json') else {}

    '''metadata-only search via web-interface video search (dynamic buvid bypasses risk control)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        rule = {'search_type': 'video', 'keyword': keywords, 'page': page, 'page_size': limit}
        resp = self.client.get('https://api.bilibili.com/x/web-interface/search/type?' + urlencode(rule))
        try:
            return ((resp.json().get('data') or {}).get('result')) or []
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

    '''resolve DASH audio track by quality tier'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        t0 = time.perf_counter()
        sessdata = getattr(self.settings, 'bili_sessdata', '')
        cookie = self._get_buvid() + (f'; SESSDATA={sessdata}' if sessdata else '')

        def _view():
            from urllib.request import urlopen, Request
            req = Request(f'https://api.bilibili.com/x/web-interface/view?bvid={song_id}',
                          headers={'User-Agent': self.UA, 'Cookie': cookie})
            return _json.loads(urlopen(req, timeout=15).read())
        view = await self.run(_view)
        pages = (view.get('data') or {}).get('pages') or []
        if not pages: raise AdapterError(404, 'video not found')
        cid, root_title = pages[0]['cid'], (view.get('data') or {}).get('title', '')

        def _playurl():
            from urllib.request import urlopen, Request
            req = Request(f'https://api.bilibili.com/x/player/playurl?fnval=208&bvid={song_id}&cid={cid}',
                          headers={'User-Agent': self.UA, 'Cookie': cookie})
            return _json.loads(urlopen(req, timeout=15).read())
        p = await self.run(_playurl)
        dash = ((p.get('data') or {}).get('dash')) or {}

        def pick(candidates):
            for a in candidates:
                u = a.get('baseUrl') or a.get('base_url')
                if u and str(u).startswith('http'): return a
            return None
        tiers = {'128k': [30232, 30280], '320k': [30280, 30251, 30250, 30232],
                 'auto': [30280, 30251, 30250, 30232]}
        want_ids = {'flac': [30251], 'hires': [30251]}[q] if q in {'flac', 'hires'} else tiers[q]
        if q in {'flac', 'hires'} and not sessdata:
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
        return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                'url': final_url, 'ext': ext,
                'size_bytes': status.get('file_size_bytes'),
                'bitrate_kbps': int(chosen.get('bandwidth', 0)) // 1000 or None,
                'duration_s': int(float(dash.get('duration') or 0)) or None,
                'cover': None, 'verified': bool(status.get('ok')),
                'headers': {'Referer': 'www.bilibili.com', 'User-Agent': self.UA},
                'parser': f'bili.dash.{chosen.get("id")}',
                'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}

    '''song meta via view endpoint'''
    async def song_info(self, song_id: str) -> dict:
        def _fetch():
            from urllib.request import urlopen, Request
            req = Request(f'https://api.bilibili.com/x/web-interface/view?bvid={song_id}',
                          headers={'User-Agent': self.UA})
            return _json.loads(urlopen(req, timeout=15).read())
        v = await self.run(_fetch)
        d = v.get('data') or {}
        if not d: raise AdapterError(404, 'video not found')
        return {'id': str(song_id), 'source': self.source_key, 'name': d.get('title'),
                'singer': (d.get('owner') or {}).get('name'), 'album': f"BV{d.get('bvid','')}",
                'duration_s': int(float(d.get('duration') or 0)) or None,
                'cover': d.get('pic'), 'raw': {}}

    '''bilibili videos have no standard lyrics; AI subtitles need login — keep empty'''
    async def lyric(self, song_id: str) -> str:
        return ''


import time as _time_mod
time = _time_mod
