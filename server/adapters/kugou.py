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
from ..cache import TTLCache
from ..quality import resolve as resolve_quality


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

    '''account cookie assembled from kugou_token.json (TTL cached, file re-read on expiry).
       Public interface: the generic passthrough injects it into container requests.'''
    def account_cookie(self) -> str:
        cache = getattr(self, '_cookie_cache', None)
        if cache is None:
            cache = self._cookie_cache = TTLCache(ttl_seconds=self.settings.cookie_refresh_s)
        ck = cache.get('cookie')
        if ck is None:
            # token file is optional: album/search metadata works anonymously; missing
            # file must degrade to anonymous, not raise out of the route as 502.
            try:
                with open(self.settings.kugou_token_file) as fp:
                    tok = json.load(fp)
                ck = f"token={tok.get('token','')};userid={tok.get('userid','')};dfid={tok.get('dfid','')}"
            except Exception:
                ck = ''
            cache.set('cookie', ck)
        return ck

    '''raw GET against the sibling kugou-api container with cookie attached'''
    def _api_get(self, path: str, params: dict = None) -> dict:
        params = dict(params or {})
        params['cookie'] = self.account_cookie()
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

    '''P6 专辑检索：容器 /search?type=album（候选）→ /album/songs（曲目，extend.disc+sort 为官方曲序）。
       album song 行是嵌套结构（base/audio_info/album_info），需单独映射；id = audio_info.hash。'''
    async def album(self, name: str, artist: str = '', page: int = 1) -> dict:
        def _search(kw):
            data = self._api_get('/search', {'keywords': kw, 'type': 'album',
                                             'page': page, 'pagesize': 5})
            return ((data.get('data') or {}).get('lists')) or []

        def _fetch():
            # name+artist 精度更高；无结果再退 name-only（平台分词差异）
            lists = _search(f'{name} {artist}'.strip() if artist else name)
            if not lists and artist:
                lists = _search(name)
            albums = []
            for a in lists:
                if not a.get('albumid'):
                    continue
                albums.append({'id': str(a['albumid']), 'name': a.get('albumname'),
                               'artist': a.get('singer'), 'size': a.get('songcount'),
                               'cover': a.get('img'), 'source': self.source_key, 'extra': {}})
            self.rank_candidates(albums, name, artist)
            if not albums:
                return {'albums': [], 'items': []}
            detail = self._api_get('/album/songs', {'id': albums[0]['id']})
            songs = ((detail.get('data') or {}).get('songs')) or []
            def _official_order(pair):
                ext = pair[1].get('extend') or {}
                return (int(ext.get('disc') or 1), int(ext.get('sort') or 0), pair[0])
            items = []
            for i, (_, s) in enumerate(sorted(enumerate(songs), key=_official_order), 1):
                base, info, alb = s.get('base') or {}, s.get('audio_info') or {}, s.get('album_info') or {}
                if not info.get('hash'):
                    continue
                cover = (alb.get('cover') or '').replace('{size}', '400') or None
                items.append({'id': str(info['hash']), 'name': base.get('audio_name'),
                              'singer': base.get('author_name'), 'album': alb.get('album_name'),
                              'ext': None, 'size_bytes': None,
                              'duration_s': int(float(info.get('duration') or 0)) or None,
                              'cover': cover, 'source': self.source_key, 'track_no': i})
            return {'albums': albums, 'items': items}
        return await self.run(_fetch)

    async def song_url(self, song_id: str, quality: str) -> dict:
        q = resolve_quality(self.source_key, quality)
        t0 = time.perf_counter()
        data = await self.run(self._api_get, '/song/url', {'hash': str(song_id), 'quality': self.QUALITY[q]})
        url = self._first_url(data.get('url')) or self._first_url(data.get('backupUrl'))
        if not url.startswith('http'):
            raise AdapterError(404, f'no url at quality={self.QUALITY[q]} — cookie expired?')
        return self.url_data(song_id, q,
                             url=url, ext=(data.get('extName') or 'mp3').lstrip('.'),
                             bitrate_kbps=int(float(data.get('bitRate') or 0)) // 1000 or None,
                             size_bytes=int(float(data.get('fileSize') or 0)) or None,
                             duration_s=(int(float(data.get('timeLength') or 0)) // 1000 or None),
                             verified=False, parser=f'kugou-api.{self.QUALITY[q]}',
                             platform_tag=str(data.get('quality') or self.QUALITY[q]),
                             elapsed_ms=round((time.perf_counter() - t0) * 1000))

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

    '''lyric chain: KuGouMusicApi container /lyric first; on failure or empty body
       fall back to kugou's official lyric service (lyrics.kugou.com search ->
       krcs.kugou.com download, anonymous zero-cookie chain, accesskey comes with
       the candidate). Added 2026-10-27: the container /lyric has been stably
       returning 400 error_code 20010 (NAS environment fact), which used to
       degrade to '' for every song.'''
    async def lyric(self, song_id: str) -> str:
        try:
            data = await self.run(self._api_get, '/lyric', {'hash': str(song_id)})
            candidates = data.get('candidates') if isinstance(data.get('candidates'), list) else []
            content = (candidates[0].get('content') if candidates and isinstance(candidates[0], dict) else None)
            text = content or data.get('content') or ''
            if text:
                return text
        except Exception:
            pass
        return await self.run(self._lyric_official, str(song_id))

    '''official lyric service fallback (two anonymous GETs, no cookie needed)'''
    @staticmethod
    def _lyric_official(song_id: str) -> str:
        import base64
        try:
            c = requests_get('https://lyrics.kugou.com/search',
                             {'ver': 1, 'man': 'yes', 'client': 'pc', 'hash': str(song_id)})
            cand = next((x for x in (c.get('candidates') or []) if isinstance(x, dict) and x.get('id')), None)
            if not cand:
                return ''
            d = requests_get('https://krcs.kugou.com/download',
                             {'ver': 1, 'client': 'pc', 'fmt': 'lrc', 'charset': 'utf8',
                              'id': cand.get('id'), 'accesskey': cand.get('accesskey') or ''})
            content = d.get('content') or ''
            return base64.b64decode(content).decode('utf-8', errors='ignore') if content else ''
        except Exception:
            return ''
