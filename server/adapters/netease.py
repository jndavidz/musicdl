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
    album_track_count = True
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
        # same guarded logical entry as every other ncm-api call (429 cooldown applies)
        data = self._api_get('/cloudsearch', {'keywords': keywords, 'limit': limit,
                                              'offset': (page - 1) * limit})
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

    '''lyric_data: /lyric/new 一次取回 lrc + yrc（逐字）。yrc 覆盖是逐曲的事实而非全量
       （20 首抽样 7 首有），无 yrc 时 lxlyric=None，只回退普通 LRC，不造坏数据。'''
    async def lyric_data(self, song_id: str) -> dict:
        from musicdl.modules.utils.lyricfmt import yrc2lxlyric
        try:
            data = await self.run(self._api_get, '/lyric/new', {'id': str(song_id)})
        except Exception:
            return {'lyric': await self.lyric(song_id) or '', 'lxlyric': None}
        lrc = ((data.get('lrc') or {}).get('lyric')) or ''
        yrc = ((data.get('yrc') or {}).get('lyric')) or ''
        if not lrc:
            lrc = await self.lyric(song_id) or ''
        return {'lyric': lrc, 'lxlyric': (yrc2lxlyric(yrc) or None) if yrc else None}

    '''MV 契约（2026-11-06 实测，文档端点 /mv/detail + /mv/url）：
       /song/detail 的 songs[].mv 给 mvid（0=无 MV）→ /mv/detail 给 name/cover/duration(ms)，
       /mv/url 的 r 是**上限**（返回实际 r 与 URL，实测 1080 请求可回落 480）。
       无 mvid 时按 title(+artist) 走 /search?type=1004 只接受**同名**命中——
       宁可 url=None 也不把访谈/翻唱当成本曲 MV。匿名可用；付费 MV 返回 code:-125 + url:null。'''
    @staticmethod
    def _mvnorm(v) -> str:
        return ''.join(str(v or '').lower().split())

    async def mv(self, song_id: str, title: str = '', artist: str = '') -> dict:
        def _song_mvid() -> int:
            detail = self._api_get('/song/detail', {'ids': str(song_id)})
            songs = detail.get('songs') or []
            try:
                return int((songs[0].get('mv') or 0) if songs else 0)
            except (TypeError, ValueError):
                return 0

        def _search_mvid() -> int:
            if not title:
                return 0
            data = self._api_get('/search', {'keywords': title, 'type': 1004, 'limit': 10})
            mvs = ((data.get('result') or {}).get('mvs')) or []
            nt = self._mvnorm(title)
            for m in mvs:
                if self._mvnorm(m.get('name')) != nt:
                    continue
                if artist:
                    na = self._mvnorm(artist)
                    names = [self._mvnorm(a.get('name')) for a in (m.get('artists') or [])]
                    names.append(self._mvnorm(m.get('artistName')))
                    names = [n for n in names if n]
                    if not any(na in n or n in na for n in names):
                        continue
                try:
                    return int(m.get('id') or 0)
                except (TypeError, ValueError):
                    return 0
            return 0

        def _fetch() -> dict:
            empty = {'id': str(song_id), 'source': self.source_key, 'url': None,
                     'cover': None, 'duration_s': None, 'quality': None}
            try:
                mvid = _song_mvid() or _search_mvid()
            except Exception:
                mvid = 0
            if not mvid and str(song_id).isdigit():
                # id 在歌曲库里不存在 → 视为 MV 搜索给出的 mvid（/mv?id= 双口径）
                try:
                    self._api_get('/song/detail', {'ids': str(song_id)})['songs'][0]
                except Exception:
                    mvid = int(song_id)
            if not mvid:
                return empty
            cover, dur_s, name, singer = None, None, (title or None), (artist or None)
            try:
                info = (self._api_get('/mv/detail', {'mvid': str(mvid)}).get('data') or {})
            except Exception:
                info = {}
            if info:
                cover = info.get('cover') or None
                try:
                    dur_s = int(float(info.get('duration') or 0)) // 1000 or None
                except (TypeError, ValueError):
                    dur_s = None
                name = info.get('name') or name
                singer = info.get('artistName') or singer
            for r in (1080, 720, 480, 240):
                try:
                    payload = self._api_get('/mv/url', {'id': str(mvid), 'r': r})
                except Exception:
                    continue
                data = payload.get('data') or {}
                url = data.get('url')
                if isinstance(url, str) and url.startswith('http'):
                    return {'id': str(song_id), 'source': self.source_key, 'url': url,
                            'cover': cover, 'duration_s': dur_s,
                            'quality': self.mv_quality(data.get('r') or r),
                            'title': name, 'artist': singer}
            return empty

        return await self.run(_fetch)

    '''MV 搜索（netease）：cloudsearch type=1004 → result.mvs；id = mvid，与 mv() 的 mvid 口径衔接。
       url 恒为 None（点击后按 id 现取）；quality 无高度信息，置 None 不臆造档位。'''
    async def search_mv(self, keywords: str, page: int = 1, limit: int = 20) -> dict:
        def _fetch():
            data = self._api_get('/cloudsearch', {'keywords': keywords, 'type': 1004,
                                                  'limit': limit, 'offset': (page - 1) * limit})
            res = data.get('result') or {}
            rows = res.get('mvs') or []
            items = []
            for m in rows:
                if not m.get('id'):
                    continue
                try:
                    dur = int(float(m.get('duration') or 0)) // 1000 or None
                except (TypeError, ValueError):
                    dur = None
                artists = [a.get('name') for a in (m.get('artists') or []) if a.get('name')]
                items.append({'id': str(m['id']), 'source': self.source_key, 'title': m.get('name'),
                              'artist': m.get('artistName') or '/'.join(artists) or None,
                              'cover': m.get('cover'), 'duration_s': dur, 'quality': None, 'url': None})
            return {'items': items, 'total': res.get('mvCount') or len(items)}
        return await self.run(_fetch)

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

    '''P9（2026-11-04）：浏览能力收编（类型搜索/榜单/推荐/歌手/评论），映射自 kwqq 插件
       netease 透传拆包逻辑（多年现网形状）。上游 ncm-api 免登即可；评论回搜/详情经
       /cloudsearch /comment/music。曲目 id=netease song id，与 /netease/song/url 口径一致。'''

    @staticmethod
    def _nm_cover(url, size=300):
        return f'{url}?param={size}y{size}' if url else None

    async def search_multi(self, keywords: str, search_type: str, page: int = 1, limit: int = 20) -> dict:
        type_no = {'album': 10, 'artist': 100, 'sheet': 1000}[search_type]
        data = await self.run(self._api_get, '/cloudsearch',
                              {'keywords': keywords, 'type': type_no,
                               'limit': limit, 'offset': (page - 1) * limit})
        res = (data or {}).get('result') or {}
        if search_type == 'album':
            total = res.get('albumCount') or 0
            items = [{'id': str(a['id']), 'name': a.get('name') or '',
                      'artist': ((a.get('artist') or {}).get('name')
                                 or ', '.join(x.get('name') for x in (a.get('artists') or [])
                                              if isinstance(x, dict) and x.get('name')) or ''),
                      'cover': self._nm_cover(a.get('picUrl')),
                      'track_count': a.get('size') or 0, 'source': 'netease'}
                     for a in res.get('albums') or [] if a.get('id')]
        elif search_type == 'artist':
            total = res.get('artistCount') or 0
            items = [{'id': str(a['id']), 'name': a.get('name') or '',
                      'avatar': self._nm_cover(a.get('picUrl') or a.get('img1v1Url'), 200),
                      'alias': (a.get('alias') or [None])[0] if a.get('alias') else None,
                      'album_count': a.get('albumSize') or 0,
                      'music_count': a.get('musicSize') or 0, 'source': 'netease'}
                     for a in res.get('artists') or [] if a.get('id')]
        else:
            total = res.get('playlistCount') or 0
            items = [{'id': str(p['id']), 'name': p.get('name') or '',
                      'creator': ((p.get('creator') or {}).get('nickname') or ''),
                      'cover': self._nm_cover(p.get('coverImgUrl') or p.get('picUrl')),
                      'track_count': p.get('trackCount') or 0,
                      'play_count': p.get('playCount') or 0,
                      'description': p.get('description'), 'source': 'netease'}
                     for p in res.get('playlists') or [] if p.get('id')]
        return {'items': items, 'total': total}

    async def toplists(self) -> dict:
        data = await self.run(self._api_get, '/toplist')
        items = [{'id': str(it['id']), 'name': it.get('name') or '',
                  'cover': self._nm_cover(it.get('coverImgUrl') or it.get('picUrl')),
                  'description': it.get('description'),
                  'update_frequency': it.get('updateFrequency'),
                  'source': 'netease'}
                 for it in (data or {}).get('list') or [] if it.get('id')]
        return {'items': items}

    async def toplist_songs(self, toplist_id: str, page: int = 1, limit: int = 50) -> dict:
        # netease 榜单 id 即 playlist id；offset 分页
        data = await self.run(self._api_get, '/playlist/track/all',
                              {'id': toplist_id, 'limit': limit, 'offset': (page - 1) * limit})
        songs = (data or {}).get('songs') or []
        total = (data or {}).get('total') or len(songs)
        return {'page': page, 'is_end': (page - 1) * limit + len(songs) >= total,
                'total': total, 'items': [self.item_from_raw(m) for m in songs]}

    async def playlist_tags(self) -> dict:
        hot = await self.run(self._api_get, '/playlist/hot')
        pinned = [{'id': t['name'], 'title': t.get('name') or ''}
                  for t in ((hot or {}).get('tags') or [])[:8] if t.get('name')]
        groups = []
        try:
            cat = await self.run(self._api_get, '/playlist/catlist')
            names = (cat or {}).get('categories') or {}
            grouped = {}
            for sub in (cat or {}).get('sub') or []:
                if not sub.get('name'):
                    continue
                grouped.setdefault(names.get(str(sub.get('category'))) or '其他', []).append(
                    {'id': sub['name'], 'title': sub['name']})
            groups = [{'title': title, 'data': tags} for title, tags in grouped.items()]
        except Exception:
            pass  # catlist 失败时只给 pinned（插件既有语义）
        return {'pinned': pinned, 'groups': groups}

    async def playlist_sheets(self, tag: str, page: int = 1, limit: int = 30) -> dict:
        params = {'limit': limit, 'offset': (page - 1) * limit, 'order': 'hot'}
        if tag:
            params['cat'] = tag
            path = '/top/playlist'
        else:
            path = '/top/playlist'
        data = await self.run(self._api_get, path, params)
        playlists = (data or {}).get('playlists') or []
        total = (data or {}).get('total') or len(playlists)
        items = [{'id': str(p['id']), 'name': p.get('name') or '',
                  'creator': ((p.get('creator') or {}).get('nickname') or ''),
                  'cover': self._nm_cover(p.get('coverImgUrl') or p.get('picUrl')),
                  'track_count': p.get('trackCount') or 0,
                  'play_count': p.get('playCount') or 0,
                  'description': p.get('description'), 'source': 'netease'}
                 for p in playlists if p.get('id')]
        return {'tag': tag, 'page': page, 'is_end': (page - 1) * limit + len(items) >= total,
                'total': total, 'items': items}

    async def playlist_songs(self, playlist_id: str, page: int = 1, limit: int = 50) -> dict:
        data = await self.run(self._api_get, '/playlist/track/all',
                              {'id': playlist_id, 'limit': limit, 'offset': (page - 1) * limit})
        songs = (data or {}).get('songs') or []
        total = (data or {}).get('total') or len(songs)
        items = [self.item_from_raw(m) for m in songs]
        meta = None
        if page == 1:
            try:
                detail = await self.run(self._api_get, '/playlist/detail', {'id': playlist_id})
                pl = (detail or {}).get('playlist') or {}
                meta = {'id': str(pl.get('id') or playlist_id), 'name': pl.get('name') or '',
                        'creator': ((pl.get('creator') or {}).get('nickname') or ''),
                        'cover': self._nm_cover(pl.get('coverImgUrl'), 500),
                        'track_count': pl.get('trackCount') or total,
                        'play_count': pl.get('playCount') or 0,
                        'extra': {'description': pl.get('description')}}
            except Exception:
                meta = None  # 元数据缺失不阻塞曲目
        return {'page': page, 'is_end': (page - 1) * limit + len(songs) >= total,
                'total': total, 'items': items, 'meta': meta}

    async def artist_info(self, artist_id: str) -> dict:
        data = await self.run(self._api_get, '/artists', {'id': artist_id})
        ar = (data or {}).get('artist') or {}
        return {'artist': {'id': str(ar.get('id') or artist_id), 'name': ar.get('name') or '',
                           'avatar': self._nm_cover(ar.get('picUrl') or ar.get('img1v1Url')),
                           'alias': (ar.get('alias') or [None])[0] if ar.get('alias') else None,
                           'description': ar.get('briefDesc') or ar.get('description'),
                           'album_count': ar.get('albumSize') or 0,
                           'music_count': ar.get('musicSize') or 0, 'source': 'netease'}}

    '''P9（2026-11-04）：浏览能力收编（类型搜索/榜单/推荐/歌手/评论），映射自 kwqq 插件
    netease 透传拆包逻辑（多年现网形状）。曲目 id=netease song id，与 song/url 口径一致。'''

    @staticmethod
    def _nm_cover(url, size=300):
        return (url + '?param=' + str(size) + 'y' + str(size)) if url else None

    async def search_multi(self, keywords: str, search_type: str, page: int = 1, limit: int = 20) -> dict:
        type_no = {'album': 10, 'artist': 100, 'sheet': 1000}[search_type]
        data = await self.run(self._api_get, '/cloudsearch',
                              {'keywords': keywords, 'type': type_no,
                               'limit': limit, 'offset': (page - 1) * limit})
        res = (data or {}).get('result') or {}
        if search_type == 'album':
            total = res.get('albumCount') or 0
            items = [{'id': str(a['id']), 'name': a.get('name') or '',
                      'artist': ((a.get('artist') or {}).get('name')
                                 or ', '.join(x.get('name') for x in (a.get('artists') or [])
                                              if isinstance(x, dict) and x.get('name')) or ''),
                      'cover': self._nm_cover(a.get('picUrl')),
                      'track_count': a.get('size') or 0, 'source': 'netease'}
                     for a in res.get('albums') or [] if a.get('id')]
        elif search_type == 'artist':
            total = res.get('artistCount') or 0
            items = [{'id': str(a['id']), 'name': a.get('name') or '',
                      'avatar': self._nm_cover(a.get('picUrl') or a.get('img1v1Url'), 200),
                      'alias': (a.get('alias') or [None])[0] if a.get('alias') else None,
                      'album_count': a.get('albumSize') or 0,
                      'music_count': a.get('musicSize') or 0, 'source': 'netease'}
                     for a in res.get('artists') or [] if a.get('id')]
        else:
            total = res.get('playlistCount') or 0
            items = [{'id': str(p['id']), 'name': p.get('name') or '',
                      'creator': ((p.get('creator') or {}).get('nickname') or ''),
                      'cover': self._nm_cover(p.get('coverImgUrl') or p.get('picUrl')),
                      'track_count': p.get('trackCount') or 0,
                      'play_count': p.get('playCount') or 0,
                      'description': p.get('description'), 'source': 'netease'}
                     for p in res.get('playlists') or [] if p.get('id')]
        return {'items': items, 'total': total}

    async def toplists(self) -> dict:
        data = await self.run(self._api_get, '/toplist')
        items = [{'id': str(it['id']), 'name': it.get('name') or '',
                  'cover': self._nm_cover(it.get('coverImgUrl') or it.get('picUrl')),
                  'description': it.get('description'),
                  'update_frequency': it.get('updateFrequency'),
                  'source': 'netease'}
                 for it in (data or {}).get('list') or [] if it.get('id')]
        return {'items': items}

    async def toplist_songs(self, toplist_id: str, page: int = 1, limit: int = 50) -> dict:
        # netease 榜单 id 即 playlist id；offset 分页
        data = await self.run(self._api_get, '/playlist/track/all',
                              {'id': toplist_id, 'limit': limit, 'offset': (page - 1) * limit})
        songs = (data or {}).get('songs') or []
        total = (data or {}).get('total') or len(songs)
        return {'page': page, 'is_end': (page - 1) * limit + len(songs) >= total,
                'total': total, 'items': [self.item_from_raw(m) for m in songs]}

    async def playlist_tags(self) -> dict:
        hot = await self.run(self._api_get, '/playlist/hot')
        pinned = [{'id': t['name'], 'title': t.get('name') or ''}
                  for t in ((hot or {}).get('tags') or [])[:8] if t.get('name')]
        groups = []
        try:
            cat = await self.run(self._api_get, '/playlist/catlist')
            names = (cat or {}).get('categories') or {}
            grouped = {}
            for sub in (cat or {}).get('sub') or []:
                if not sub.get('name'):
                    continue
                grouped.setdefault(names.get(str(sub.get('category'))) or '其他', []).append(
                    {'id': sub['name'], 'title': sub['name']})
            groups = [{'title': title, 'data': tags} for title, tags in grouped.items()]
        except Exception:
            pass  # catlist 失败时只给 pinned（插件既有语义）
        return {'pinned': pinned, 'groups': groups}

    async def playlist_sheets(self, tag: str, page: int = 1, limit: int = 30) -> dict:
        params = {'limit': limit, 'offset': (page - 1) * limit, 'order': 'hot'}
        if tag:
            params['cat'] = tag
        data = await self.run(self._api_get, '/top/playlist', params)
        playlists = (data or {}).get('playlists') or []
        total = (data or {}).get('total') or len(playlists)
        items = [{'id': str(p['id']), 'name': p.get('name') or '',
                  'creator': ((p.get('creator') or {}).get('nickname') or ''),
                  'cover': self._nm_cover(p.get('coverImgUrl') or p.get('picUrl')),
                  'track_count': p.get('trackCount') or 0,
                  'play_count': p.get('playCount') or 0,
                  'description': p.get('description'), 'source': 'netease'}
                 for p in playlists if p.get('id')]
        return {'tag': tag, 'page': page, 'is_end': (page - 1) * limit + len(items) >= total,
                'total': total, 'items': items}

    async def playlist_songs(self, playlist_id: str, page: int = 1, limit: int = 50) -> dict:
        data = await self.run(self._api_get, '/playlist/track/all',
                              {'id': playlist_id, 'limit': limit, 'offset': (page - 1) * limit})
        songs = (data or {}).get('songs') or []
        total = (data or {}).get('total') or len(songs)
        items = [self.item_from_raw(m) for m in songs]
        meta = None
        if page == 1:
            try:
                detail = await self.run(self._api_get, '/playlist/detail', {'id': playlist_id})
                pl = (detail or {}).get('playlist') or {}
                meta = {'id': str(pl.get('id') or playlist_id), 'name': pl.get('name') or '',
                        'creator': ((pl.get('creator') or {}).get('nickname') or ''),
                        'cover': self._nm_cover(pl.get('coverImgUrl'), 500),
                        'track_count': pl.get('trackCount') or total,
                        'play_count': pl.get('playCount') or 0,
                        'extra': {'description': pl.get('description')}}
            except Exception:
                meta = None  # 元数据缺失不阻塞曲目
        return {'page': page, 'is_end': (page - 1) * limit + len(songs) >= total,
                'total': total, 'items': items, 'meta': meta}

    async def artist_info(self, artist_id: str) -> dict:
        data = await self.run(self._api_get, '/artists', {'id': artist_id})
        ar = (data or {}).get('artist') or {}
        return {'artist': {'id': str(ar.get('id') or artist_id), 'name': ar.get('name') or '',
                           'avatar': self._nm_cover(ar.get('picUrl') or ar.get('img1v1Url')),
                           'alias': (ar.get('alias') or [None])[0] if ar.get('alias') else None,
                           'description': ar.get('briefDesc') or ar.get('description'),
                           'album_count': ar.get('albumSize') or 0,
                           'music_count': ar.get('musicSize') or 0, 'source': 'netease'}}

    async def artist_works(self, artist_id: str, work_type: str = 'music',
                           page: int = 1, limit: int = 30) -> dict:
        offset = (page - 1) * limit
        if work_type == 'music':
            data = await self.run(self._api_get, '/artist/songs',
                                  {'id': artist_id, 'limit': limit, 'offset': offset, 'order': 'hot'})
            songs = (data or {}).get('songs') or []
            total = (data or {}).get('total') or len(songs)
            return {'type': work_type, 'page': page,
                    'is_end': offset + len(songs) >= total, 'total': total,
                    'items': [self.item_from_raw(m) for m in songs]}
        data = await self.run(self._api_get, '/artist/album',
                              {'id': artist_id, 'limit': limit, 'offset': offset})
        albums = (data or {}).get('hotAlbums') or []
        total = ((data or {}).get('artist') or {}).get('albumSize') or len(albums)
        items = [{'id': str(a['id']), 'name': a.get('name') or '',
                  'artist': ((a.get('artist') or {}).get('name') or ''),
                  'cover': self._nm_cover(a.get('picUrl')),
                  'track_count': a.get('size') or 0,
                  'extra': {'publish_time': a.get('publishTime'), 'company': a.get('company')},
                  'source': 'netease'}
                 for a in albums if a.get('id')]
        return {'type': work_type, 'page': page,
                'is_end': offset + len(albums) >= total, 'total': total, 'items': items}

    async def music_comments(self, song_id: str = None, title: str = '', artist: str = '',
                             page: int = 1, limit: int = 20) -> dict:
        if not song_id and title:
            found = await self.run(self._api_get, '/cloudsearch',
                                   {'keywords': (title + ' ' + artist).strip(),
                                    'type': 1, 'limit': 1, 'offset': 0})
            songs = ((found or {}).get('result') or {}).get('songs') or []
            if not songs:
                return {'id': '', 'page': page, 'total': 0, 'has_more': False, 'hot': [], 'items': []}
            song_id = str(songs[0].get('id'))
        if not song_id:
            raise AdapterError(400, 'id or title required')

        def _comment(c):
            if not c:
                return None
            user = c.get('user') or {}
            # netease 的 time 是毫秒；契约统一出 Unix 秒 create_time，created_at 保留毫秒兼容旧客户端。
            try:
                ts_ms = int(c.get('time'))
            except (TypeError, ValueError):
                ts_ms = None
            return {'id': str(c.get('commentId') or ''), 'nick_name': user.get('nickname') or '匿名用户',
                    'avatar': user.get('avatarUrl'), 'content': c.get('content') or '',
                    'like': c.get('likedCount'), 'created_at': ts_ms,
                    'create_time': (ts_ms // 1000) if ts_ms else None, 'replies': []}

        data = await self.run(self._api_get, '/comment/music',
                              {'id': song_id, 'limit': limit, 'offset': (page - 1) * limit})
        total = (data or {}).get('total')
        has_more = bool((data or {}).get('more'))
        hot = [c for c in (_comment(x) for x in (data or {}).get('hotComments') or []) if c]
        items = [c for c in (_comment(x) for x in (data or {}).get('comments') or []) if c]
        return {'id': song_id, 'page': page, 'total': total, 'has_more': has_more,
                'hot': hot if page == 1 else [], 'items': items}

    '''P9b（2026-11-04）：专辑 by-id 详情（kwqq 插件 album/info 的 netease id 精确分支收编）。'''
    async def album_detail(self, album_id: str) -> dict:
        data = await self.run(self._api_get, '/album', {'id': album_id})
        al = (data or {}).get('album') or {}
        songs = (data or {}).get('songs') or []
        albums = [{'id': str(al.get('id') or album_id), 'name': al.get('name') or '',
                   'artist': ((al.get('artist') or {}).get('name') or ''),
                   'size': al.get('size') or len(songs),
                   'cover': self._nm_cover(al.get('picUrl'), 500),
                   'source': self.source_key,
                   'extra': {'publish_time': al.get('publishTime'), 'company': al.get('company'),
                             'description': al.get('description')}}] if al else []
        items = []
        for i, s in enumerate(sorted((s for s in songs if s.get('id')),
                                     key=lambda s: (s.get('no') or 0)), 1):
            item = self.item_from_raw(s)
            item['track_no'] = s.get('no') or i
            items.append(item)
        return {'albums': albums, 'items': items}

    '''P9c（2026-11-04）：导入协议（MusicFree importMusicItem/importMusicSheet）。
       urlLike 提取 id：纯数字 / ?id= 参数 / 路径段数字（musicfree shared extractId 同式）。'''
    _IMPORT_CAP = 1000

    @staticmethod
    def _extract_id(url_like: str):
        import re
        s = str(url_like or '').strip()
        if re.fullmatch(r'\d+', s):
            return s
        m = re.search(r'[?&](?:id|specialid|album_id)=(\d+)', s, re.I)
        if m:
            return m.group(1)
        m2 = re.search(r'/(\d+)/?(?:[?#]|$)', s)
        return m2.group(1) if m2 else None

    async def import_item(self, url_like: str) -> dict:
        sid = self._extract_id(url_like)
        if not sid:
            raise AdapterError(400, 'cannot extract song id from urlLike')
        data = await self.run(self._api_get, '/song/detail', {'ids': sid})
        songs = (data or {}).get('songs') or []
        if not songs:
            raise AdapterError(404, f'song not found (id={sid})')
        return {'item': self.item_from_raw(songs[0])}

    async def import_sheet(self, url_like: str, cap: int = 1000) -> dict:
        pid = self._extract_id(url_like)
        if not pid:
            raise AdapterError(400, 'cannot extract playlist id from urlLike')
        items, offset, limit, truncated = [], 0, 500, False
        while len(items) < cap:
            data = await self.run(self._api_get, '/playlist/track/all',
                                  {'id': pid, 'limit': limit, 'offset': offset})
            songs = (data or {}).get('songs') or []
            if not songs:
                break
            for m in songs:
                if len(items) >= cap:
                    truncated = True
                    break
                items.append(self.item_from_raw(m))
            if len(songs) < limit or truncated:
                break
            offset += limit
        return {'items': items, 'total': len(items), 'truncated': truncated}
