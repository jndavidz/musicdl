'''
Function:
    SourceAdapter base: wraps a musicdl source client for API usage.
'''
import time
import asyncio
from musicdl.modules.sources.base import BaseMusicClient
from musicdl.modules.utils import AudioLinkTester


class AdapterError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg); self.code, self.msg = code, msg


class SourceAdapter:
    source_key = 'base'
    '''subclass builds the musicdl client (no cookies! third-party chain relies on that)'''
    def _build_client(self) -> BaseMusicClient:
        raise NotImplementedError

    def __init__(self, settings, health):
        self.settings = settings
        self.health = health
        self.semaphore = asyncio.Semaphore(settings.max_concurrency_per_source)
        self.client = health.wrap_client(self._build_client())

    '''account cookie value for passthrough injection; default: anonymous (no cookie)'''
    def account_cookie(self) -> str:
        return ''

    '''run a sync callable in a worker thread under the source semaphore + hard timeout'''
    async def run(self, fn, *args, **kwargs):
        return await self.run_with_timeout(fn, self.settings.hard_timeout_s, *args, **kwargs)

    '''same as run() with an explicit timeout (slow resolvers like deezer override this)'''
    async def run_with_timeout(self, fn, timeout, *args, **kwargs):
        async with self.semaphore:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)

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

    '''P6 专辑检索（roadmap）：专辑名 → {'albums': [候选], 'items': [首选专辑有序曲目]}。
       items 与 search_items 同构（附加 track_no，1 起）；曲目解析仍走 /song/url by-id（二段式不变）。
       默认不支持——routes 层转 501 envelope；支持源在各自 adapter 覆写。'''
    async def album(self, name: str, artist: str = '', page: int = 1) -> dict:
        raise AdapterError(501, f'album search not supported for source "{self.source_key}"')

    '''SongInfo / direct-dict -> song url dict'''
    def urldata_from_songinfo(self, song_id: str, quality: str, info, elapsed_ms: int, cached: bool = False, platform_tag: str | None = None) -> dict:
        return {
            'id': str(song_id), 'source': self.source_key, 'quality': quality,
            'url': info.download_url, 'ext': info.ext, 'size_bytes': info.file_size_bytes,
            'bitrate_kbps': getattr(info, 'bitrate', None), 'duration_s': info.duration_s,
            'cover': info.cover_url, 'verified': True, 'headers': {},
            'parser': (info.raw_data or {}).get('spike_parser'), 'elapsed_ms': elapsed_ms, 'cached': cached,
            'platform_tag': platform_tag,
        }

    '''direct/relay result -> song url dict: the single assembly point for the
       14-field response shape (replaces the per-adapter hand-built dicts)'''
    def url_data(self, song_id: str, quality: str, *, url: str, ext: str = 'mp3', size_bytes=None,
                 bitrate_kbps=None, duration_s=None, cover=None, verified: bool = True,
                 headers: dict | None = None, parser: str = '', platform_tag: str | None = None,
                 ekey: str | None = None, elapsed_ms: int = 0, cached: bool = False) -> dict:
        return {
            'id': str(song_id), 'source': self.source_key, 'quality': quality,
            'url': url, 'ext': ext, 'size_bytes': size_bytes, 'bitrate_kbps': bitrate_kbps,
            'duration_s': duration_s, 'cover': cover, 'verified': verified,
            'headers': headers or {}, 'parser': parser, 'platform_tag': platform_tag,
            'ekey': ekey, 'elapsed_ms': elapsed_ms, 'cached': cached,
        }
