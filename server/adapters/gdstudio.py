'''
Function:
    GD音乐台 (GD Studio) multi-platform aggregator adapter — EXPERIMENTAL, NOT REGISTERED.
    Official doc: https://music-api.gdstudio.xyz/api.php (no signature required).
    Status 2026-08-23: API works (netease verified real CDN link) BUT the new paid
    server has ~50% connect-timeout rate from CN networks. Re-enable when stable:
      1) add 'gdstudio' to ADAPTER_CLASSES and config.SOURCES
    Usage note: /gdstudio/song/url accepts `source=` (netease/joox/bilibili/tidal/
    qobuz/apple/ytmusic/spotify/kuwo) to resolve ANY platform's track id.
'''
import time
import requests
from .base import SourceAdapter, AdapterError

DOC_BASE = 'https://music-api.gdstudio.xyz/api.php'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131',
           'Accept': 'application/json'}
BR_MAP = {'auto': [999, 320, 128], 'flac': [999, 740], 'hires': [999, 740],
          '320k': [320, 192, 128], '128k': [128]}
LOSSLESS_BRS = {999, 740}


class GDMusicAdapter(SourceAdapter):
    source_key = 'gdstudio'
    timeout_override = 60

    def _build_client(self):
        return None  # pure HTTP, no musicdl client needed

    def _api_get(self, **params) -> dict:
        r = requests.get(DOC_BASE, params=params, headers=HEADERS, timeout=(5, 25))
        return r.json() if r.text.startswith(('{', '[')) else {}

    '''search via GD aggregate (defaults to netease source)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        d = self._api_get(types='search', source='netease', name=keywords,
                          count=str(limit), pages=str(page))
        return d if isinstance(d, list) else []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        artists = raw.get('artist')
        if isinstance(artists, list): artists = ', '.join(str(a) for a in artists)
        return {'id': str(raw.get('id') or ''), 'name': raw.get('name'), 'singer': artists,
                'album': raw.get('album'), 'ext': None, 'size_bytes': None, 'duration_s': None,
                'cover': None, 'source': f"gdstudio:{raw.get('source', 'netease')}"}

    '''resolve url for any platform track id; quality maps to br sequence'''
    async def song_url(self, song_id: str, quality: str, source: str = 'netease') -> dict:
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        t0 = time.perf_counter()
        last = {}
        for br in BR_MAP[q]:
            try:
                d = await self.run(self._api_get, types='url', source=source,
                                   id=str(song_id), br=str(br))
            except AdapterError:
                continue
            url = d.get('url') or ''
            if not str(url).startswith('http') or d.get('br') in (-1, '-1'):
                last = d; continue
            return {'id': str(song_id), 'source': f'gdstudio:{source}', 'quality': q,
                    'url': url, 'ext': 'flac' if int(d.get('br') or 0) >= 800 else 'mp3',
                    'size_bytes': int(float(d.get('size') or 0)) * 1024 or None,
                    'bitrate_kbps': int(d['br']) if str(d.get('br')).isdigit() else None,
                    'duration_s': None, 'cover': None, 'verified': False, 'headers': {},
                    'parser': f'gd.{source}.br{d.get("br")}',
                    'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}
        raise AdapterError(404, f'no playable url resolved (last={last})')

    async def song_info(self, song_id: str, source: str = 'netease') -> dict:
        raise AdapterError(404, 'gdstudio does not expose track meta by id')

    async def lyric(self, song_id: str, source: str = 'netease') -> str:
        try:
            d = await self.run(self._api_get, types='lyric', source=source, id=str(song_id))
            return d.get('lyric') or ''
        except Exception:
            return ''
