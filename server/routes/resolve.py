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
from server.schemas import (SearchData, SongUrlData, SongInfoData, LyricData, MvData, MvItem,
                            AlbumData, PlaylistData, SearchMultiData)
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
                   copyright: str = Query('', description='migu only: copyrightId from search item extra'),
                   cid: str = Query('', description='bilibili only: verified cid of the selected part'),
                   page: int = Query(0, ge=0, description='bilibili only: verified page number of the selected part')):
    s = request.app.state
    adapter = get_adapter(s, source)
    q = resolve_quality(source, quality)
    key = (source, id, q, copyright)
    identity = {}
    if source == 'bilibili' and (cid or page):
        # additive: part identity joins the v1 cache key so different P never share a URL
        identity = {'cid': cid or None, 'page': page or None}
        key = key + (cid, page)
    result, hit = await cached(
        s.url_cache, key,
        lambda: _resolve_song_url(adapter, id, q, copyright, s.settings.hard_timeout_s, identity))
    if hit:
        result = {**result, 'cached': True}
    return ok(SongUrlData(**result).model_dump())


async def _resolve_song_url(adapter, song_id: str, q: str, copyright: str, hard_timeout_s: float,
                            identity: dict = None) -> dict:
    kwargs = {'copyright_id': copyright} if adapter.source_key == 'migu' else {}
    kwargs.update(identity or {})
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


async def lyric(request: Request, source: str, id: str = Query(..., min_length=1),
                copyright: str = Query('', description='migu only: copyrightId from search item extra')):
    s = request.app.state
    adapter = get_adapter(s, source)
    kwargs = {'copyright_id': copyright} if source == 'migu' else {}
    # cache key carries a version tag: the value shape changed from str to {lyric, lxlyric},
    # so pre-deploy in-process entries must not be served to the new contract.
    result, hit = await cached(s.lyric_cache, (source, 'lyric2', id, copyright or ''),
                               lambda: asyncio.wait_for(adapter.lyric_data(id, **kwargs),
                                                        timeout=s.settings.hard_timeout_s))
    return ok(LyricData(id=id, source=source, lyric=result.get('lyric') or '',
                        lxlyric=result.get('lxlyric') or None, cached=hit).model_dump())


async def mv(request: Request, source: str, id: str = Query(..., min_length=1),
             title: str = Query('', description='optional hint: song title for sources whose id cannot map to an MV'),
             artist: str = Query('', description='optional hint: song artist for MV match disambiguation')):
    '''MV 契约（字段名固定，客户端按顶层字段直接消费）：
       data = {id, source, url, cover, duration_s, quality}；url=None 表示该源无 MV / 不可匿名访问 /
       本曲无匹配（HTTP 仍为 200 + code 200，业务未命中不做 404、不返回空对象）。
       可选 items 仅在源确有多个 MV 时出现，且**首个可直接播放的必是顶层字段**。
       MV URL 是签名短链（netease wsTime / QQ fvkey / kugou 日期路径，均短时效），
       这里**不接进程内缓存**：客户端每次点击都现取，避免把过期链接交给播放器。'''
    s = request.app.state
    adapter = get_adapter(s, source)
    result = await asyncio.wait_for(adapter.mv(str(id), title=title, artist=artist),
                                    timeout=s.settings.hard_timeout_s)
    raw_items = [it for it in (result.get('items') or []) if isinstance(it, dict)]
    playable = [it for it in raw_items if str(it.get('url') or '').startswith('http')]
    primary = playable[0] if playable else (raw_items[0] if raw_items else result)
    url = primary.get('url')
    if not (isinstance(url, str) and url.startswith('http')):
        url = None
    data = MvData(id=str(result.get('id') or id), source=source, url=url,
                  cover=primary.get('cover'), duration_s=primary.get('duration_s'),
                  quality=primary.get('quality'), title=primary.get('title'),
                  artist=primary.get('artist'), items=raw_items)
    return ok(data.model_dump())


async def search_multi(request: Request, source: str, keywords: str = Query(..., min_length=1),
                       type: str = Query('album', pattern='^(album|artist|sheet)$'),
                       page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    '''P7 多类型搜索：type ∈ album|artist|sheet → 类型特定条目（MusicFree 语义归一，带 source）。
       qq/kuwo/migu/qianqian 在各自 adapter 实现；netease/kugou 走透传（kwqq 插件直连容器）；
       其余源由 base.search_multi() 抛 501 envelope。'''
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    limit = min(limit or st.search_size_default, st.search_size_max)
    result, _ = await cached(s.meta_cache, (source, 'smulti', keywords, type, page, limit),
                             lambda: adapter.search_multi(keywords, type, page, limit))
    data = SearchMultiData(source=source, type=type, keywords=keywords, page=page,
                           total=result.get('total'), items=result.get('items') or [])
    return ok(data.model_dump())


async def album(request: Request, source: str, name: str = Query(..., min_length=1),

                artist: str = Query(''), page: int = Query(1, ge=1)):
    '''P6 专辑检索：专辑名 → 候选专辑 + 首选专辑的有序曲目（item 含 track_no）。
       单次调用覆盖语音点歌"整张连播"场景；未实现源由 base.album() 抛 501 envelope。'''
    s = request.app.state
    adapter = get_adapter(s, source)
    result, hit = await cached(
        s.meta_cache, (source, 'album', name, artist, page),
        lambda: asyncio.wait_for(adapter.album(name, artist, page),
                                 timeout=s.settings.hard_timeout_s))
    items = result.get('items') or []
    # 曲目数只在 adapter 承诺整册曲目时给出（album_track_count）；其余源留 None（不臆造）。
    data = AlbumData(source=source, name=name, artist=artist or None,
                     albums=result.get('albums') or [], items=items, total=len(items),
                     track_count=len(items) if getattr(adapter, 'album_track_count', False) else None)
    return ok(data.model_dump())


async def playlist(request: Request, source: str, name: str = Query(..., min_length=1),
                   page: int = Query(1, ge=1)):
    '''P6 歌单检索：歌单名 → 候选歌单 + 首选歌单的有序曲目（item 含 track_no）。
       未实现源由 base.playlist() 抛 501 envelope。'''
    s = request.app.state
    adapter = get_adapter(s, source)
    result, hit = await cached(
        s.meta_cache, (source, 'playlist', name, page),
        lambda: asyncio.wait_for(adapter.playlist(name, page),
                                 timeout=s.settings.hard_timeout_s))
    items = result.get('items') or []
    data = PlaylistData(source=source, name=name,
                        playlists=result.get('playlists') or [], items=items, total=len(items))
    return ok(data.model_dump())
