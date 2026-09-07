'''
Function:
    Kugou adapter — resolves through the self-hosted KuGouMusicApi container
    (http://10.10.10.2:3001) with the account cookie pulled dynamically from
    the cookie-server (http://10.10.10.2:3002/kugou, refreshed by kugou_refresh.sh).
'''
import time
import json
import urllib.request
import urllib.parse
import gzip
import io as _io
from .base import SourceAdapter, AdapterError


def raw_get(url: str, timeout: int = 15) -> str:
    '''fetch body as plain text (cookie-server returns a raw string, not JSON)'''
    req = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='ignore')


def requests_get(url: str, params: dict = None, timeout: int = 20) -> dict:
    if params:
        url = f'{url}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers={'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.GzipFile(fileobj=_io.BytesIO(raw)).read()
    text = raw.decode('utf-8', errors='ignore')
    import json_repair
    try:
        return json_repair.loads(text)
    except Exception:
        return {'_text': text}


class KugouAdapter(SourceAdapter):
    source_key = 'kugou'
    QUALITY = {'128k': '128', '320k': '320', 'auto': '320', 'flac': 'flac', 'hires': 'high'}

    def _build_client(self):
        from musicdl.modules.sources.kugou import KugouMusicClient
        return KugouMusicClient(search_size_per_source=self.settings.search_size_max,
                                disable_print=True, work_dir='/tmp/kwqq-kugou', max_retries=2)

    '''account cookie assembled from kugou_token.json (TTL cached, file re-read on expiry)'''
    def _get_cookie(self) -> str:
        cache = getattr(self, '_cookie_cache', None)
        if cache is None:
            self._cookie_cache = {'v': '', 'at': 0}
        if not self._cookie_cache['v'] or time.time() - self._cookie_cache['at'] > self.settings.cookie_refresh_s:
            with open(self.settings.kugou_token_file) as fp:
                tok = json.load(fp)
            ck = f"token={tok.get('token','')};userid={tok.get('userid','')};dfid={tok.get('dfid','')}"
            self._cookie_cache.update({'v': ck, 'at': time.time()})
        return self._cookie_cache['v']

    '''raw GET against the sibling kugou-api container with cookie attached'''
    def _api_get(self, path: str, params: dict = None) -> dict:
        params = dict(params or {})
        params['cookie'] = self._get_cookie()
        return requests_get(f'{self.settings.kugou_api_base}{path}', params)

    '''metadata-only search via musicdl's anonymous search endpoint (stable JSON)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        rule = {'format': 'json', 'keyword': keywords, 'platform': 'WebFilter',
                'page': page, 'pagesize': limit}
        resp = self.client.get('https://songsearch.kugou.com/song_search_v2?' + urlencode(rule))
        try:
            return ((resp.json() or {}).get('data') or {}).get('lists') or []
        except Exception:
            return []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        name = raw.get('SongName') or raw.get('FileName') or ''
        singer = raw.get('SingerName') or raw.get('singername')
        if ' - ' in name and not singer:
            singer, _, rest = name.partition(' - '); name = rest or name
        return {'id': str(raw.get('FileHash') or ''), 'name': name.strip(), 'singer': singer,
                'album': raw.get('AlbumName'), 'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('Duration') or 0)) or None,
                'cover': raw.get('Image') or raw.get('cover'), 'source': 'kugou'}

    @staticmethod
    def _first_url(v) -> str:
        if isinstance(v, list):
            v = v[0] if v else ''
        return str(v or '')

    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '192k', '128k', 'flac', 'hires'} else 'auto'
        if q == '192k': q = '320k'  # no native 192k tier — snap up to 320k
        t0 = time.perf_counter()
        data = await self.run(self._api_get, '/song/url', {'hash': str(song_id), 'quality': self.QUALITY[q]})
        url = self._first_url(data.get('url')) or self._first_url(data.get('backupUrl'))
        if not url.startswith('http'):
            raise AdapterError(404, f'no url at quality={self.QUALITY[q]} — cookie expired?')
        return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                'url': url, 'ext': (data.get('extName') or 'mp3').lstrip('.'),
                'bitrate_kbps': int(float(data.get('bitRate') or 0)) // 1000 or None,
                'size_bytes': int(float(data.get('fileSize') or 0)) or None,
                'duration_s': (int(float(data.get('timeLength') or 0)) // 1000 or None),
                'cover': None, 'verified': False, 'headers': {},
                'parser': f'kugou-api.{self.QUALITY[q]}',
                'platform_tag': str(data.get('quality') or self.QUALITY[q]),
                'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}

    '''song meta via musicdl's kugou metainfo helper (lowercase fields: songname/singername/album_name)'''
    async def song_info(self, song_id: str) -> dict:
        meta = await self.run(self.client._getsongmetainfo, song_id)
        if not meta:
            raise AdapterError(404, 'song not found')
        first = lambda *keys: next((meta.get(k) for k in keys if meta.get(k)), None)
        return {'id': str(song_id), 'source': self.source_key,
                'name': first('songname', 'SONGNAME', 'songName', 'OriSongName'),
                'singer': first('singername', 'SINGERNAME', 'author_name', 'artist'),
                'album': first('album_name', 'ALBUMNAME', 'album'),
                'duration_s': int(float(first('duration') or 0)) or None,
                'cover': first('cover_url', 'img'), 'raw': {}}

    '''official lyric endpoint of KuGouMusicApi'''
    async def lyric(self, song_id: str) -> str:
        try:
            data = await self.run(self._api_get, '/lyric', {'hash': str(song_id)})
        except Exception:
            return ''
        candidates = data.get('candidates') if isinstance(data.get('candidates'), list) else []
        content = (candidates[0].get('content') if candidates and isinstance(candidates[0], dict) else None)
        return content or data.get('content') or ''
