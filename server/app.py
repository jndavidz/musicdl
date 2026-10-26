'''
Function:
    kw-qq-music-api: self-hosted Kuwo + QQ music API on top of musicdl parse chains.
    Endpoints follow the kugou/netease RESTful style; primary consumer is MusicFree plugins.
Run:
    uvicorn server.app:app --host 0.0.0.0 --port 3003
Notes:
    create_app(settings) is the single assembly point: caches / health / adapters live on
    app.state (injected, replaceable in tests), handlers read request.app.state. The
    module-level `app` is the production instance with the env singleton settings.
'''
import os
import sys
import time
import asyncio
import contextlib
import functools as _ft

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from server.config import settings, SOURCES, QUALITY_ALIASES, get_settings
from server.cache import TTLCache
from server.parsers_health import ParserHealth
from server.schemas import Envelope, SearchData, SongUrlData, SongInfoData, LyricData
from server.adapters import ADAPTER_CLASSES, AdapterError
from datetime import datetime, timezone, timedelta as _td
from server import proxy as passthrough

PROXY_TIMEOUT = 40


'''---------------- envelope & lookup helpers ----------------'''


def ok(data) -> dict:
    return {'code': 200, 'msg': 'success', 'data': data, 'timestamp': int(time.time() * 1000)}


def err(code: int, msg: str) -> JSONResponse:
    return JSONResponse({'code': code, 'msg': msg, 'data': None, 'timestamp': int(time.time() * 1000)}, status_code=200 if code in {403, 404} else code)


def get_adapter(state, source: str):
    if source not in SOURCES:
        raise AdapterError(404, f'unknown source "{source}" (available: {", ".join(SOURCES)})')
    adapter = state.adapters.get(source)
    if adapter is None:
        raise AdapterError(404, f'source "{source}" is not enabled on this server')
    return adapter


def _shanghai_today() -> str:
    return datetime.now(timezone(_td(hours=8))).strftime('%Y-%m-%d')


def _vip_result(raw_status_body: bytes) -> Response:
    import json as _json
    d = _json.loads(raw_status_body.decode('utf-8', errors='ignore'))
    code, err_msg = d.get('error_code'), d.get('error_msg', '')
    if d.get('status') == 1:
        return ok({'success': True, 'data': d.get('data'), 'raw_code': code})
    semantic = {131001: 'already claimed today', 297002: 'upgrade reward already claimed'}.get(code)
    return JSONResponse({'code': 200 if semantic else 500, 'msg': semantic or err_msg or f'error_code {code}',
                         'data': {'success': bool(semantic), 'error_code': code}, 'timestamp': int(time.time()*1000)},
                        status_code=200)


'''---------------- request handlers (read everything off request.app.state) ----------------'''


async def search(request: Request, source: str, keywords: str = Query(..., min_length=1),
                 page: int = Query(1, ge=1), limit: int = Query(None, ge=1)):
    s = request.app.state
    st = s.settings
    adapter = get_adapter(s, source)
    limit = min(limit or st.search_size_default, st.search_size_max)
    cache_key = f'{source}:{keywords}:{page}:{limit}'
    items = s.search_cache.get(cache_key)
    if items is None:
        items = await adapter.search_items(keywords, limit, page)
        s.search_cache.set(cache_key, items)
    data = SearchData(keywords=keywords, page=page, total=len(items), items=items[:limit])
    return ok(data.model_dump())


async def song_url(request: Request, source: str, id: str = Query(..., min_length=1), quality: str = Query('auto'),
                   copyright: str = Query('', description='migu only: copyrightId from search item extra')):
    s = request.app.state
    adapter = get_adapter(s, source)
    q = QUALITY_ALIASES.get(quality.lower(), 'auto')
    cache_key = f'{source}:{id}:{q}:{copyright}'
    cached = s.url_cache.get(cache_key)
    if cached:
        cached['cached'] = True; return ok(SongUrlData(**cached).model_dump())
    kwargs = {'copyright_id': copyright} if source == 'migu' else {}
    route_timeout = getattr(adapter, 'timeout_override', 0) or s.settings.hard_timeout_s
    result = await asyncio.wait_for(adapter.song_url(id, q, **kwargs), timeout=route_timeout)
    s.url_cache.set(cache_key, result)
    return ok(SongUrlData(**result).model_dump())


async def song_info(request: Request, source: str, id: str = Query(..., min_length=1),
                    copyright: str = Query('', description='migu only: copyrightId from search item extra')):
    s = request.app.state
    adapter = get_adapter(s, source)
    cache_key = f'{source}:info:{id}'
    cached = s.meta_cache.get(cache_key)
    if cached: return ok(SongInfoData(**cached).model_dump())
    kwargs = {'copyright_id': copyright} if source == 'migu' else {}
    result = await asyncio.wait_for(adapter.song_info(id, **kwargs), timeout=s.settings.hard_timeout_s)
    s.meta_cache.set(cache_key, result)
    return ok(SongInfoData(**result).model_dump())


