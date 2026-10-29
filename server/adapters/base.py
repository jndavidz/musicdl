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


class _Job:
    '''one measured execution: fn + the flags that mark an abandoned caller'''
    __slots__ = ('fn', 'args', 'kwargs', 'loop', 'started', 'abandoned')

    def __init__(self, fn, args, kwargs, loop):
        self.fn, self.args, self.kwargs, self.loop = fn, args, kwargs, loop
        self.started = False
        self.abandoned = False


class SourceAdapter:
    source_key = 'base'
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
