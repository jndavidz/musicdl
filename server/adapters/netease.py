'''
Function:
    Netease adapter — resolves through the self-hosted NeteaseCloudMusicApiEnhanced
    container on the NAS (http://10.10.10.2:3000), whose persisted login powers
    VIP-quality links. Requires the container to be logged in (/login/status).
'''
import time
from .base import SourceAdapter, AdapterError
from ..quality import resolve as resolve_quality
from .kugou import requests_get


class NeteaseAdapter(SourceAdapter):
    source_key = 'netease'
    LEVELS = {'128k': 'standard', '192k': 'higher', '320k': 'exhigh', 'auto': 'exhigh',
              'flac': 'lossless', 'hires': 'hires'}

    def _build_client(self):
        # musicdl's netease client is unused for resolution here; we only need its
        # HTTP session helpers. Keep it constructed for interface parity.
        from musicdl.modules.sources.netease import NeteaseMusicClient
        return NeteaseMusicClient(search_size_per_source=self.settings.search_size_max,
                                  disable_print=True, work_dir='/tmp/kwqq-netease', max_retries=2)

    '''raw GET against the sibling ncm-api container, gzip-decoded.
       NETEASE_COOKIE (e.g. MUSIC_U=xxx) is attached when configured — enables VIP-quality.
       os=pc in the cookie guarantees non-truncated bitrates (per ncm-api docs).'''
    def _api_get(self, path: str, params: dict = None) -> dict:
        params = dict(params or {})
        mu = self.account_cookie()
        if mu:
            params['cookie'] = 'os=pc; ' + mu
        # logical name keeps the cooldown host-agnostic (NCM_API_BASE alias switching
        # must not reset an upstream 429 cooldown)
        return self.guarded_sync('netease:ncm-api', requests_get, f'{self.settings.ncm_api_base}{path}', params)

    '''raw cookie value (e.g. MUSIC_U=xxx); public interface for the generic passthrough
       (cookie-optional injection: absent file -> anonymous request)'''
    def account_cookie(self) -> str:
        try:
            return open(self.settings.netease_cookie_file).read().strip()
        except Exception:
            return ''

    '''metadata-only search via cloudsearch (standard fields: id/name/ar[]/al/duration)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        data = requests_get(f'{self.settings.ncm_api_base}/cloudsearch', {'keywords': keywords, 'limit': limit, 'offset': (page - 1) * limit})
        return (((data.get('result') or {}).get('songs')) or [])

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        # search-stage quality stock: cloudsearch rows carry per-tier size entries
        #   hr = Hi-Res, sq = lossless, h = 320k — surface the best available tier.
        stock_tier, stock_size = None, None
        for key, tier in (('hr', 'HR'), ('sq', 'SQ'), ('h', 'HQ')):
            entry = raw.get(key) or {}
            if entry.get('size'):
                stock_tier, stock_size = tier, int(entry['size']); break
        return {'id': str(raw.get('id') or ''), 'name': raw.get('name'),
                'singer': ', '.join(a.get('name') for a in (raw.get('ar') or []) if isinstance(a, dict) and a.get('name')) or None,
                'album': (raw.get('al') or {}).get('name'),
                'ext': None, 'size_bytes': None,
                'stock_tier': stock_tier, 'stock_size_bytes': stock_size,
                'duration_s': int(float(raw.get('dt') or 0)) // 1000 or None,
                'cover': (raw.get('al') or {}).get('picUrl'), 'source': 'netease'}

    async def song_url(self, song_id: str, quality: str) -> dict:
        q = resolve_quality(self.source_key, quality)  # netease has a REAL 192k tier ('higher')
        t0 = time.perf_counter()
        # single-pass: official catalog ladder only (no cross-platform unblock
        # mirrors — per policy, netease songs must come from netease CDNs).
        levels = (['jymaster', 'dolby', 'sky', 'jyeffect', 'hires']
                  if q == 'hires' else [self.LEVELS[q]])
        high_tiers = {'jymaster', 'dolby', 'sky', 'vivid', 'jyeffect'}
        premium_floor_mbpm = 17

        for level in levels:
            data = await self.run(
                self._api_get, '/song/url/v1',
                {'id': song_id, 'level': level, 'unblock': 'false'})
            entry = ((data.get('data') or [{}])[0]) if isinstance(data.get('data'), list) else {}
            url = entry.get('url') or ''
            if not str(url).startswith('http'): continue
            size_b = float(entry.get('size') or 0)
            dur_s = float(entry.get('time') or 0) / 1000
            if level in high_tiers:
                # HEAD is blocking sync I/O: run it inside the measured execution
                # boundary (worker slot + timeout), never on the event loop (K-03)
                size_b = await self.run(self._head_size, url, size_b)
                mbpm = (round(size_b / 1048576 / (dur_s / 60), 1)
                        if size_b > 0 and dur_s > 0 else None)
                if not ((mbpm is not None and mbpm >= premium_floor_mbpm)
                        or (mbpm is None and size_b >= 45 * 1024 * 1024)):
                    continue
            return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                    'url': url, 'ext': entry.get('type') or 'mp3',
                    'size_bytes': int(float(entry.get('size') or 0)) or None,
                    'bitrate_kbps': int(float(entry.get('br') or 0)) // 1000 or None,
                    'duration_s': int(float(entry.get('time') or 0)) // 1000 or None,
                    'cover': None, 'verified': False, 'headers': {},
                    'parser': f'ncm-api.{level}',
                    'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}

        # pass 3: ffapi 128k last-resort (official CDN, anonymous — survives VIP expiry)
        ff = await self.run(self._via_ffapi, song_id)
        if ff and ff.get('url'):
            return self.url_data(song_id, q,
                                 url=ff['url'], ext='mp3', bitrate_kbps=128, verified=False,
                                 parser='ffapi.relay',
                                 elapsed_ms=round((time.perf_counter() - t0) * 1000))
        raise AdapterError(404, f'no playable url at levels={levels} (official + unblock + ffapi exhausted)')

    '''official CDN HEAD used for the premium-tier payload floor; blocking, so it
       always runs through self.run() with its own socket budget'''
    def _head_size(self, url: str, fallback) -> float:
        try:
            import requests as _rq
            h = _rq.head(url, timeout=self.io_timeout, allow_redirects=True)
            return int(h.headers.get('Content-Length', 0) or 0) or fallback
        except Exception:
            return fallback

    async def song_info(self, song_id: str) -> dict:
        data = await self.run(self._api_get, '/song/detail', {'ids': str(song_id)})
        songs = (data.get('songs') or [])
        if not songs: raise AdapterError(404, 'song not found')
        s = songs[0]
        return {'id': str(song_id), 'source': self.source_key, 'name': s.get('name'),
                'singer': ', '.join(a.get('name') for a in (s.get('ar') or []) if isinstance(a, dict)),
                'album': (s.get('al') or {}).get('name'),
                'duration_s': int(float(s.get('dt') or 0)) // 1000 or None,
                'cover': (s.get('al') or {}).get('picUrl'), 'raw': {}}

    '''ffapi 128k last-resort (official CDN, anonymous, works after VIP expiry)'''
    def _via_ffapi(self, song_id: str) -> dict:
        import requests as _rq
        r = self.guarded_sync('netease:ffapi', _rq.get,
                              f'https://ffapi.cn/int/v1/netease_url?id={song_id}&level=standard',
                              headers={'User-Agent': 'Mozilla/5.0 Chrome/131'}, timeout=self.io_timeout)
        d = r.json()
        url = (d.get('data') or d).get('url') or ''
        if not str(url).startswith('http'): return None
        return {'url': url, 'parser': 'ffapi.relay'}

    async def lyric(self, song_id: str) -> str:
        data = await self.run(self._api_get, '/lyric', {'id': str(song_id)})
        return ((data.get('lrc') or {}).get('lyric')) or ''

    '''P6 专辑检索（netease 先行实现）：ncm-api /cloudsearch?type=10（专辑候选）
       → /album?id=（官方曲序 songs，ar/al/dt 与 cloudsearch 同构，item_from_raw 直接复用）。
       artist 提示用于候选排序（平台专辑搜索常有同名异手专辑）。'''
    async def album(self, name: str, artist: str = '', page: int = 1) -> dict:
        def _search(kw):
            search = self._api_get('/cloudsearch', {'keywords': kw, 'type': 10,
                                                    'limit': 5, 'offset': (page - 1) * 5})
            return ((search.get('result') or {}).get('albums')) or []

        def _fetch():
            # name+artist 精度更高（同名异手专辑多）；无结果再退 name-only
            albums_raw = _search(f'{name} {artist}'.strip() if artist else name)
            if not albums_raw and artist:
                albums_raw = _search(name)
            albums = []
            for a in albums_raw:
                if not a.get('id'):
                    continue
                albums.append({'id': str(a['id']), 'name': a.get('name'),
                               'artist': (a.get('artist') or {}).get('name'),
                               'size': a.get('size'), 'cover': a.get('picUrl'),
                               'source': self.source_key, 'extra': {}})
            self.rank_candidates(albums, name, artist)
            if not albums:
                return {'albums': [], 'items': []}
            detail = self._api_get('/album', {'id': albums[0]['id']})
            items = []
            for i, raw in enumerate(detail.get('songs') or [], 1):
                item = self.item_from_raw(raw)
                if item.get('id'):
                    item['track_no'] = i
                    items.append(item)
            return {'albums': albums, 'items': items}
        return await self.run(_fetch)

    '''P6 歌单检索：/cloudsearch?type=1000（歌单候选）→ /playlist/track/all（整单曲目）。
       曲目行与 cloudsearch songs 同构，item_from_raw 直接复用；序号取官方曲序。'''
    async def playlist(self, name: str, page: int = 1) -> dict:
        def _fetch():
            search = self._api_get('/cloudsearch', {'keywords': name, 'type': 1000,
                                                    'limit': 5, 'offset': (page - 1) * 5})
            playlists_raw = ((search.get('result') or {}).get('playlists')) or []
            playlists = []
            for p in playlists_raw:
                if not p.get('id'):
                    continue
                playlists.append({'id': str(p['id']), 'name': p.get('name'),
                                  'creator': (p.get('creator') or {}).get('nickname'),
                                  'track_count': p.get('trackCount'),
                                  'cover': p.get('coverImgUrl'),
                                  'source': self.source_key, 'extra': {}})
            key = name.strip().lower()
            playlists.sort(key=lambda p: ((p.get('name') or '').strip().lower() == key,), reverse=True)
            if not playlists:
                return {'playlists': [], 'items': []}
            detail = self._api_get('/playlist/track/all', {'id': playlists[0]['id'], 'limit': 1000})
            items = []
            for i, raw in enumerate(detail.get('songs') or [], 1):
                item = self.item_from_raw(raw)
                if item.get('id'):
                    item['track_no'] = i
                    items.append(item)
            return {'playlists': playlists, 'items': items}
        return await self.run(_fetch)