async def lyric(request: Request, source: str, id: str = Query(..., min_length=1)):
    s = request.app.state
    adapter = get_adapter(s, source)
    cache_key = f'{source}:lyric:{id}'
    cached = s.lyric_cache.get(cache_key)
    if cached is not None: return ok(LyricData(id=id, source=source, lyric=cached, cached=True).model_dump())
    text = await asyncio.wait_for(adapter.lyric(id), timeout=s.settings.hard_timeout_s)
    s.lyric_cache.set(cache_key, text)
    return ok(LyricData(id=id, source=source, lyric=text, cached=False).model_dump())


# kugou vip ops (semantic endpoints over passthrough)

async def kugou_vip_day(request: Request):
    s = request.app.state
    day = _shanghai_today()
    status, ctype, raw = await s.adapters['kugou'].run(
        lambda: passthrough.fetch('kugou', 'GET', 'youth/day/vip',
                                  {'receive_day': day}, kugou_cookie_fn=s.adapters['kugou']._get_cookie,
                                  timeout=PROXY_TIMEOUT))
    return _vip_result(raw)


async def kugou_vip_upgrade(request: Request):
    s = request.app.state
    status, ctype, raw = await s.adapters['kugou'].run(
        lambda: passthrough.fetch('kugou', 'GET', 'youth/day/vip/upgrade',
                                  kugou_cookie_fn=s.adapters['kugou']._get_cookie, timeout=PROXY_TIMEOUT))
    return _vip_result(raw)


async def kugou_vip_status(request: Request):
    import json as _json
    s = request.app.state

    def _fetch(path):
        return passthrough.fetch('kugou', 'GET', path,
                                 kugou_cookie_fn=s.adapters['kugou']._get_cookie, timeout=PROXY_TIMEOUT)

    union_st, _, union_raw = await s.adapters['kugou'].run(_fetch, 'youth/union/vip')
    rec_st, _, rec_raw = await s.adapters['kugou'].run(_fetch, 'youth/month/vip/record')

    def _load(raw):
        try:
            d = _json.loads(raw.decode('utf-8', errors='ignore'))
            return d.get('data') if isinstance(d.get('data'), dict) else {}
        except Exception:
            return {}

    union, record = _load(union_raw), _load(rec_raw)

    def _busi(product_type):
        for item in (union.get('busi_vip') or []):
            if isinstance(item, dict) and item.get('product_type') == product_type:
                return {'is_vip': bool(item.get('is_vip')), 'begin': item.get('vip_begin_time'),
                        'end': item.get('vip_end_time')}
        return {'is_vip': False, 'begin': None, 'end': None}

    claims = [{'day': r.get('day'), 'vip_type': r.get('vip_type')} for r in (record.get('list') or []) if isinstance(r, dict)]
    return ok({
        'svip_concept': _busi('svip'),          # 概念版 VIP
        'tvip_listening': _busi('tvip'),        # 畅听 VIP
        'claimed_days_this_month': len(claims),
        'claim_records': claims,
        'month': record.get('month'),
        'future_duration': record.get('future_duration'),
        'raw': {'union': union, 'record': record},
    })


# generic passthrough to sibling containers
# covers ALL upstream endpoints (catalog browsing / vip ops / comments / ...)
# with account cookies injected; body streamed verbatim; API-key guarded globally.

async def kugou_proxy_get(request: Request, path: str):
    s = request.app.state
    fn = _ft.partial(passthrough.fetch, source='kugou', method='GET', path=path,
                     query=dict(request.query_params),
                     kugou_cookie_fn=s.adapters['kugou']._get_cookie, timeout=PROXY_TIMEOUT)
    status, ctype, body = await s.adapters['kugou'].run(fn)
    return Response(content=body, status_code=status, media_type=ctype)


async def kugou_proxy_post(request: Request, path: str):
    s = request.app.state
    body = await request.body()
    fn = _ft.partial(passthrough.fetch, source='kugou', method='POST', path=path,
                     body=body, content_type=request.headers.get('content-type',
                     'application/json'),
                     kugou_cookie_fn=s.adapters['kugou']._get_cookie, timeout=PROXY_TIMEOUT)
    status, ctype, out = await s.adapters['kugou'].run(fn)
    return Response(content=out, status_code=status, media_type=ctype)


async def netease_proxy_get(request: Request, path: str):
    s = request.app.state
    fn = _ft.partial(passthrough.fetch, source='netease', method='GET', path=path,
                     query=dict(request.query_params), timeout=PROXY_TIMEOUT)
    status, ctype, body = await s.adapters['netease'].run(fn)
    return Response(content=body, status_code=status, media_type=ctype)


async def netease_proxy_post(request: Request, path: str):
    s = request.app.state
    body = await request.body()
    fn = _ft.partial(passthrough.fetch, source='netease', method='POST', path=path,
                     body=body, content_type=request.headers.get('content-type',
                     'application/json'), timeout=PROXY_TIMEOUT)
    status, ctype, out = await s.adapters['netease'].run(fn)
    return Response(content=out, status_code=status, media_type=ctype)


async def healthz(request: Request):
    return ok({'status': 'up', 'uptime_s': round(time.time() - request.app.state.started_at)})


