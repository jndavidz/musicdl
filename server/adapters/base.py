'''
Function:
    SourceAdapter base: wraps a musicdl source client for API usage.
Notes on the execution boundary (K-03):
    - sync work runs on a per-source ThreadPoolExecutor whose worker count IS the
      capacity. A caller timeout returns control to the caller, but the pool slot
      stays occupied until the worker thread really exits (Python cannot kill a
      running thread, so we stop pretending the timeout freed it).
    - waiting requests are a bounded, statically partitioned second bucket
      (MAX_WAITERS per source); an over-full queue answers 503 capacity instead of
      growing without bound.
    - results that finish after their caller gave up are dropped, never delivered
      and never written to a cache.
'''
import re
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from musicdl.modules.sources.base import BaseMusicClient
from musicdl.modules.utils import AudioLinkTester
from server.parsers_health import is_rate_limited, retry_after_from


class AdapterError(Exception):
    def __init__(self, code: int, msg: str, retry_after: int = None):
        super().__init__(msg)
        self.code, self.msg, self.retry_after = code, msg, retry_after


'''词曲编曲统一契约：{lyricist: [], composer: [], arranger: []}（不写 null）。
   现网实测（2026-11）：六源都没有独立的 credits 接口（netease /api/song/credit、
   容器 /song/credit 均 404；QQ track_info、酷狗 /audio/related、酷我 songinfo 都无署名），
   但歌词正文头部普遍带署名行（`作词：周杰伦` / `词 : 唐恬` / `编曲：...`），
   甚至一行内写多个位（`作词：李瑞洵 作曲：林俊杰`）——故统一从歌词头解析。
   歌词里没有署名行的曲目返回全空 → routes 层把 credits 键整个缺省。'''
_CREDIT_TS_PREFIX = re.compile(r'^\s*(?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]\s*)+')
_CREDIT_MARK = re.compile(r'(作词|作曲|编曲|词|曲)\s*[：:]')
_CREDIT_STOP = re.compile(
    r'[ \t]*(?:演唱|制作人|监制|出品|发行|录音|混音|母带|和声|配唱|'
    r'吉他|贝斯|鼓手|键盘|弦乐|作词|作曲|编曲|词|曲)\s*[：:]')
_CREDIT_FIELDS = {'作词': 'lyricist', '词': 'lyricist',
                  '作曲': 'composer', '曲': 'composer', '编曲': 'arranger'}
_CREDIT_SPLIT = re.compile(r'[、,，/;；|｜]+')
_CREDIT_PLACEHOLDERS = {'佚名', '未知', '不详', '无', '暂无', '-', '—', 'n/a', 'none'}


def parse_credits(lyric: str, head_lines: int = 25) -> dict:
    '''从歌词头部的署名行解析词/曲/编曲；只看前 head_lines 个非空行，避免把
       正文里偶然出现的「词：」当成署名。支持一行内多个位（`作词：A 作曲：B`）、
       多值切分、去重、去空白、剔除「佚名/未知」类占位。'''
    out = {'lyricist': [], 'composer': [], 'arranger': []}
    if not lyric:
        return out
    seen = 0
    for raw in str(lyric).splitlines():
        line = raw.strip()
        if not line:
            continue
        seen += 1
        if seen > head_lines:
            break
        line = _CREDIT_TS_PREFIX.sub('', line).strip()
        marks = list(_CREDIT_MARK.finditer(line))
        if not marks:
            continue
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
            stop = _CREDIT_STOP.search(line, m.end(), end)
            value = line[m.end():stop.start() if stop else end].strip()
            field = _CREDIT_FIELDS[m.group(1)]
            for name in _CREDIT_SPLIT.split(value):
                name = name.strip().strip('"“”\'')
                if not name or name.lower() in _CREDIT_PLACEHOLDERS:
                    continue
                if len(name) > 40:
                    continue
                if name not in out[field]:
                    out[field].append(name)
    return out


class _Job:
    '''one measured execution: fn + the flags that mark an abandoned caller'''
    __slots__ = ('fn', 'args', 'kwargs', 'loop', 'started', 'abandoned')

    def __init__(self, fn, args, kwargs, loop):
        self.fn, self.args, self.kwargs, self.loop = fn, args, kwargs, loop
        self.started = False
        self.abandoned = False


