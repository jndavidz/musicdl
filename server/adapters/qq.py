'''
Function:
    QQ adapter: all playback links come from the third-party parse chain
    (official anonymous GetVkey verified dead in stage-0 spike).
'''
import time
import base64
from .base import SourceAdapter, AdapterError
from ..quality import resolve as resolve_quality, lossless_allowed, LOSSLESS_MSG, LOSSLESS_EXTS
from musicdl.modules.sources.qq import QQMusicClient
from musicdl.modules.utils import AudioLinkTester


class QQAdapter(SourceAdapter):
    source_key = 'qq'

    def _build_client(self) -> QQMusicClient:
        return QQMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-qq', max_retries=2,
            audio_link_tester_timeout=self.settings.tester_timeout,
        )

    '''third-party parse chain by minimal search_result dict'''
    def _via_thirdparty(self, song_id: str):
        return self.client._parsewiththirdpartapis({'mid': song_id}, {})

    '''yuanli SVIP relay (175.27.166.236/kgqq1, verified live 2026-08-23 via plugin instrumentation).
       level: exhigh -> 320k mp3, lossless -> FLAC. Note it resolves via kuwo CDN.
       429 cools the logical relay name (qq:relay.yuanli) and is re-raised.'''
    def _via_yuanli(self, song_id: str, quality: str):
        level = 'lossless' if quality in {'flac', 'hires'} else 'exhigh'
        try:
            resp = self.guarded_sync('qq:relay.yuanli', self.client.get,
                                     'http://175.27.166.236/kgqq1/qq.php',
                                     params={'id': song_id, 'type': 'json', 'level': level}, timeout=(3, 10))
        except AdapterError:
            raise            # 429/cooldown: surfaced, never silently skipped
        except Exception:
            return None
        payload = resp.json() if resp and hasattr(resp, 'json') else {}
        url = ((payload.get('data') or {}).get('url')) or ''
        if not (payload.get('code') == 200 and str(url).startswith('http')): return None
        status = self.client.audio_link_tester.test(url)
        return status if status.get('ok') else None

    '''last-resort aggregate relay (music.3e0.cn, verified live 2026-08-12).
       Returns its own proxy stream (not a CDN direct link) — 320k-class only.'''
    def _via_3e0(self, song_id: str):
        resp = self.guarded_sync('qq:relay.3e0', self.client.get, 'https://music.3e0.cn',
                                 params={'server': 'tencent', 'type': 'url', 'id': song_id},
                                 headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                                 timeout=(3, 10))
        url = (resp.text or '').strip()
        if not url.startswith('http'): return None
        status = self.client.audio_link_tester.test(url)
        if not status.get('ok'): return None
        return status

    '''metadata-only search via musicu.fcg (single POST, no parse chain)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        import json as _json
        from musicdl.modules.utils.qqutils import QQMusicClientUtils, SearchType, Credential
        payload = QQMusicClientUtils.buildrequestdata(
            params={'searchid': QQMusicClientUtils.randomsearchid(), 'query': keywords, 'search_type': SearchType.SONG.value,
                    'num_per_page': limit, 'page_num': page, 'highlight': 0, 'grp': 1},
            module="music.search.SearchCgiService", method="DoSearchForQQMusicMobile", credential=Credential())
        resp = self.client.post(QQMusicClientUtils.endpoint, data=_json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                                timeout=self.io_timeout)
        return ((resp.json().get('music.search.SearchCgiService.DoSearchForQQMusicMobile', {}).get('data', {}).get('body', {}) or {}).get('item_song')) or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        album = raw.get('album') or {}
        file = raw.get('file') or {}
        # search-stage quality stock (exact sizes from tencent) — surfaced so the UI
        # can show what the platform actually stocks before any resolve happens.
        if file.get('size_hires'): stock_tier, stock_size = 'HR', int(file['size_hires'])
        elif file.get('size_flac'): stock_tier, stock_size = 'SQ', int(file['size_flac'])
        elif file.get('size_320mp3'): stock_tier, stock_size = 'HQ', int(file['size_320mp3'])
        elif file.get('size_128mp3'): stock_tier, stock_size = 'PQ', int(file['size_128mp3'])
        else: stock_tier, stock_size = None, None
        return {'id': raw.get('mid') or raw.get('songmid') or '', 'name': raw.get('title') or raw.get('songname'),
                'singer': ', '.join(s.get('name') for s in (raw.get('singer') or []) if isinstance(s, dict) and s.get('name')) or None,
                'album': album.get('title') if isinstance(album, dict) else None,
                'ext': None, 'size_bytes': None,
                'stock_tier': stock_tier, 'stock_size_bytes': stock_size,
                'duration_s': int(float(raw.get('interval') or 0)) or None,
                'cover': f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{album.get('mid', '')}.jpg" if isinstance(album, dict) else None,
                'source': 'qq'}

    '''quality param is advisory for QQ (chain returns the best it can); flac/hires gated likewise'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = resolve_quality(self.source_key, quality)
        if not lossless_allowed(q, self.settings.enable_lossless):
            raise AdapterError(403, LOSSLESS_MSG)
        t0 = time.perf_counter()
        info = await self.run(self._via_thirdparty, song_id)
        elapsed = round((time.perf_counter() - t0) * 1000)
        qq_tag = {'auto': 'HQ 320K', '320k': 'HQ 320K', '128k': 'PQ 128K',
                  'flac': 'SQ 无损', 'hires': 'HR Hi-Res'}[q]
        if not (info.with_valid_download_url and info.ext in AudioLinkTester.VALID_AUDIO_EXTS):
            # chain exhausted -> yuanli SVIP relay, then 3e0 aggregate relay
            fallback = await self.run(self._via_yuanli, song_id, q)
            if fallback:
                return self.url_data(song_id, q,
                                     url=fallback['download_url'], ext=fallback.get('ext') or 'mp3',
                                     size_bytes=fallback.get('file_size_bytes'),
                                     parser='yuanli.relay', platform_tag=qq_tag,
                                     elapsed_ms=round((time.perf_counter() - t0) * 1000))
            fallback = await self.run(self._via_3e0, song_id)
            if fallback:
                return self.url_data(song_id, q,
                                     url=fallback['download_url'], ext=fallback.get('ext') or 'mp3',
                                     size_bytes=fallback.get('file_size_bytes'),
                                     parser='3e0.relay', platform_tag=f'{qq_tag}(聚合降级)',
                                     elapsed_ms=round((time.perf_counter() - t0) * 1000))
            raise AdapterError(404, 'no playable url resolved')
        data = self.urldata_from_songinfo(song_id, q, info, elapsed, platform_tag=qq_tag)
        # annotate actual tier honestly
        if info.ext in LOSSLESS_EXTS: data['quality'] = 'flac' if q not in {'flac', 'hires'} else q
        return data

    '''meta info from official track_info'''
    async def song_info(self, song_id: str) -> dict:
        meta = await self.run(self.client._getsongmetainfo, song_id)
        if not meta: raise AdapterError(404, 'song not found')
        singers = ', '.join(s.get('name') for s in (meta.get('singer') or []) if isinstance(s, dict) and s.get('name'))
        album = (meta.get('album') or {}).get('title') if isinstance(meta.get('album'), dict) else meta.get('albumname')
        return {'id': str(song_id), 'source': self.source_key, 'name': meta.get('title') or meta.get('songname'),
                'singer': singers or None, 'album': album,
                'duration_s': int(float(meta.get('interval') or 0)) or None,
                'cover': f"https://y.gtimg.cn/music/photo_new/T002R800x800M000{(meta.get('album') or {}).get('mid', '')}.jpg",
                'raw': {'qq_meta': {k: meta.get(k) for k in ('title', 'interval', 'songmid') if k in meta}}}

    '''lyric via official fcg endpoint (base64 json)'''
    async def lyric(self, song_id: str) -> str:
        params = {'songmid': str(song_id), 'g_tk': '5381', 'loginUin': '0', 'hostUin': '0',
                  'format': 'json', 'inCharset': 'utf8', 'outCharset': 'utf-8', 'platform': 'yqq'}
        resp = await self.run(self.client.get, 'https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg',
                              headers={'Referer': 'https://y.qq.com/portal/player.html'}, params=params)
        lyric_b64 = (resp.json() or {}).get('lyric') or ''
        if not lyric_b64: return ''
        return base64.b64decode(lyric_b64).decode('utf-8', errors='ignore')

    '''P7 多类型搜索（官方 fcg Desktop 通道，零 Cookie）：search_type 2=album / 1=artist / 3=songlist。
       形状与 musicfree-plugins qq 插件 officialXxxItem 对齐（2026-11-03 实测）。'''
    _QQ_MULTI_SEARCH_TYPE = {'album': 2, 'artist': 1, 'sheet': 3}

    async def search_multi(self, keywords: str, search_type: str, page: int = 1, limit: int = 20) -> dict:
        import json as _json
        from musicdl.modules.utils.qqutils import QQMusicClientUtils, Credential
        payload = {
            'comm': {'ct': 19, 'cv': 1845, 'uin': ''},
            'req_1': {
                'method': 'DoSearchForQQMusicDesktop',
                'module': 'music.search.SearchCgiService',
                'param': {'num_per_page': limit, 'page_num': page, 'query': keywords,
                          'search_type': self._QQ_MULTI_SEARCH_TYPE[search_type]},
            },
        }
        def _post():
            return self.client.post(QQMusicClientUtils.endpoint,
                                    data=_json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                                    timeout=self.io_timeout)
        resp = await self.run(_post)
        d = (resp.json() or {}).get('req_1') or {}
        if d.get('code') != 0:
            raise AdapterError(502, f'qq multi search code={d.get("code")}')
        body = (d.get('data') or {}).get('body') or {}
        total = ((d.get('data') or {}).get('meta') or {}).get('sum')

        if search_type == 'album':
            rows = (body.get('album') or {}).get('list') or []
            items = [{'id': str(a.get('albumID') if a.get('albumID') is not None else a.get('albumid') or ''),
                      'name': a.get('albumName') or a.get('album_name') or '',
                      'artist': a.get('singerName') or a.get('singer_name') or '',
                      'cover': a.get('albumPic') or None, 'track_count': None, 'source': 'qq'}
                     for a in rows if a.get('albumID') is not None or a.get('albumid')]
        elif search_type == 'artist':
            rows = (body.get('singer') or {}).get('list') or []
            items = [{'id': str(s.get('singerID') if s.get('singerID') is not None else s.get('singerid') or ''),
                      'name': s.get('singerName') or '', 'avatar': s.get('singerPic') or None, 'source': 'qq'}
                     for s in rows if s.get('singerID') is not None or s.get('singerid')]
        else:
            rows = (body.get('songlist') or {}).get('list') or []
            items = [{'id': str(p.get('dissid') or ''), 'name': p.get('dissname') or '',
                      'creator': ((p.get('creator') or {}).get('name')) or '',
                      'cover': p.get('imgurl') or None, 'track_count': None,
                      'play_count': p.get('listennum'), 'source': 'qq'}
                     for p in rows if p.get('dissid')]
        return {'items': items, 'total': total}

    '''P6 补齐（2026-11-03）：专辑检索走官方 fcg——候选 search_type=2，首选曲目
       music.musichallAlbum.AlbumSongList（GetAlbumSongList）。形状与 musicfree-plugins
       qq 插件 getAlbumInfo 对齐。曲目解析仍走 /song/url by-id（二段式不变）。'''
    async def album(self, name: str, artist: str = '', page: int = 1) -> dict:
        import json as _json
        from musicdl.modules.utils.qqutils import QQMusicClientUtils, Credential

        def _fcg(payload):
            resp = self.client.post(QQMusicClientUtils.endpoint,
                                    data=_json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                                    timeout=self.io_timeout)
            return resp.json() or {}

        def _search_albums(kw):
            payload = {
                'comm': {'ct': 19, 'cv': 1845, 'uin': ''},
                'req_1': {'method': 'DoSearchForQQMusicDesktop', 'module': 'music.search.SearchCgiService',
                          'param': {'num_per_page': 5, 'page_num': page, 'query': kw, 'search_type': 2}},
            }
            d = _fcg(payload).get('req_1') or {}
            if d.get('code') != 0:
                return []
            body = (d.get('data') or {}).get('body') or {}
            out = []
            for a in (body.get('album') or {}).get('list') or []:
                aid = a.get('albumID') if a.get('albumID') is not None else a.get('albumid')
                if aid is None:
                    continue
                out.append({'id': str(aid), 'mid': a.get('albumMID') or a.get('album_mid') or '',
                            'name': a.get('albumName') or a.get('album_name') or '',
                            'artist': a.get('singerName') or a.get('singer_name') or '',
                            'cover': a.get('albumPic') or None, 'date': a.get('publicTime') or a.get('pub_time'),
                            'source': 'qq'})
            return out

        def _fetch():
            raw = _search_albums(f'{name} {artist}'.strip() if artist else name)
            if not raw and artist:
                raw = _search_albums(name)
            if not raw:
                return {'albums': [], 'items': [], 'total': 0}
            best = raw[0]
            payload = {
                'comm': {'ct': 24, 'cv': 10000},
                'albumSonglist': {
                    'method': 'GetAlbumSongList', 'module': 'music.musichallAlbum.AlbumSongList',
                    'param': {'albumMid': best.get('mid') or '', 'albumID': int(best['id']) if str(best['id']).isdigit() else 0,
                              'begin': 0, 'num': 500, 'order': 2},
                },
            }
            res = _fcg(payload).get('albumSonglist') or {}
            if res.get('code') != 0:
                raise AdapterError(502, f'qq album songlist code={res.get("code")}')
            song_list = ((res.get('data') or {}).get('songList')) or []
            items = []
            for n, x in enumerate(song_list, start=1):
                info = x.get('songInfo') or x
                mid = info.get('mid') or info.get('songmid') or ''
                if not mid:
                    continue
                album = info.get('album') or {}
                cover = None
                album_mid = (album.get('mid') if isinstance(album, dict) else None) or ''
                if album_mid:
                    cover = f'https://y.gtimg.cn/music/photo_new/T002R300x300M000{album_mid}.jpg'
                singers = ', '.join(s.get('name') for s in (info.get('singer') or [])
                                    if isinstance(s, dict) and s.get('name'))
                items.append({'id': str(mid), 'name': info.get('title') or info.get('songname') or '',
                              'singer': singers or None,
                              'album': (album.get('name') or album.get('title')) if isinstance(album, dict) else '',
                              'ext': None, 'size_bytes': None,
                              'duration_s': int(float(info.get('interval') or 0)) or None,
                              'cover': cover, 'source': 'qq', 'track_no': n})
            return {'albums': raw, 'items': items, 'total': len(items)}

        return await self.run(_fetch)