async def status(request: Request):
    s = request.app.state
    return ok({
        'uptime_s': round(time.time() - s.started_at),
        'parsers': s.health.snapshot(),   # keys are "<source>:<parser_name>"
        'caches': {'url': s.url_cache.stats(), 'search': s.search_cache.stats(), 'meta': s.meta_cache.stats(), 'lyric': s.lyric_cache.stats()},
        'settings': {'enable_lossless': s.settings.enable_lossless, 'tester_timeout': s.settings.tester_timeout,
                     'hard_timeout_s': s.settings.hard_timeout_s, 'max_concurrency_per_source': s.settings.max_concurrency_per_source},
    })


'''---------------- app factory ----------------'''


def _install_auth(app: FastAPI, st):
    '''service-level API key guard: Lucky's per-sub-rule Basic Auth only challenges the exact `/` path,
       so functional paths need their own protection when exposed. Disabled when API_KEY is empty.
       Requests from trusted LAN networks bypass the check (direct intranet access needs no key);
       the Lucky router IP is explicitly untrusted because it relays all external traffic.'''
    if not st.api_key:
        return
    import base64 as _b64
    import ipaddress as _ip

    def _from_trusted_lan(client_host: str) -> bool:
        if client_host in st.untrusted_hosts: return False
        try:
            addr = _ip.ip_address(client_host.split('%')[0])
        except Exception:
            return False
        return any(addr in net for net in st.trusted_networks)

    @app.middleware('http')
    async def api_key_guard(request: Request, call_next):
        client_host = request.client.host if request.client else ''
        if request.url.path != '/healthz' and not _from_trusted_lan(client_host):
            provided = request.headers.get('x-api-key', '')
            if not provided:
                auth = request.headers.get('authorization', '')
                if auth.startswith('Basic '):
                    try: provided = _b64.b64decode(auth[6:]).decode('utf-8', errors='ignore').split(':', 1)[0]
                    except Exception: provided = ''
            if provided != request.app.state.settings.api_key:
                return JSONResponse({'code': 401, 'msg': 'unauthorized: missing or invalid API key', 'data': None},
                                    status_code=401, headers={'WWW-Authenticate': 'Basic realm="Authorization Required"'})
        return await call_next(request)


def create_app(st=None) -> FastAPI:
    st = st or get_settings()
    app = FastAPI(title='kw-qq-music-api', version='1.0.0',
                  description='Kuwo + QQ Music API powered by musicdl (hifi branch parse chains)',
                  lifespan=_lifespan)
    app.state.settings = st
    app.state.started_at = time.time()
    app.state.url_cache = TTLCache(st.url_cache_ttl)
    app.state.search_cache = TTLCache(st.search_cache_ttl)
    app.state.meta_cache = TTLCache(st.meta_cache_ttl)
    app.state.lyric_cache = TTLCache(st.meta_cache_ttl)
    app.state.health = ParserHealth(fail_threshold=st.parser_fail_threshold, cooldown_s=st.parser_cooldown_s)
    app.state.adapters = {}

    app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
    _install_auth(app, st)

    @app.exception_handler(AdapterError)
    async def adapter_error_handler(request: Request, exc: AdapterError):
        return err(exc.code, exc.msg)

    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_handler(request: Request, exc: asyncio.TimeoutError):
        return err(504, f'upstream timed out after {request.app.state.settings.hard_timeout_s}s')

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        return err(502, f'upstream failure: {type(exc).__name__}: {str(exc)[:180]}')

    R = app.add_api_route
    R('/{source}/search', search, methods=['GET'], response_model=Envelope, summary='search songs')
    R('/{source}/song/url', song_url, methods=['GET'], response_model=Envelope, summary='resolve playback url by song id')
    R('/{source}/song/info', song_info, methods=['GET'], response_model=Envelope, summary='song meta info by id')
    R('/{source}/lyric', lyric, methods=['GET'], response_model=Envelope, summary='lyrics (LRC text) by id')
    R('/kugou/vip/day', kugou_vip_day, methods=['POST'], summary='claim today concept listening VIP')
    R('/kugou/vip/upgrade', kugou_vip_upgrade, methods=['POST'], summary='upgrade concept vip reward')
    R('/kugou/vip/status', kugou_vip_status, methods=['GET'], summary='structured vip entitlements + monthly claim records')
    R('/kugou/api/{path:path}', kugou_proxy_get, methods=['GET'], summary='passthrough: any KuGouMusicApi endpoint')
    R('/kugou/api/{path:path}', kugou_proxy_post, methods=['POST'], summary='passthrough POST')
    R('/netease/api/{path:path}', netease_proxy_get, methods=['GET'], summary='passthrough: any NeteaseCloudMusicApi endpoint')
    R('/netease/api/{path:path}', netease_proxy_post, methods=['POST'], summary='passthrough POST')
    R('/healthz', healthz, methods=['GET'], summary='liveness probe')
    R('/status', status, methods=['GET'], summary='parser health & cache stats')
    return app


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    st = app.state.settings
    for key, cls in ADAPTER_CLASSES.items():
        app.state.adapters[key] = cls(st, app.state.health)
    yield


app = create_app()
