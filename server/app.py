'''
Function:
    kw-qq-music-api: self-hosted Kuwo + QQ music API on top of musicdl parse chains.
    Endpoints follow the kugou/netease RESTful style; primary consumer is MusicFree plugins.
Run:
    uvicorn server.app:app --host 0.0.0.0 --port 3003
'''
import os
import sys
import time
import asyncio
import contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.config import settings, SOURCES, QUALITY_ALIASES
from server.cache import TTLCache
from server.parsers_health import ParserHealth
from server.schemas import Envelope, SearchData, SearchItem, SongUrlData, SongInfoData, LyricData
from server.adapters import ADAPTER_CLASSES, AdapterError


'''app state'''
_started_at = time.time()
url_cache = TTLCache(settings.url_cache_ttl)
search_cache = TTLCache(settings.search_cache_ttl)
meta_cache = TTLCache(settings.meta_cache_ttl)
lyric_cache = TTLCache(settings.meta_cache_ttl)
health = ParserHealth(fail_threshold=settings.parser_fail_threshold, cooldown_s=settings.parser_cooldown_s)
adapters: dict = {}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    for key, cls in ADAPTER_CLASSES.items():
        adapters[key] = cls(settings, health)
    yield


app = FastAPI(title='kw-qq-music-api', version='1.0.0', description='Kuwo + QQ Music API powered by musicdl (hifi branch parse chains)', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])


def ok(data) -> dict:
    return {'code': 200, 'msg': 'success', 'data': data, 'timestamp': int(time.time() * 1000)}


def err(code: int, msg: str) -> JSONResponse:
    return JSONResponse({'code': code, 'msg': msg, 'data': None, 'timestamp': int(time.time() * 1000)}, status_code=200 if code in {403, 404} else code)


def get_adapter(source: str):
    if source not in SOURCES: raise AdapterError(404, f'unknown source "{source}" (available: {", ".join(SOURCES)})')
    return adapters[source]


@app.exception_handler(AdapterError)
async def adapter_error_handler(request: Request, exc: AdapterError):
    return err(exc.code, exc.msg)


@app.exception_handler(asyncio.TimeoutError)
async def timeout_handler(request: Request, exc: asyncio.TimeoutError):
    return err(504, f'upstream timed out after {settings.hard_timeout_s}s')


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return err(502, f'upstream failure: {type(exc).__name__}: {str(exc)[:180]}')


'''---------------- endpoints ----------------'''


@app.get('/{source}/search', response_model=Envelope, summary='search songs')
async def search(source: str, keywords: str = Query(..., min_length=1), page: int = Query(1, ge=1), limit: int = Query(settings.search_size_default, ge=1, le=settings.search_size_max)):
    adapter = get_adapter(source)
    limit = min(limit, settings.search_size_max)
    cache_key = f'{source}:{keywords}:{page}:{limit}'
    items = search_cache.get(cache_key)
    if items is None:
        items = await adapter.search_items(keywords, limit, page)
        search_cache.set(cache_key, items)
    data = SearchData(keywords=keywords, page=page, total=len(items), items=items[:limit])
    return ok(data.model_dump())


@app.get('/{source}/song/url', response_model=Envelope, summary='resolve playback url by song id')
async def song_url(source: str, id: str = Query(..., min_length=1), quality: str = Query('auto')):
    adapter = get_adapter(source)
    q = QUALITY_ALIASES.get(quality.lower(), 'auto')
    cache_key = f'{source}:{id}:{q}'
    cached = url_cache.get(cache_key)
    if cached:
        cached['cached'] = True; return ok(SongUrlData(**cached).model_dump())
    result = await asyncio.wait_for(adapter.song_url(id, q), timeout=settings.hard_timeout_s)
    url_cache.set(cache_key, result)
    return ok(SongUrlData(**result).model_dump())


@app.get('/{source}/song/info', response_model=Envelope, summary='song meta info by id')
async def song_info(source: str, id: str = Query(..., min_length=1)):
    adapter = get_adapter(source)
    cache_key = f'{source}:info:{id}'
    cached = meta_cache.get(cache_key)
    if cached: return ok(SongInfoData(**cached).model_dump())
    result = await asyncio.wait_for(adapter.song_info(id), timeout=settings.hard_timeout_s)
    meta_cache.set(cache_key, result)
    return ok(SongInfoData(**result).model_dump())


@app.get('/{source}/lyric', response_model=Envelope, summary='lyrics (LRC text) by id')
async def lyric(source: str, id: str = Query(..., min_length=1)):
    adapter = get_adapter(source)
    cache_key = f'{source}:lyric:{id}'
    cached = lyric_cache.get(cache_key)
    if cached is not None: return ok(LyricData(id=id, source=source, lyric=cached, cached=True).model_dump())
    text = await asyncio.wait_for(adapter.lyric(id), timeout=settings.hard_timeout_s)
    lyric_cache.set(cache_key, text)
    return ok(LyricData(id=id, source=source, lyric=text, cached=False).model_dump())


@app.get('/healthz', summary='liveness probe')
async def healthz():
    return ok({'status': 'up', 'uptime_s': round(time.time() - _started_at)})


@app.get('/status', summary='parser health & cache stats')
async def status():
    return ok({
        'uptime_s': round(time.time() - _started_at),
        'sources': {key: {'parsers': adapter.health.snapshot()} for key, adapter in adapters.items()},
        'caches': {'url': url_cache.stats(), 'search': search_cache.stats(), 'meta': meta_cache.stats(), 'lyric': lyric_cache.stats()},
        'settings': {'enable_lossless': settings.enable_lossless, 'tester_timeout': settings.tester_timeout,
                     'hard_timeout_s': settings.hard_timeout_s, 'max_concurrency_per_source': settings.max_concurrency_per_source},
    })
