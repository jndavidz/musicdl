'''
Function:
    Qianqian (Baidu 91q) adapter — signed official API, naturally by-id friendly.
    tracklink(TSID, rate) resolves directly; response also carries song meta.
'''
from .base import SourceAdapter, AdapterError
from ..quality import resolve as resolve_quality, lossless_allowed, LOSSLESS_MSG
from musicdl.modules.sources.qianqian import QianqianMusicClient


class QianqianAdapter(SourceAdapter):
    source_key = 'qianqian'

    def _build_client(self) -> QianqianMusicClient:
        return QianqianMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-qqy', max_retries=2,
        )

    '''metadata-only search via /v1/search (signed), no parse chain'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        params = self.client._addsignandtstoparams(params={'word': keywords, 'type': '1',
                                                  'pageNo': str(page), 'pageSize': str(limit),
                                                  'appid': self.client.APPID})
        resp = self.client.get('https://music.91q.com/v1/search', params=params, timeout=self.io_timeout)
        return ((resp.json().get('data') or {}).get('typeTrack')) or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        artists = ', '.join(a.get('name') for a in (raw.get('artist') or []) if isinstance(a, dict) and a.get('name'))
        return {'id': str(raw.get('TSID') or ''), 'name': raw.get('title'), 'singer': artists or None,
                'album': raw.get('albumTitle'), 'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('duration') or 0)) or None,
                'cover': raw.get('pic'), 'source': 'qianqian'}

    '''P6 专辑检索：/v1/search type=3（候选）→ /v1/album/info（trackList，sort 为官方曲序）。
       曲目 assetId 即 TSID，/song/url 的 tracklink 可直接出链。'''
    async def album(self, name: str, artist: str = '', page: int = 1) -> dict:
        def _search(kw):
            params = self.client._addsignandtstoparams(
                params={'word': kw, 'type': '3', 'pageNo': str(page), 'pageSize': '5',
                        'appid': self.client.APPID})
            resp = self.client.get('https://music.91q.com/v1/search', params=params, timeout=self.io_timeout)
            return ((resp.json().get('data') or {}).get('typeAlbum')) or []

        def _fetch():
            # name+artist 精度更高；无结果再退 name-only（千千对长词几乎零召回）
            raw = _search(f'{name} {artist}'.strip() if artist else name)
            if not raw and artist:
                raw = _search(name)
            albums = []
            for a in raw:
                code = a.get('albumAssetCode')
                if not code:
                    continue
                albums.append({'id': str(code), 'name': a.get('title'),
                               'artist': ', '.join(x.get('name') for x in (a.get('artist') or [])
                                                   if isinstance(x, dict) and x.get('name')) or None,
                               'size': len(a.get('trackList') or []) or None,
                               'cover': a.get('pic'), 'source': self.source_key, 'extra': {}})
            self.rank_candidates(albums, name, artist)
            if not albums:
                return {'albums': [], 'items': []}
            params = self.client._addsignandtstoparams(
                params={'albumAssetCode': albums[0]['id'], 'pageNo': '1', 'pageSize': '200',
                        'appid': self.client.APPID})
            detail = (self.client.get('https://music.91q.com/v1/album/info', params=params, timeout=self.io_timeout)
                      .json().get('data') or {})
            tracks = list({t.get('assetId'): t for t in (detail.get('trackList') or [])
                           if isinstance(t, dict) and t.get('assetId')}.values())
            tracks.sort(key=lambda t: int(t.get('sort') or 0))
            items = []
            for i, t in enumerate(tracks, 1):
                items.append({'id': str(t['assetId']), 'name': t.get('title'),
                              'singer': ', '.join(x.get('name') for x in (t.get('artist') or [])
                                                  if isinstance(x, dict) and x.get('name')) or None,
                              'album': albums[0]['name'], 'ext': None, 'size_bytes': None,
                              'duration_s': int(float(t.get('duration') or 0)) or None,
                              'cover': albums[0]['cover'], 'source': self.source_key,
                              'track_no': i})
            return {'albums': albums, 'items': items}
        return await self.run(_fetch)

    def _tracklink(self, tsid: str, rate: str) -> dict:
        params = self.client._addsignandtstoparams(params={'TSID': tsid, 'appid': self.client.APPID, 'rate': rate})
        resp = self.client.get('https://music.91q.com/v1/song/tracklink', params=params, timeout=self.io_timeout)
        data = (resp.json() or {}).get('data') or {}
        path = data.get('path') or (data.get('trail_audio_info') or {}).get('path') or ''
        # size/format/bits/rate are the server-declared file attributes of THIS link —
        # exact payload size and bit depth, far more reliable than any tier promise.
        return {'path': path if str(path).startswith('http') else '',
                **{k: data.get(k) for k in ('title', 'duration', 'size', 'format', 'bits', 'rate')}}

    '''quality routing: auto/320k/128k capped at 320; flac/hires gated by ENABLE_LOSSLESS'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = resolve_quality(self.source_key, quality)
        t0 = __import__('time').perf_counter()
        import time
        elapsed = lambda: round((time.perf_counter() - t0) * 1000)
        rates = {'128k': ['128'], '320k': ['320'], 'auto': ['320', '128'],
                 'flac': ['3000'], 'hires': ['3000']}[q]
        if not lossless_allowed(q, self.settings.enable_lossless):
            raise AdapterError(403, LOSSLESS_MSG)
        for rate in rates:
            link = await self.run(self._tracklink, song_id, rate)
            if not link['path']: continue
            status = await self.run(self.client.audio_link_tester.test, link['path'])
            if not status.get('ok'): continue
            link_size = int(float(link.get('size') or 0)) or None
            bits = str(link.get('bits') or '')
            platform_tag = f'{rate}kbps' + (f'·{bits}bit' if bits else '')
            return self.url_data(song_id, q,
                                 url=status.get('download_url') or link['path'], ext=status.get('ext'),
                                 size_bytes=status.get('file_size_bytes') or link_size,
                                 bitrate_kbps=int(rate) if rate.isdigit() else None,
                                 duration_s=int(float(link.get('duration') or 0)) or None,
                                 parser=f'tracklink.{rate}', platform_tag=platform_tag,
                                 elapsed_ms=elapsed())
        raise AdapterError(404, f'no playable url resolved (rates tried: {rates})')

    '''song meta via tracklink response fields (works with any available rate)'''
    async def song_info(self, song_id: str) -> dict:
        for rate in ('320', '3000', '128'):
            link = await self.run(self._tracklink, song_id, rate)
            if link['path'] or link.get('title'):
                return {'id': str(song_id), 'source': self.source_key, 'name': link.get('title'),
                        'singer': None, 'album': None,
                        'size_bytes': int(float(link.get('size') or 0)) or None,
                        'duration_s': int(float(link.get('duration') or 0)) or None, 'cover': None,
                        'raw': {'qqy_note': 'full artist/album available in search items'}}
        raise AdapterError(404, 'song not found')

    '''lyric url only exists inside search results; by-id lyric not supported upstream'''
    async def lyric(self, song_id: str) -> str:
        return ''
