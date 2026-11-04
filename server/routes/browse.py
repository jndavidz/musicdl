'''
Function:
    Browse endpoints (P8/P9) — online-browse resource domain: toplists / playlist recommend / artist / comments.
    MusicFree 语义归一；曲目解析仍走 /song/url by-id（二段式不变）。
    默认 501 由 adapters/base 的缺省实现给出（source 不支持该能力）。
'''
import asyncio

from fastapi import Query, Request

from server.cache import cached
from server.envelope import ok
from server.routes.resolve import get_adapter
from server.schemas import (ImportItemData, ImportSheetData,
                            ToplistsData, PlaylistTagsData, SheetListData,
                            SheetSongsData, ToplistEntry, TagEntry, TagGroup, PlaylistEntry,
                            ArtistData, ArtistWorksData, CommentsData, ArtistEntry, CommentEntry)


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


async def artist_info(request: Request, source: str, id: str = Query(..., min_length=1)):
    '''P9 歌手详情（头像/别名/简介/作品数）。'''
    s = request.app.state
    adapter = get_adapter(s, source)
    result, _ = await cached(s.meta_cache, (source, 'artist', id),
                             lambda: adapter.artist_info(id))
    data = ArtistData(source=source, artist=ArtistEntry(**(result.get('artist') or {})))
    return ok(data.model_dump())


async def artist_works(request: Request, source: str, id: str = Query(..., min_length=1),
                       type: str = Query('music', pattern='^(music|album)$'),
                       page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    '''P9 歌手作品：type=music → SearchItem 形状曲目；type=album → AlbumEntry 形状专辑。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    limit = min(limit or 30, 50)
    result, _ = await cached(s.meta_cache, (source, 'aworks', id, type, page, limit),
                             lambda: asyncio.wait_for(adapter.artist_works(id, type, page, limit),
                                                      timeout=st.hard_timeout_s))
    data = ArtistWorksData(source=source, id=id, type=result.get('type', type),
                           page=result.get('page', page), is_end=result.get('is_end', True),
                           total=result.get('total'), items=result.get('items') or [])
    return ok(data.model_dump())


async def music_comments(request: Request, source: str,
                         id: str = Query('', min_length=0),
                         title: str = Query(''), artist: str = Query(''),
                         page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    '''P9 歌曲评论（netease 支持 id 或 title+artist 回搜；kugou 需数字 mixsongid）。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    if not id and not title:
        from server.adapters import AdapterError
        raise AdapterError(400, 'id or title required')
    limit = min(limit or 20, 50)
    result, _ = await cached(s.meta_cache, (source, 'comments', id, title, artist, page, limit),
                             lambda: asyncio.wait_for(
                                 adapter.music_comments(song_id=id or None, title=title,
                                                        artist=artist, page=page, limit=limit),
                                 timeout=st.hard_timeout_s))
    data = CommentsData(source=source, id=result.get('id') or id,
                        page=result.get('page', page), total=result.get('total'),
                        has_more=result.get('has_more', False),
                        hot=[CommentEntry(**c) for c in result.get('hot') or []],
                        items=[CommentEntry(**c) for c in result.get('items') or []])
    return ok(data.model_dump())

async def album_detail(request: Request, source: str, id: str = Query(..., min_length=1)):
    '''P9b 专辑 by-id 详情（albums 单条 + 官方曲序曲目 track_no）；base 缺省 501。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    result, _ = await cached(s.meta_cache, (source, 'adetail', id),
                             lambda: asyncio.wait_for(adapter.album_detail(id),
                                                      timeout=st.hard_timeout_s))
    from server.schemas import AlbumEntry, AlbumData
    data = AlbumData(source=source, id=id,
                     albums=[AlbumEntry(**a) for a in result.get('albums') or []],
                     items=result.get('items') or [],
                     total=len(result.get('items') or []))
    return ok(data.model_dump())


async def import_item(request: Request, source: str, url: str = Query(..., min_length=1)):
    '''P9c 导入单曲（urlLike → SearchItem；MusicFree importMusicItem 语义）。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    result, _ = await cached(s.meta_cache, (source, 'impitem', url),
                             lambda: asyncio.wait_for(adapter.import_item(url),
                                                      timeout=st.hard_timeout_s))
    from server.schemas import SearchItem
    item = result.get('item')
    data = ImportItemData(source=source, url=url,
                          item=SearchItem(**item) if item else None)
    return ok(data.model_dump())


async def import_sheet(request: Request, source: str, url: str = Query(..., min_length=1),
                       cap: int = Query(1000, ge=1, le=2000)):
    '''P9c 导入歌单（urlLike → 全量曲目；cap 截断保护，truncated 标记）。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    result, _ = await cached(s.meta_cache, (source, 'impsheet', url, cap),
                             lambda: asyncio.wait_for(adapter.import_sheet(url, cap),
                                                      timeout=st.hard_timeout_s * 3))
    data = ImportSheetData(source=source, url=url, total=result.get('total', 0),
                           truncated=result.get('truncated', False),
                           items=result.get('items') or [])
    return ok(data.model_dump())
