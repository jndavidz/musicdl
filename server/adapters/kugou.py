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
    album_track_count = True
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

    '''raw GET against the sibling kugou-api container with cookie attached.
       cooldown is keyed by the LOGICAL endpoint (kugou:container), so a 429 on the
       container is not bypassed by re-pointing KUGOU_API_BASE at an alias.'''
    def _api_get(self, path: str, params: dict = None) -> dict:
        params = dict(params or {})
        params['cookie'] = self.account_cookie()
        return self.guarded_sync('kugou:container', requests_get, f'{self.settings.kugou_api_base}{path}', params)

    '''metadata-only search via musicdl's anonymous search endpoint (stable JSON)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        rule = {'format': 'json', 'keyword': keywords, 'platform': 'WebFilter',
                'page': page, 'pagesize': limit}
        resp = self.client.get('https://songsearch.kugou.com/song_search_v2?' + urlencode(rule), timeout=self.io_timeout)
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
        # songsearch returns the cover as a template URL with a literal `{size}`
        # placeholder (http://imge.kugou.com/stdmusic/{size}/...); 240 is the size
        # every other kugou path uses, and unsubstituted `{size}` 404s.
        return {'id': str(raw.get('FileHash') or ''), 'name': name.strip(), 'singer': singer,
                'album': raw.get('AlbumName'), 'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('Duration') or 0)) or None,
                'cover': KugouAdapter._kg_cover(raw.get('Image') or raw.get('cover')),
                'source': 'kugou'}

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
                               'cover': self._kg_cover(a.get('img')), 'source': self.source_key, 'extra': {}})
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
                'cover': self._kg_cover(first('cover_url', 'img')), 'raw': {}}

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

    '''逐字歌词（lxlyric）：与上方 lyric 同一官方通道，仅把 fmt 换成 krc。
       KuGouMusicApi 容器没有 krc 能力（/lyric 只返回 lrc），故逐字固定走官方零 Cookie 链。'''
    async def lyric_data(self, song_id: str) -> dict:
        lyric = await self.lyric(song_id)
        lxlyric = await self.run(self._lxlyric_official, str(song_id))
        return {'lyric': lyric or '', 'lxlyric': lxlyric or None}

    '''krc 文件结构（2026-11-06 现网实测）：4 字节 'krc1' 头 + XOR(key) + zlib 压缩的 UTF-8 文本；
       行格式 [行起始ms,行时长ms]……逐字 <相对行首偏移ms,时长ms,保留位>文本。'''
    _KRC_KEY = (0x40, 0x47, 0x61, 0x77, 0x5e, 0x32, 0x74, 0x47,
                0x51, 0x36, 0x31, 0x2d, 0xce, 0xd2, 0x6e, 0x69)

    @staticmethod
    def _lxlyric_official(song_id: str) -> str:
        import base64
        try:
            c = requests_get('https://lyrics.kugou.com/search',
                             {'ver': 1, 'man': 'yes', 'client': 'pc', 'hash': str(song_id)})
            cand = next((x for x in (c.get('candidates') or []) if isinstance(x, dict) and x.get('id')), None)
            if not cand:
                return ''
            d = requests_get('https://krcs.kugou.com/download',
                             {'ver': 1, 'client': 'pc', 'fmt': 'krc', 'charset': 'utf8',
                              'id': cand.get('id'), 'accesskey': cand.get('accesskey') or ''})
            content = d.get('content') or ''
            return KugouAdapter._krc_to_lxlyric(base64.b64decode(content)) if content else ''
        except Exception:
            return ''

    '''KRC → 洛雪逐字格式（行 [mm:ss.mmm] + 逐字 <偏移,时长>文本）。
       KRC 的第三个数字是保留位，客户端解析器只认两段 <a,b>，必须丢弃。'''
    @staticmethod
    def _krc_to_lxlyric(raw: bytes) -> str:
        import re
        import zlib
        if not raw or raw[:4] != b'krc1':
            return ''
        body = bytearray(raw[4:])
        key = KugouAdapter._KRC_KEY
        for i in range(len(body)):
            body[i] ^= key[i % 16]
        try:
            text = zlib.decompress(bytes(body)).decode('utf-8', errors='ignore')
        except Exception:
            return ''
        out = []
        for line in text.splitlines():
            m = re.match(r'\[(\d+),\d+\](.*)', line.strip('\r'))
            if not m:
                continue
            start, content = int(m.group(1)), m.group(2)
            parts = re.split(r'<(\d+),(\d+)(?:,\d+)?>', content)
            segs = [(0, 0, parts[0])] if parts[0] else []
            for i in range(1, len(parts), 3):
                segs.append((int(parts[i]), int(parts[i + 1]), parts[i + 2]))
            segs = [s for s in segs if s[2]]
            if not segs:
                continue
            ts = f'[{start // 60000:02d}:{start // 1000 % 60:02d}.{start % 1000:03d}]'
            out.append(ts + ''.join(f'<{off},{dur}>{txt}' for off, dur, txt in segs))
        return '\n'.join(out)

    '''P9（2026-11-04）：浏览能力收编（类型搜索/榜单/推荐/歌手/评论），映射自 kwqq 插件
    kugou 透传拆包逻辑（2026-11-03/04 现网实测形状）。上游 = kugouapi 容器同名模块。
    曲目 id=hash（rank/audio 取 hash_320 优先降档，与搜曲通道 128 hash 经 media 链
    quality 换档均实测可解析）；歌单 id=gid（global_collection_id，specialid 必 20010）。'''

    _KG_COVER_240 = ('{size}', '240')

    @staticmethod
    def _kg_cover(v, size='240'):
        return str(v or '').replace('{size}', size) or None

    @staticmethod
    def _kg_int(v):
        try:
            return int(str(v))
        except (TypeError, ValueError):
            return None

    async def search_multi(self, keywords: str, search_type: str, page: int = 1, limit: int = 20) -> dict:
        # kugouapi /search 的 type 是字符串枚举：album / author / special（数字不分流，实测确认）
        type_map = {'album': 'album', 'artist': 'author', 'sheet': 'special'}
        data = await self.run(self._api_get, '/search',
                              {'keywords': keywords, 'type': type_map[search_type],
                               'page': page, 'pagesize': limit})
        d = (data or {}).get('data') or data or {}
        rows = d.get('lists') or []
        total = self._kg_int(d.get('total')) or len(rows)
        if search_type == 'album':
            items = []
            for r in rows:
                if not r.get('albumid'):
                    continue
                singers = r.get('singers')
                items.append({'id': str(r['albumid']), 'name': r.get('albumname') or '',
                              'artist': (' / '.join(x.get('name') for x in singers if isinstance(x, dict))
                                         if isinstance(singers, list) else (r.get('singer') or '')),
                              'cover': self._kg_cover(r.get('img')),
                              'track_count': self._kg_int(r.get('songcount') or r.get('song_count')),
                              'source': 'kugou'})
        elif search_type == 'artist':
            items = []
            for r in rows:
                aid = r.get('AuthorId') or r.get('singerid')
                if not aid:
                    continue
                items.append({'id': str(aid), 'name': r.get('AuthorName') or r.get('singername') or '',
                              'avatar': r.get('Avatar') or r.get('avatar'), 'source': 'kugou'})
        else:
            items = []
            for r in rows:
                pid = r.get('specialid') or r.get('gid')
                if not pid:
                    continue
                # 歌单详情 /playlist/track/all 只认 gid，id 口径 gid 优先
                items.append({'id': str(r.get('gid') or pid), 'name': r.get('specialname') or '',
                              'creator': r.get('nickname') or '', 'cover': r.get('img'),
                              'track_count': self._kg_int(r.get('song_count')), 'source': 'kugou'})
        return {'items': items, 'total': total}

    async def toplists(self) -> dict:
        data = await self.run(self._api_get, '/rank/list')
        info = ((data or {}).get('data') or {}).get('info') or (data or {}).get('info') or []
        items = [{'id': str(it.get('rankid') or it.get('rank_cid') or it.get('id')),
                  'name': it.get('rankname') or '',
                  'cover': self._kg_cover(it.get('album_img_9') or it.get('img_9') or it.get('imgurl')),
                  'description': it.get('intro'),
                  'update_frequency': it.get('update_frequency'),
                  'source': 'kugou'}
                 for it in info if it.get('rankid') or it.get('rank_cid') or it.get('id')]
        return {'items': items}

    async def toplist_songs(self, toplist_id: str, page: int = 1, limit: int = 50) -> dict:
        data = await self.run(self._api_get, '/rank/audio',
                              {'rankid': toplist_id, 'page': page, 'pagesize': limit})
        d = (data or {}).get('data') or {}
        songs = d.get('songlist') or []
        total = self._kg_int(d.get('total')) or len(songs)
        items = [self._rank_song(m) for m in songs]
        return {'page': page, 'is_end': page * limit >= total,
                'total': total, 'items': [i for i in items if i]}

    @staticmethod
    def _rank_song(s):
        ai = s.get('audio_info') or {}
        authors = [a.get('author_name') for a in (s.get('authors') or []) if isinstance(a, dict)]
        artist = ' / '.join(a for a in authors if a) or s.get('author_name') or ''
        album_name = (s.get('album_info') or {}).get('album_name') or ''
        cover = ((s.get('album_info') or {}).get('sizable_cover')
                 or (s.get('trans_param') or {}).get('union_cover') or '')
        return {'id': (ai.get('hash_320') or ai.get('hash_128') or ai.get('hash') or ''),
                'name': s.get('songname') or '', 'singer': artist, 'album': album_name,
                'duration_s': int((ai.get('duration_128') or 0) / 1000) or None,
                'cover': KugouAdapter._kg_cover(cover), 'source': 'kugou'}

    async def playlist_tags(self) -> dict:
        data = await self.run(self._api_get, '/playlist/tags')
        tags = (data or {}).get('data') or []
        groups = []
        for cat in tags:
            son = [{'id': str(s.get('tag_id')), 'title': s.get('tag_name') or ''}
                   for s in (cat.get('son') or []) if s.get('tag_id')]
            if son:
                groups.append({'title': cat.get('tag_name') or '', 'data': son})
        pinned = [{'id': str(s.get('tag_id')), 'title': s.get('tag_name') or ''}
                  for s in (((tags[0] or {}).get('son') or [])[:8]) if s.get('tag_id')] if tags else []
        return {'pinned': pinned, 'groups': groups}

    async def playlist_sheets(self, tag: str, page: int = 1, limit: int = 30) -> dict:
        data = await self.run(self._api_get, '/top/playlist',
                              {'category_id': tag or '0', 'page': page, 'pagesize': limit})
        d = (data or {}).get('data') or {}
        specials = d.get('special_list') or []
        items = []
        for sp in specials:
            pid = sp.get('global_collection_id') or sp.get('specialid')
            if not pid:
                continue
            items.append({'id': str(pid), 'name': sp.get('specialname') or '',
                          'creator': sp.get('nickname') or '',
                          'cover': self._kg_cover(sp.get('flexible_cover') or sp.get('imgurl')),
                          'track_count': self._kg_int(sp.get('songcount') or sp.get('song_count')),
                          'play_count': self._kg_int(sp.get('play_count')),
                          'source': 'kugou'})
        return {'tag': tag, 'page': page, 'is_end': not d.get('has_next'),
                'total': len(items) if not d.get('has_next') else None, 'items': items}

    async def playlist_songs(self, playlist_id: str, page: int = 1, limit: int = 50) -> dict:
        # **必须 gid（global_collection_id）**，specialid 实测 20010；page=1 自带 list_info 元数据
        data = await self.run(self._api_get, '/playlist/track/all',
                              {'id': playlist_id, 'page': page, 'pagesize': limit})
        if (data or {}).get('error_code') not in (0, None):
            raise AdapterError(404, 'playlist tracks unavailable: '
                               + str(data.get('errmsg') or data.get('error_code')))
        d = (data or {}).get('data') or {}
        songs = d.get('songs') or []
        total = self._kg_int(d.get('count')) or len(songs)
        items = [i for i in (self._playlist_song(m) for m in songs) if i]
        meta = None
        if page == 1 and d.get('list_info'):
            li = d['list_info']
            meta = {'id': str(li.get('global_collection_id') or li.get('specialid') or playlist_id),
                    'name': li.get('name') or '', 'creator': li.get('list_create_username') or '',
                    'cover': self._kg_cover(li.get('pic'), '480'),
                    'track_count': self._kg_int(li.get('count')) or total,
                    'extra': {'play_count': self._kg_int(li.get('collect_total')),
                              'description': li.get('intro')}}
        return {'page': page, 'is_end': page * limit >= total,
                'total': total, 'items': items, 'meta': meta}

    @staticmethod
    def _playlist_song(it):
        # 老接口形状：name 是「歌手 - 歌名」，singerinfo 才可靠
        title = (it or {}).get('name') or ''
        artist = ''
        dash = title.find(' - ')
        if dash >= 0:
            artist, title = title[:dash], title[dash + 3:]
        if not artist and isinstance(it.get('singerinfo'), list):
            artist = ' / '.join(s.get('name') for s in it['singerinfo'] if isinstance(s, dict) and s.get('name'))
        hash320 = ''
        for g in (it.get('relate_goods') or []):
            if isinstance(g, dict) and g.get('level') == 4:
                hash320 = g.get('hash') or ''
                break
        rid_hash = it.get('hash') or hash320
        if not rid_hash:
            return None
        return {'id': str(rid_hash), 'name': (title or '').strip(), 'singer': artist,
                'album': (it.get('albuminfo') or {}).get('name'),
                'duration_s': int((it.get('timelen') or 0) / 1000) or None,
                'cover': KugouAdapter._kg_cover(it.get('cover')
                                                or (it.get('trans_param') or {}).get('union_cover')),
                'source': 'kugou'}

    async def artist_info(self, artist_id: str) -> dict:
        data = await self.run(self._api_get, '/artist/detail', {'id': artist_id})
        ar = (data or {}).get('data') or {}
        description = ''
        if isinstance(ar.get('long_intro'), list) and ar['long_intro']:
            description = (ar['long_intro'][0] or {}).get('content') or ''
        return {'artist': {'id': str(ar.get('author_id') or artist_id),
                           'name': ar.get('author_name') or '',
                           'avatar': self._kg_cover(ar.get('sizable_avatar')),
                           'description': description or None,
                           'album_count': self._kg_int(ar.get('album_count')) or 0,
                           # 现网字段是 song_count（audio_count 旧形兼容）
                           'music_count': self._kg_int(ar.get('song_count') or ar.get('audio_count')) or 0,
                           'source': 'kugou'}}

    async def artist_works(self, artist_id: str, work_type: str = 'music',
                           page: int = 1, limit: int = 30) -> dict:
        if work_type == 'music':
            data = await self.run(self._api_get, '/artist/audios',
                                  {'id': artist_id, 'page': page, 'pagesize': limit})
            rows = (data or {}).get('data') or []
            total = self._kg_int((data or {}).get('total')) or len(rows)
            items = []
            for r in rows:
                # audios 行 id 取 hash_128||hash——kwqq-api /kugou/song/url 以 FileHash 取链
                rid = r.get('hash_128') or r.get('hash')
                if not rid:
                    continue
                duration = r.get('timelength_128') or r.get('timelength')
                items.append({'id': str(rid), 'name': r.get('audio_name') or '',
                              'singer': r.get('author_name') or '', 'album': r.get('album_name'),
                              'duration_s': int(float(duration) / 1000) if duration else None,
                              'cover': (r.get('trans_param') or {}).get('union_cover'),
                              'source': 'kugou'})
            return {'type': work_type, 'page': page, 'is_end': page * limit >= total,
                    'total': total, 'items': items}
        data = await self.run(self._api_get, '/artist/albums',
                              {'id': artist_id, 'page': page, 'pagesize': limit})
        rows = (data or {}).get('data') or []
        total = self._kg_int((data or {}).get('total')) or len(rows)
        items = [{'id': str(r['album_id']), 'name': r.get('album_name') or '',
                  'artist': r.get('author_name') or '',
                  'cover': self._kg_cover(r.get('sizable_cover')),
                  'extra': {'description': r.get('intro')}, 'source': 'kugou'}
                 for r in rows if r.get('album_id')]
        return {'type': work_type, 'page': page, 'is_end': page * limit >= total,
                'total': total, 'items': items}

    async def music_comments(self, song_id: str = None, title: str = '', artist: str = '',
                             page: int = 1, limit: int = 20) -> dict:
        # kugou 评论按 mixsongid（数字 id）取——hash 口径的调用方须先经 song_info 换 id；
        # kwqq 插件消费时从已入库歌曲的 dedup_key 取 mixsongid 传入
        if not song_id:
            raise AdapterError(400, 'kugou comments require numeric mixsongid')
        data = await self.run(self._api_get, '/comment/music',
                              {'mixsongid': song_id, 'page': page, 'pagesize': limit, 'folder': 0})
        if (data or {}).get('status') != 1:
            return {'id': str(song_id), 'page': page, 'total': 0, 'has_more': False, 'hot': [], 'items': []}

        def _comment(c):
            if not c:
                return None
            return {'id': str(c.get('id') or ''), 'nick_name': c.get('user_name') or '匿名用户',
                    'avatar': c.get('avatar'), 'content': c.get('content') or '',
                    'like': c.get('like') if isinstance(c.get('like'), int) else self._kg_int(c.get('like')),
                    'created_at': self._kg_int(c.get('addtime')), 'replies': []}

        lst = [c for c in (_comment(x) for x in (data or {}).get('list') or []) if c]
        total = self._kg_int((data or {}).get('total'))
        return {'id': str(song_id), 'page': page, 'total': total,
                'has_more': bool(total) and page * limit < total,
                'hot': [], 'items': lst}

    '''P9b（2026-11-04）：专辑 by-id 详情（曲目官方曲序 + album_info 元数据）。'''
    async def album_detail(self, album_id: str) -> dict:
        detail = await self.run(self._api_get, '/album/songs', {'id': album_id})
        songs = ((detail.get('data') or {}).get('songs')) or []
        alb = (songs[0].get('album_info') or {}) if songs else {}
        albums = [{'id': str(album_id), 'name': alb.get('album_name'),
                   'artist': None, 'size': len(songs),
                   'cover': (alb.get('cover') or '').replace('{size}', '400') or None,
                   'source': self.source_key, 'extra': {}}] if songs else []

        def _official_order(pair):
            ext = pair[1].get('extend') or {}
            return (int(ext.get('disc') or 1), int(ext.get('sort') or 0), pair[0])
        items = []
        for i, (_, s) in enumerate(sorted(enumerate(songs), key=_official_order), 1):
            base, info, alb2 = s.get('base') or {}, s.get('audio_info') or {}, s.get('album_info') or {}
            if not info.get('hash'):
                continue
            cover = (alb2.get('cover') or '').replace('{size}', '400') or None
            items.append({'id': str(info['hash']), 'name': base.get('audio_name'),
                          'singer': base.get('author_name'), 'album': alb2.get('album_name'),
                          'ext': None, 'size_bytes': None,
                          'duration_s': int(float(info.get('duration') or 0)) or None,
                          'cover': cover, 'source': self.source_key, 'track_no': i})
        return {'albums': albums, 'items': items}

    '''P9c（2026-11-04）：导入协议。单曲 = 数字 MixSongID（album_audio_id）→
       /audio/related 取 original；歌单 = global_collection_id 或数字 specialid
       （先经 /playlist/detail?ids= 换 gid），/playlist/track/all 300/页自动翻页。'''
    @staticmethod
    def _import_song_id(url_like: str):
        import re
        s = str(url_like or '').strip()
        return s if re.fullmatch(r'\d+', s) else None

    @staticmethod
    def _related_to_item(orig):
        base = (orig or {}).get('base') or {}
        info = (orig or {}).get('audio_info') or {}
        if not base:
            return None
        return {'id': str(base.get('album_audio_id') or ''), 'name': base.get('audio_name'),
                'singer': base.get('author_name'), 'album': base.get('album_name'),
                'duration_s': int(float(info.get('timelength') or 0)) // 1000 or None,
                'source': 'kugou'}

    async def import_item(self, url_like: str) -> dict:
        sid = self._import_song_id(url_like)
        if not sid:
            raise AdapterError(400, 'cannot extract MixSongID (numeric) from urlLike')
        data = await self.run(self._api_get, '/audio/related', {'album_audio_id': sid})
        if (data or {}).get('status') == 1:
            orig = ((data or {}).get('extra') or {}).get('original') or [None]
            item = self._related_to_item(orig[0])
            if item:
                return {'item': item}
        # related 失败给最小占位（musicfree 同款语义：返回 id 占位行）
        return {'item': {'id': sid, 'name': f'ID:{sid}', 'singer': '未知艺人',
                         'album': None, 'duration_s': None, 'source': 'kugou'}}

    async def import_sheet(self, url_like: str, cap: int = 1000) -> dict:
        pid = str(url_like or '').strip()
        if not pid:
            raise AdapterError(400, 'playlist id required')
        # 纯数字 specialid → /playlist/detail?ids= 换 global_collection_id
        import re
        if re.fullmatch(r'\d+', pid):
            # specialid → gid 换算依赖 /playlist/detail（现网实测稳定返回空 data，
            # 疑似需登录态）——失败即报 404 引导用户输入 collection_… 形态
            try:
                dr = await self.run(self._api_get, '/playlist/detail', {'ids': pid})
                info = ((dr or {}).get('data') or [{}])[0]
                if isinstance(info, dict) and info.get('global_collection_id'):
                    pid = info['global_collection_id']
                else:
                    raise AdapterError(404, 'playlist not found: /playlist/detail returned no gid; use global_collection_id (collection_...)')
            except AdapterError:
                raise
            except Exception as e:
                raise AdapterError(404, f'playlist lookup failed: {e}')
        items, page, pagesize, truncated = [], 1, 300, False
        while len(items) < cap:
            data = await self.run(self._api_get, '/playlist/track/all',
                                  {'id': pid, 'page': page, 'pagesize': pagesize})
            d = (data or {}).get('data') or {}
            songs = d.get('songs') or []
            if not songs:
                break
            for m in songs:
                if len(items) >= cap:
                    truncated = True
                    break
                conv = self._playlist_song(m)
                if conv:
                    items.append(conv)
            total = self._kg_int(d.get('count')) or 0
            if len(items) >= total or len(songs) < pagesize or truncated:
                break
            page += 1
        return {'items': items, 'total': len(items), 'truncated': truncated}
