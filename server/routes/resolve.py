'''
Function:
    Resolve endpoints — the "解析" resource domain: search / song_url / song_info / lyric.
    Two-stage contract: search issues a single metadata request (adapter.search_items);
    direct-link resolution happens only on /song/url by id.
'''
import asyncio
from fastapi import Query, Request

from server.adapters import AdapterError
from server.cache import cached
from server.envelope import ok
from server.quality import resolve as resolve_quality
from server.schemas import SearchData, SongUrlData, SongInfoData, LyricData
from server.config import SOURCES


def get_adapter(state, source: str):
    if source not in SOURCES:
        raise AdapterError(404, f'unknown source "{source}" (available: {", ".join(SOURCES)})')
    adapter = state.adapters.get(source)
    if adapter is None:
        raise AdapterError(404, f'source "{source}" is not enabled on this server')
    return adapter


async def search(request: Request, source: str, keywords: str = Query(..., min_length=1),
                 page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    limit = min(limit or st.search_size_default, st.search_size_max)
    items, _ = await cached(s.search_cache, (source, keywords, page, limit),
                            lambda: adapter.search_items(keywords, limit, page))
    data = SearchData(keywords=keywords, page=page, total=len(items), items=items[:limit])
    return ok(data.model_dump())


async def song_url(request: Request, source: str, id: str = Query(..., min_length=1), quality: str = Query('auto'),
                   copyright: str = Query('', description='migu only: copyrightId from search item extra')):
    s = request.app.state
    adapter = get_adapter(s, source)
    q = resolve_quality(source, quality)
    result, hit = await cached(
        s.url_cache, (source, id, q, copyright),
        lambda: _resolve_song_url(adapter, id, q, copyright, s.settings.hard_timeout_s))
    if hit:
        result = {**result, 'cached': True}
    return ok(SongUrlData(**result).model_dump())


async def _resolve_song_url(adapter, song_id: str, q: str, copyright: str, hard_timeout_s: float) -> dict:
    kwargs = {'copyright_id': copyright} if adapter.source_key == 'migu' else {}
    # two timeout layers, distinct roles: adapter run_with_timeout = single upstream call
    # budget; this wait_for = whole fallback-chain budget (multi-route chains accumulate).
    route_timeout = getattr(adapter, 'timeout_override', 0) or hard_timeout_s
    return await asyncio.wait_for(adapter.song_url(song_id, q, **kwargs), timeout=route_timeout)


async def song_info(request: Request, source: str, id: str = Query(..., min_length=1),
                    copyright: str = Query('', description='migu only: copyrightId from search item extra')):
    s = request.app.state
    adapter = get_adapter(s, source)
    kwargs = {'copyright_id': copyright} if source == 'migu' else {}
    result, _ = await cached(s.meta_cache, (source, 'info', id),
                             lambda: asyncio.wait_for(adapter.song_info(id, **kwargs),
                                                      timeout=s.settings.hard_timeout_s))
    return ok(SongInfoData(**result).model_dump())


async def lyric(request: Request, source: str, id: str = Query(..., min_length=1)):
    s = request.app.state
    adapter = get_adapter(s, source)
    text, hit = await cached(s.lyric_cache, (source, 'lyric', id),
                             lambda: asyncio.wait_for(adapter.lyric(id), timeout=s.settings.hard_timeout_s))
    return ok(LyricData(id=id, source=source, lyric=text, cached=hit).model_dump())
