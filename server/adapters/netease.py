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
       NETEASE_COOKIE (e.g. MUSIC_U=xxx) is attached when configured — enables VIP lossless.'''
    def _api_get(self, path: str, params: dict = None) -> dict:
        params = dict(params or {})
        if self.settings.netease_cookie:
            params['cookie'] = self.settings.netease_cookie
        return requests_get(f'{self.settings.ncm_api_base}{path}', params)

    '''metadata-only search via cloudsearch (standard fields: id/name/ar[]/al/duration)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        data = requests_get(f'{self.settings.ncm_api_base}/cloudsearch', {'keywords': keywords, 'limit': limit, 'offset': (page - 1) * limit})
        return (((data.get('result') or {}).get('songs')) or [])

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        return {'id': str(raw.get('id') or ''), 'name': raw.get('name'),
                'singer': ', '.join(a.get('name') for a in (raw.get('ar') or []) if isinstance(a, dict) and a.get('name')) or None,
                'album': (raw.get('al') or {}).get('name'),
                'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('dt') or 0)) // 1000 or None,
                'cover': (raw.get('al') or {}).get('picUrl'), 'source': 'netease'}

    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        t0 = time.perf_counter()
        # hires: try jymaster (master) first — black-vip accounts get it on eligible
        # tracks; standard/hifi accounts fall back to plain hires automatically.
        levels = ['jymaster', 'hires'] if q == 'hires' else [self.LEVELS[q]]
        last_err_entry = {}
        for level in levels:
            data = await self.run(self._api_get, '/song/url/v1', {'id': song_id, 'level': level})
            entry = ((data.get('data') or [{}])[0]) if isinstance(data.get('data'), list) else {}
            url = entry.get('url') or ''
            if not str(url).startswith('http'):
                last_err_entry = {'level': level}
                continue
            return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                    'url': url, 'ext': entry.get('type') or 'mp3',
                    'size_bytes': int(float(entry.get('size') or 0)) or None,
                    'bitrate_kbps': int(float(entry.get('br') or 0)) // 1000 or None,
                    'duration_s': int(float(entry.get('time') or 0)) // 1000 or None,
                    'cover': None, 'verified': False, 'headers': {},
                    'parser': f'ncm-api.{level}',
                    'platform_tag': str(entry.get('level') or level),   # actual level ncm-api granted
                    'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}
        # official sources exhausted (grey / delisted track) -> unblock via /song/url/match,
        # which mirrors from kuwo/migu CDNs; those links need anti-hotlink referer headers.
        match = await self.run(self._api_get, '/song/url/match', {'id': song_id})
        match_url = str(match.get('data') or '')
        if match_url.startswith('http'):
            status = await self.run(self.client.audio_link_tester.test, match_url)
            unblock_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36',
                               'Referer': 'https://kuwo.cn/', 'Origin': 'https://kuwo.cn'}
            ext = (status.get('ext') or match_url.rsplit('.', 1)[-1].split('?')[0] or 'mp3').lower()
            return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                    'url': status.get('download_url') or match_url, 'ext': ext,
                    'size_bytes': status.get('file_size_bytes'), 'bitrate_kbps': None,
                    'duration_s': None, 'cover': None, 'verified': bool(status.get('ok')),
                    'headers': unblock_headers,
                    'parser': 'ncm-api.match.unblock',
                    'platform_tag': '解灰(第三方音源镜像)',
                    'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}
        raise AdapterError(404, f"no url at level={levels} and unblock match failed — {last_err_entry}")

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

    async def lyric(self, song_id: str) -> str:
        data = await self.run(self._api_get, '/lyric', {'id': str(song_id)})
        return ((data.get('lrc') or {}).get('lyric')) or ''
