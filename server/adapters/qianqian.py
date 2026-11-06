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
        rows = ((resp.json().get('data') or {}).get('typeTrack')) or []
        # 千千的歌词 URL 只挂在搜索结果行上（行内 lyric），没有 by-id 歌词通道；
        # 进程内 id→url 缓存让随后的 /{source}/lyric 能按 id 取到（进程间不共享）。
        self._remember_lyric_urls(rows)
        return rows

    def _remember_lyric_urls(self, rows: list) -> None:
        cache = getattr(self, '_lyric_urls', None)
        if cache is None:
            cache = self._lyric_urls = {}
        for r in rows:
            tsid = str((r or {}).get('TSID') or '')
            url = str((r or {}).get('lyric') or '').strip()
            if not (tsid and url.startswith('http')):
                continue
            if len(cache) >= 500:
                cache.clear()  # 简单有界，不做 LRU：命中率靠「搜索紧跟歌词请求」的调用序
            cache[tsid] = url

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

    '''P9b（2026-11-04，对照 MusicFree qianqian）：歌手作品走官方签名 /v1/artist/song
       （artistCode 分页，返回 TSID 曲目）。上游没有「歌手专辑列表」通道
       （MusicFree 同款只实现 music），album 返回空集合而非 501。'''
    async def artist_works(self, artist_id: str, work_type: str = 'music',
                           page: int = 1, limit: int = 30) -> dict:
        if work_type != 'music':
            return {'type': work_type, 'page': page, 'is_end': True, 'total': 0, 'items': []}

        def _fetch():
            params = self.client._addsignandtstoparams(
                params={'artistCode': str(artist_id), 'pageNo': str(page),
                        'pageSize': str(limit), 'appid': self.client.APPID})
            resp = self.client.get('https://music.91q.com/v1/artist/song',
                                   params=params, timeout=self.io_timeout)
            data = (resp.json() or {}).get('data') or {}
            rows = data.get('result') or []
            total = int(data.get('total') or 0) or len(rows)
            items = [x for x in (self.item_from_raw(r) for r in rows) if x.get('id')]
            return {'type': 'music', 'page': page, 'is_end': page * limit >= total,
                    'total': total, 'items': items}
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

    '''千千没有 by-id 歌词通道：URL 只能从搜索结果行拿到，靠 _search_raw 的进程内缓存；
       缓存未命中（服务重启 / 跨进程）时返回空串，由上层降级为「无歌词」。'''
    async def lyric(self, song_id: str) -> str:
        from musicdl.modules.utils import cleanlrc
        url = (getattr(self, '_lyric_urls', None) or {}).get(str(song_id))
        if not url:
            return ''
        try:
            # 不能把 timeout 传给 run()：run(fn, *args, **kwargs) 的第二个位置参数已是
            # hard timeout，再传 timeout= 会与内置参数重名（TypeError）。
            resp = await self.run(self.client.get, url)
            resp.encoding = 'utf-8'
            return cleanlrc(resp.text)
        except Exception:
            return ''

    '''P7 多类型搜索（官方签名 /v1/search）：type=3 album / type=2 artist（sheet 平台无通道）。
       形状与 musicfree-plugins qianqian 插件 qXxxItem 对齐（2026-11-03 实测）。'''
    async def search_multi(self, keywords: str, search_type: str, page: int = 1, limit: int = 20) -> dict:
        if search_type == 'sheet':
            raise AdapterError(501, f'type search "sheet" not supported for source "{self.source_key}"')
        params = self.client._addsignandtstoparams(
            params={'word': keywords, 'type': '3' if search_type == 'album' else '2',
                    'pageNo': str(page), 'pageSize': str(limit), 'appid': self.client.APPID})
        def _get():
            return self.client.get('https://music.91q.com/v1/search', params=params, timeout=self.io_timeout)
        resp = await self.run(_get)
        j = resp.json() or {}
        if j.get('state') is False or j.get('errno') not in (None, 22000):
            raise AdapterError(502, f'qianqian multi search errno={j.get("errno")}')
        data = j.get('data') or {}
        if search_type == 'album':
            rows = data.get('typeAlbum') or []
            items = [{'id': str(a['albumAssetCode']),
                      'name': a.get('title') or '',
                      'artist': ', '.join(x.get('name') for x in (a.get('artist') or []) if isinstance(x, dict) and x.get('name')),
                      'cover': a.get('pic') or None, 'track_count': None, 'source': 'qianqian'}
                     for a in rows if a.get('albumAssetCode')]
        else:
            rows = data.get('typeArtist') or []
            items = [{'id': str(s['artistCode']), 'name': s.get('name') or '',
                      'avatar': s.get('pic') or None, 'source': 'qianqian'}
                     for s in rows if s.get('artistCode')]
        return {'items': items, 'total': None}