class SourceAdapter:
    source_key = 'base'
    '''album 通道是否返回整册曲目（count 可信）。True 的源门面给出 track_count；
    migu/qianqian 上游无整册计数，产品决定不显示（选项 A：不为补数字逐专辑查详情）→ False。'''
    album_track_count = False
    '''subclass builds the musicdl client (no cookies! third-party chain relies on that)'''
    def _build_client(self) -> BaseMusicClient:
        raise NotImplementedError

    def __init__(self, settings, health):
        self.settings = settings
        self.health = health
        self.max_workers = max(1, int(settings.max_concurrency_per_source))
        self.max_waiters = max(1, int(getattr(settings, 'max_waiters_per_source', self.max_workers * 2)))
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers,
                                        thread_name_prefix=f'kwqq-{self.source_key}')
        self._capacity = asyncio.Semaphore(self.max_workers)
        self._waiting = 0     # admitted callers queued for a worker slot
        self._active = 0      # worker slots held (runs until the thread really exits)
        self._timed_out = 0
        self._late_dropped = 0
        self._stats_lock = threading.Lock()
        self.client = health.wrap_client(self._build_client())

    '''account cookie value for passthrough injection; default: anonymous (no cookie)'''
    def account_cookie(self) -> str:
        return ''

    '''(connect, read) budget for every bare sync upstream call made by an adapter'''
    @property
    def io_timeout(self):
        try:
            budget = float(getattr(self.settings, 'io_timeout_s', 20))
        except (TypeError, ValueError):
            budget = 20.0
        return (3.0, max(3.0, min(budget, float(self.settings.hard_timeout_s))))

    '''run a sync callable in a worker thread under the source capacity + hard timeout'''
    async def run(self, fn, *args, **kwargs):
        return await self.run_with_timeout(fn, self.settings.hard_timeout_s, *args, **kwargs)

    '''one logical upstream entry point (primary host, container, relay/mirror).
       `name` is host-agnostic by contract: every alias of the same logical parser
       shares it, so a 429 cooldown cannot be reset by switching hosts.'''
    async def run_guarded(self, name, fn, *args, **kwargs):
        remaining = self.health.cooldown_remaining(name)
        if remaining > 0:
            raise AdapterError(429, f'{self.source_key}: {name} is cooling down after an upstream '
                                    f'rate limit ({int(round(remaining))}s left)',
                               retry_after=int(round(remaining)) or 1)
        try:
            return await self.run(fn, *args, **kwargs)
        except Exception as err:
            if is_rate_limited(err):
                wait = self.health.record_throttle(name, retry_after_from(err), err)
                raise AdapterError(429, f'{self.source_key}: upstream rate limited ({name})',
                                   retry_after=int(round(wait)) or 1)
            raise

    '''sync-side counterpart of run_guarded, for helpers already inside a worker thread'''
    def guarded_sync(self, name, fn, *args, **kwargs):
        remaining = self.health.cooldown_remaining(name)
        if remaining > 0:
            raise AdapterError(429, f'{self.source_key}: {name} is cooling down after an upstream '
                                    f'rate limit ({int(round(remaining))}s left)',
                               retry_after=int(round(remaining)) or 1)
        try:
            return fn(*args, **kwargs)
        except Exception as err:
            if is_rate_limited(err):
                wait = self.health.record_throttle(name, retry_after_from(err), err)
                raise AdapterError(429, f'{self.source_key}: upstream rate limited ({name})',
                                   retry_after=int(round(wait)) or 1)
            raise

    '''same as run() with an explicit timeout (slow resolvers like deezer override this)'''
    async def run_with_timeout(self, fn, timeout, *args, **kwargs):
        self._admit_waiter()
        promoted = False
        try:
            try:
                await asyncio.wait_for(self._capacity.acquire(), timeout=timeout)
            except asyncio.TimeoutError:
                raise AdapterError(504, f'{self.source_key}: timed out waiting for a worker slot '
                                        f'({self.max_workers} busy)')
            with self._stats_lock:
                self._waiting -= 1
                self._active += 1
            promoted = True
            loop = asyncio.get_running_loop()
            job = _Job(fn, args, kwargs, loop)
            try:
                cf = self._pool.submit(self._execute, job)
            except RuntimeError:      # pool shut down (lifespan exit)
                with self._stats_lock:
                    self._active -= 1
                self._capacity.release()
                raise AdapterError(503, f'{self.source_key}: worker pool is shutting down')
            cf.add_done_callback(self._on_done(job))
            try:
                return await asyncio.wait_for(asyncio.wrap_future(cf), timeout=timeout)
            except asyncio.TimeoutError:
                job.abandoned = True
                with self._stats_lock:
                    self._timed_out += 1
                raise
        finally:
            if not promoted:
                self._waiting -= 1

    '''worker-thread body; capacity release happens in the done-callback below so a
       future cancelled BEFORE the worker starts cannot leak a slot'''
    def _execute(self, job: _Job):
        job.started = True
        return job.fn(*job.args, **job.kwargs)

    def _on_done(self, job: _Job):
        def _release(fut):
            with self._stats_lock:
                self._active -= 1
                if job.started and job.abandoned:
                    self._late_dropped += 1
            try:
                job.loop.call_soon_threadsafe(self._capacity.release)
            except RuntimeError:
                pass   # loop already closed during shutdown
        return _release

    def _admit_waiter(self):
        # event-loop-thread-only counter: admission check is await-free by design
        if self._waiting >= self.max_waiters:
            raise AdapterError(503, f'{self.source_key}: capacity exhausted '
                                    f'({self.max_workers} busy, {self._waiting} waiting)')
        self._waiting += 1

    '''live counters for /status and cross-project capacity acceptance'''
    def runtime_stats(self) -> dict:
        with self._stats_lock:
            return {'active': self._active, 'waiting': self._waiting,
                    'max_workers': self.max_workers, 'max_waiters': self.max_waiters,
                    'timed_out': self._timed_out, 'late_dropped': self._late_dropped}

    def shutdown(self):
        self._pool.shutdown(wait=False)

    '''SongInfo -> search item dict'''
    @staticmethod
    def item_from_songinfo(info) -> dict:
        return {
            'id': str(info.identifier) if info.identifier else '',
            'name': info.song_name, 'singer': info.singers, 'album': info.album,
            'ext': info.ext, 'size_bytes': info.file_size_bytes,
            'duration_s': info.duration_s, 'cover': info.cover_url,
            'source': info.source,
        }

    '''lightweight metadata-only search (single upstream request, no parse chain).
       API search must NOT go through client.search(): that resolves download links
       for every candidate (seconds each). Plugins only need meta here.'''
    async def search_items(self, keywords: str, limit: int, page: int = 1) -> list[dict]:
        raw_items = await self.run(self._search_raw, keywords, limit, page)
        return [self.item_from_raw(raw) for raw in raw_items if self.item_from_raw(raw).get('id')]

    '''platform-specific: fetch raw search rows + convert row -> item dict'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        raise NotImplementedError

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        raise NotImplementedError

    '''歌词契约：{'lyric': str, 'lxlyric': str|None}。
       lxlyric = 逐字歌词，洛雪格式——行前缀 [mm:ss.mmm]，逐字 <偏移ms,时长ms>文本，
       偏移相对行首；客户端按此格式解析（字段名固定，不得改名）。
       默认无逐字能力；有逐字通道的源（目前 kugou）覆写本方法。'''
    async def lyric_data(self, song_id: str, **kwargs) -> dict:
        return {'lyric': await self.lyric(song_id, **kwargs) or '', 'lxlyric': None}

    '''词曲编曲（2026-11）：契约 {lyricist: [], composer: [], arranger: []}，来源是歌词头部署名行
       （各源歌词里都有，无需额外接口）。无歌词能力或歌词里没有署名行的源返回全空 →
       routes 层把 credits 键整个缺省，前端据此隐藏该区块。'''
    async def credits(self, song_id: str, **kwargs) -> dict:
        try:
            return parse_credits(await self.lyric(song_id, **kwargs) or '')
        except Exception:
            return parse_credits('')

    '''MV 契约：{id, source, url, cover, duration_s, quality}，顶层永远是首个可直接播放的 MV。
       默认无 MV 能力 → url=None（契约要求业务未命中走 url:null，而不是 404/501）。
       有 MV 通道的源（netease/qq/kugou）覆写本方法。'''
    async def mv(self, song_id: str, title: str = '', artist: str = '') -> dict:
        return {'id': str(song_id), 'source': self.source_key, 'url': None,
                'cover': None, 'duration_s': None, 'quality': None}

    '''MV 清晰度归一：各源档位命名/高度口径不同，统一落到 ld/sd/hd/fhd 简单枚举。
       height 可以是像素高度（qq vh / kugou *_height）或纵向清晰度标记（netease br）。'''
    @staticmethod
    def mv_quality(height) -> str:
        try:
            h = int(float(height))
        except (TypeError, ValueError):
            return 'hd'
        if h <= 300:
            return 'ld'
        if h <= 480:
            return 'sd'
        if h <= 720:
            return 'hd'
        return 'fhd'

    '''MV 搜索契约（`/{source}/search?type=mv`）：{'items': [MvItem], 'total': int}。
       item 与 mv() 同构，url 恒为 None（点击后再按 id 现取）；id 必须是该源 mv() 能直接吃的 id。
       默认不支持——routes 层转 501 envelope；有 MV 通道的源（netease/qq/kugou/kuwo）覆写。'''
    async def search_mv(self, keywords: str, page: int = 1, limit: int = 20) -> dict:
        raise AdapterError(501, f'MV search not supported for source "{self.source_key}"')

    '''P6 专辑检索：专辑名 → {'albums': [候选], 'items': [首选专辑有序曲目]}。
       items 与 search_items 同构（附加 track_no，1 起）；曲目解析仍走 /song/url by-id（二段式不变）。
       默认不支持——routes 层转 501 envelope；支持源在各自 adapter 覆写。'''
    async def album(self, name: str, artist: str = '', page: int = 1) -> dict:
        raise AdapterError(501, f'album search not supported for source "{self.source_key}"')

    '''候选排序（专辑/歌单共用）：名字精确匹配优先，其次歌手/创建者提示命中。
       配合各 adapter 的「name+artist 无结果再退 name」检索，抵消平台分词差异造成的漏召回。'''
    @staticmethod
    def rank_candidates(entries: list, name: str, artist: str = '') -> list:
        nk = (name or '').strip().lower()
        ak = (artist or '').lower()
        entries.sort(key=lambda e: ((e.get('name') or '').strip().lower() == nk,
                                    bool(ak) and ak in (e.get('artist') or '').lower()),
                     reverse=True)
        return entries

    '''P6 歌单检索：歌单名 → {'playlists': [候选], 'items': [首选歌单有序曲目]}。
       默认不支持——routes 层转 501 envelope；支持源覆写。'''
    async def playlist(self, name: str, page: int = 1) -> dict:
        raise AdapterError(501, f'playlist search not supported for source "{self.source_key}"')

    '''v2 identity: identity-affecting extra fields -> song_url kwargs.
       Sources whose by-id resolve needs extra identity (migu copyrightId,
       bilibili cid/page) override this; everything else takes no extra args.'''
    def identity_kwargs(self, extra: dict) -> dict:
        return {}

    '''v2 identity: echo/complete the TrackRef extra after resolving. Adapters that
       verify or derive identity fields (bilibili resolves cid from page) override;
       base echoes the requested identity unchanged.'''
    def identity_out(self, requested: dict, result: dict) -> dict:
        return dict(requested or {})

    '''SongInfo / direct-dict -> song url dict'''
    def urldata_from_songinfo(self, song_id: str, quality: str, info, elapsed_ms: int, cached: bool = False, platform_tag: str | None = None) -> dict:
        return {
            'id': str(song_id), 'source': self.source_key, 'quality': quality,
            'url': info.download_url, 'ext': self.clean_ext(info.ext), 'size_bytes': info.file_size_bytes,
            'bitrate_kbps': getattr(info, 'bitrate', None), 'duration_s': info.duration_s,
            'cover': info.cover_url, 'verified': True, 'headers': {},
            'parser': (info.raw_data or {}).get('spike_parser'), 'elapsed_ms': elapsed_ms, 'cached': cached,
            'platform_tag': platform_tag,
        }

    @staticmethod
    def clean_ext(ext):
        '''AudioLinkTester answers "NULL" when it cannot infer a codec; that sentinel is
           not an extension and must not reach a response or an admission check'''
        cleaned = str(ext or '').strip().lower().lstrip('.')
        return None if cleaned in {'', 'null', 'none'} else cleaned

    '''direct/relay result -> song url dict: the single assembly point for the
       14-field response shape (replaces the per-adapter hand-built dicts)'''
    def url_data(self, song_id: str, quality: str, *, url: str, ext: str = 'mp3', size_bytes=None,
                 bitrate_kbps=None, duration_s=None, cover=None, verified: bool = True,
                 headers: dict | None = None, parser: str = '', platform_tag: str | None = None,
                 ekey: str | None = None, elapsed_ms: int = 0, cached: bool = False) -> dict:
        return {
            'id': str(song_id), 'source': self.source_key, 'quality': quality,
            'url': url, 'ext': self.clean_ext(ext), 'size_bytes': size_bytes, 'bitrate_kbps': bitrate_kbps,
            'duration_s': duration_s, 'cover': cover, 'verified': verified,
            'headers': headers or {}, 'parser': parser, 'platform_tag': platform_tag,
            'ekey': ekey, 'elapsed_ms': elapsed_ms, 'cached': cached,
        }

    '''P7 多类型搜索：type ∈ album|artist|sheet → {'items': [type 特定条目], 'total': int|None}。
       条目形状（MusicFree 语义归一，全部带 source）：
         album  {id, name, artist, cover, track_count}
         artist {id, name, avatar}
         sheet  {id, name, creator, cover, track_count, play_count}
       默认不支持——routes 层转 501 envelope；支持源在各自 adapter 覆写。'''
    '''P8 在线浏览：榜单 / 推荐歌单（2026-11-04，kuwo 首发）。
       五个能力按 MusicFree 语义归一；默认不支持——routes 层转 501 envelope；
       支持源在各自 adapter 覆写。曲目解析仍走 /song/url by-id（二段式不变）。'''
    async def toplists(self) -> dict:
        raise AdapterError(501, f'toplists not supported for source "{self.source_key}"')

    async def toplist_songs(self, toplist_id: str, page: int = 1, limit: int = 50) -> dict:
        raise AdapterError(501, f'toplist songs not supported for source "{self.source_key}"')

    async def playlist_tags(self) -> dict:
        raise AdapterError(501, f'playlist tags not supported for source "{self.source_key}"')

    async def playlist_sheets(self, tag: str, page: int = 1, limit: int = 30) -> dict:
        raise AdapterError(501, f'playlist recommend not supported for source "{self.source_key}"')

    async def playlist_songs(self, playlist_id: str, page: int = 1, limit: int = 50) -> dict:
        raise AdapterError(501, f'playlist songs not supported for source "{self.source_key}"')

    async def artist_info(self, artist_id: str) -> dict:
        raise AdapterError(501, f'artist info not supported for source "{self.source_key}"')

    async def artist_works(self, artist_id: str, work_type: str = 'music',
                           page: int = 1, limit: int = 30) -> dict:
        raise AdapterError(501, f'artist works not supported for source "{self.source_key}"')

    async def music_comments(self, song_id: str = None, title: str = '', artist: str = '',
                             page: int = 1, limit: int = 20) -> dict:
        raise AdapterError(501, f'comments not supported for source "{self.source_key}"')

    async def search_multi(self, keywords: str, search_type: str, page: int = 1, limit: int = 20) -> dict:
        raise AdapterError(501, f'type search "{search_type}" not supported for source "{self.source_key}"')

    '''P9c 导入协议（2026-11-04）：urlLike → 单曲 / 歌单全量曲目（MusicFree
       importMusicItem / importMusicSheet 语义）。默认不支持——routes 层转 501。'''
    async def import_item(self, url_like: str) -> dict:
        raise AdapterError(501, f'import item not supported for source "{self.source_key}"')

    async def import_sheet(self, url_like: str, cap: int = 1000) -> dict:
        raise AdapterError(501, f'import sheet not supported for source "{self.source_key}"')
