'''
Function:
    Netease adapter — resolves through the self-hosted NeteaseCloudMusicApiEnhanced
    container on the NAS (http://10.10.10.2:3000), whose persisted login powers
    VIP-quality links. Requires the container to be logged in (/login/status).
'''
import time
from .base import SourceAdapter, AdapterError
from .kugou import requests_get


class NeteaseAdapter(SourceAdapter):
    source_key = 'netease'
    LEVELS = {'128k': 'standard', '320k': 'exhigh', 'auto': 'exhigh',
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
        if self.settings.netease_cookie:
            params['cookie'] = 'os=pc; ' + self.settings.netease_cookie
        return requests_get(f'{self.settings.ncm_api_base}{path}', params)

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
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        t0 = time.perf_counter()
        # Two-pass strategy:
        #   pass 1 (unblock=false): official catalog ladder — jymaster down to hires.
        #     Premium tiers are HEAD-verified against the spec table (>=17 MB/min)
        #     because ncm-api sometimes tags a CD-sized stand-in with a premium level.
        #   pass 2 (unblock=true): grey/delisted tracks fall back to mirror sources
        #     (kuwo CDN); those links carry anti-hotlink headers forwarded to clients.
        levels = (['jymaster', 'dolby', 'sky', 'jyeffect', 'hires']
                  if q == 'hires' else [self.LEVELS[q]])
        high_tiers = {'jymaster', 'dolby', 'sky', 'vivid', 'jyeffect'}
        premium_floor_mbpm = 17

        async def _run_pass(unblock: bool):
            for level in levels:
                data = await self.run(
                    self._api_get, '/song/url/v1',
                    {'id': song_id, 'level': level, 'unblock': 'true' if unblock else 'false'})
                entry = ((data.get('data') or [{}])[0]) if isinstance(data.get('data'), list) else {}
                url = entry.get('url') or ''
                if not str(url).startswith('http'): continue
                mirrored = ('kuwo' in url) or ('migu' in url)
                size_b = float(entry.get('size') or 0)
                dur_s = float(entry.get('time') or 0) / 1000
                if level in high_tiers and not mirrored:
                    try:
                        import requests as _rq
                        h = _rq.head(url, timeout=(3, 15), allow_redirects=True)
                        size_b = int(h.headers.get('Content-Length', 0) or 0) or size_b
                    except Exception: pass
                    mbpm = (round(size_b / 1048576 / (dur_s / 60), 1)
                            if size_b > 0 and dur_s > 0 else None)
                    if not ((mbpm is not None and mbpm >= premium_floor_mbpm)
                            or (mbpm is None and size_b >= 45 * 1024 * 1024)):
                        continue
                platform_tag = (f'解灰镜像({entry.get("level") or level})' if mirrored
                                else str(entry.get('level') or level))
                headers = ({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36',
                            'Referer': 'https://kuwo.cn/', 'Origin': 'https://kuwo.cn'} if mirrored else {})
                return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                        'url': url, 'ext': entry.get('type') or 'mp3',
                        'size_bytes': int(float(entry.get('size') or 0)) or None,
                        'bitrate_kbps': int(float(entry.get('br') or 0)) // 1000 or None,
                        'duration_s': int(float(entry.get('time') or 0)) // 1000 or None,
                        'cover': None, 'verified': False, 'headers': headers,
                        'parser': f'ncm-api.{level}',
                        'platform_tag': platform_tag,
                        'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}
            return None

        result = await _run_pass(unblock=False)      # pass 1: official best
        if result is None:
            result = await _run_pass(unblock=True)   # pass 2: grey-track unblock mirrors
        if result is None:
            # pass 3: ffapi 128k last-resort (official CDN, anonymous — survives VIP expiry)
            ff = await self.run(self._via_ffapi, song_id)
            if ff and ff.get('url'):
                return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                        'url': ff['url'], 'ext': 'mp3', 'size_bytes': None, 'bitrate_kbps': 128,
                        'duration_s': None, 'cover': None, 'verified': False, 'headers': {},
                        'parser': 'ffapi.relay',
                        'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}
            raise AdapterError(404, f'no playable url at levels={levels} (official + unblock + ffapi exhausted)')
        return result

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
        r = _rq.get(f'https://ffapi.cn/int/v1/netease_url?id={song_id}&level=standard',
                    headers={'User-Agent': 'Mozilla/5.0 Chrome/131'}, timeout=12)
        d = r.json()
        url = (d.get('data') or d).get('url') or ''
        if not str(url).startswith('http'): return None
        return {'url': url, 'parser': 'ffapi.relay'}

    async def lyric(self, song_id: str) -> str:
        data = await self.run(self._api_get, '/lyric', {'id': str(song_id)})
        return ((data.get('lrc') or {}).get('lyric')) or ''
