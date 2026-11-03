'''
Function:
    Browse endpoints (P8) — online-browse resource domain: toplists / playlist recommend.
    MusicFree 语义归一；曲目解析仍走 /song/url by-id（二段式不变）。
    默认 501 由 adapters/base 的缺省实现给出（source 不支持该能力）。
'''
import asyncio

from fastapi import Query, Request

from server.cache import cached
from server.envelope import ok
from server.routes.resolve import get_adapter
from server.schemas import (ToplistsData, PlaylistTagsData, SheetListData,
                            SheetSongsData, ToplistEntry, TagEntry, TagGroup, PlaylistEntry)


async def toplists(request: Request, source: str):
    '''P8 榜单列表：平台全部榜单平铺（二级分组交给客户端）。'''
    s = request.app.state
    adapter = get_adapter(s, source)
    result, _ = await cached(s.meta_cache, (source, 'toplists'),
                             lambda: adapter.toplists())
    items = result.get('items') or []
    data = ToplistsData(source=source, items=[ToplistEntry(**i) for i in items])
    return ok(data.model_dump())


async def toplist_songs(request: Request, source: str, id: str = Query(..., min_length=1),
                        page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    '''P8 榜单内曲目（by id 分页）。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    limit = min(limit or 50, 100)
    result, _ = await cached(s.meta_cache, (source, 'tlist', id, page, limit),
                             lambda: asyncio.wait_for(adapter.toplist_songs(id, page, limit),
                                                      timeout=st.hard_timeout_s))
    data = SheetSongsData(source=source, id=id, page=result.get('page', page),
                          is_end=result.get('is_end', True), total=result.get('total'),
                          items=result.get('items') or [])
    return ok(data.model_dump())


async def playlist_tags(request: Request, source: str):
    '''P8 推荐歌单标签：pinned 热门 + groups 全量分类。'''
    s = request.app.state
    adapter = get_adapter(s, source)
    result, _ = await cached(s.meta_cache, (source, 'ptags'),
                             lambda: adapter.playlist_tags())
    data = PlaylistTagsData(
        source=source,
        pinned=[TagEntry(**t) for t in result.get('pinned') or []],
        groups=[TagGroup(**g) for g in result.get('groups') or []],
    )
    return ok(data.model_dump())


async def playlist_sheets(request: Request, source: str, tag: str = Query(''),
                          page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    '''P8 标签下推荐歌单（tag 空 = 全部热门；专区标签形如 "<id>@<digest>"，插件侧编码）。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    limit = min(limit or 30, 50)
    result, _ = await cached(s.meta_cache, (source, 'psheets', tag, page, limit),
                             lambda: asyncio.wait_for(adapter.playlist_sheets(tag, page, limit),
                                                      timeout=st.hard_timeout_s))
    data = SheetListData(source=source, tag=result.get('tag', tag),
                         page=result.get('page', page), is_end=result.get('is_end', True),
                         total=result.get('total'),
                         items=[PlaylistEntry(**i) for i in result.get('items') or []])
    return ok(data.model_dump())


async def playlist_songs(request: Request, source: str, id: str = Query(..., min_length=1),
                         page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    '''P8 歌单内曲目（by id 分页）；meta 仅 page=1 附歌单元数据。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    limit = min(limit or 50, 100)
    result, _ = await cached(s.meta_cache, (source, 'psongs', id, page, limit),
                             lambda: asyncio.wait_for(adapter.playlist_songs(id, page, limit),
                                                      timeout=st.hard_timeout_s))
    meta = result.get('meta')
    data = SheetSongsData(source=source, id=id, page=result.get('page', page),
                          is_end=result.get('is_end', True), total=result.get('total'),
                          items=result.get('items') or [],
                          meta=PlaylistEntry(**meta) if meta else None)
    return ok(data.model_dump())
