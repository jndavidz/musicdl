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
