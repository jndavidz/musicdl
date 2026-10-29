'''
Function:
    kw-qq-music-api: self-hosted Kuwo + QQ music API on top of musicdl parse chains.
    Endpoints follow the kugou/netease RESTful style; primary consumer is MusicFree plugins.
Run:
    uvicorn server.app:app --host 0.0.0.0 --port 3003
Notes:
    create_app(settings) is the single assembly point: caches / health / adapters live
    on app.state (injected, replaceable in tests). Handlers live in server/routes/*;
    this file keeps only the factory, system endpoints and exception mapping.
'''
import os
import sys
import time
import asyncio
import contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST

from server.config import settings, get_settings
from server.cache import TTLCache
from server.parsers_health import ParserHealth
from server.envelope import ok, err, envelope
from server.schemas import Envelope
from server.adapters import ADAPTER_CLASSES, AdapterError
from server.auth import install_auth
from server.metrics import Metrics
from server.ratelimit import install_ratelimit
from server.scopes import ScopeRegistry, ScopeDenied
from server.routes import resolve, kugou_vip, passthrough, playback


async def healthz(request: Request):
    return ok({'status': 'up', 'uptime_s': round(time.time() - request.app.state.started_at)})


async def metrics(request: Request):
    m = request.app.state.metrics
    m.sync_from_state(request.app.state)
    return Response(content=m.render(), media_type=CONTENT_TYPE_LATEST)


async def status(request: Request):
    s = request.app.state
    return ok({
        'uptime_s': round(time.time() - s.started_at),
        'parsers': s.health.snapshot(),   # keys are "<source>:<parser_name>"
        'caches': {'url': s.url_cache.stats(), 'search': s.search_cache.stats(), 'meta': s.meta_cache.stats(),
                   'lyric': s.lyric_cache.stats(), 'v2_url': s.v2_url_cache.stats()},
        # per-source real-work counters (active = threads still running, waiters = admitted
        # callers queued for a slot). Cross-project acceptance sums these with Songloft's.
        'runtime': {key: a.runtime_stats() for key, a in s.adapters.items()
                    if hasattr(a, 'runtime_stats')},
        'settings': {'enable_lossless': s.settings.enable_lossless, 'tester_timeout': s.settings.tester_timeout,
                     'hard_timeout_s': s.settings.hard_timeout_s,
                     'max_concurrency_per_source': s.settings.max_concurrency_per_source,
                     'max_waiters_per_source': s.settings.max_waiters_per_source,
                     'io_timeout_s': s.settings.io_timeout_s},
    })


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    st = app.state.settings
    for key, cls in ADAPTER_CLASSES.items():
        app.state.adapters[key] = cls(st, app.state.health)
    try:
        yield
    finally:
        for adapter in app.state.adapters.values():
            if hasattr(adapter, 'shutdown'):
                adapter.shutdown()


def create_app(st=None) -> FastAPI:
    st = st or get_settings()
    app = FastAPI(title='kw-qq-music-api', version='1.0.0',
                  description='Kuwo + QQ Music API powered by musicdl (hifi branch parse chains)',
                  lifespan=_lifespan)
    app.state.settings = st
    app.state.started_at = time.time()
    app.state.url_cache = TTLCache(st.url_cache_ttl)
    app.state.v2_url_cache = TTLCache(st.url_cache_ttl)
    app.state.search_cache = TTLCache(st.search_cache_ttl)
    app.state.meta_cache = TTLCache(st.meta_cache_ttl)
    app.state.lyric_cache = TTLCache(st.meta_cache_ttl)
    app.state.health = ParserHealth(fail_threshold=st.parser_fail_threshold, cooldown_s=st.parser_cooldown_s)
    app.state.scopes = ScopeRegistry(st.service_tokens, download_key=st.api_key,
                                     default_generation=st.credential_generation)
    app.state.adapters = {}
    app.state.metrics = Metrics()

    app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
    install_auth(app, st)

    # order (outermost first after all adds): metrics > ratelimit > auth > CORS.
    # ratelimit sheds external floods before auth/routes; metrics sits above
    # everything so 401/429 responses are counted too.
    install_ratelimit(app, st)

    @app.middleware('http')
    async def metrics_middleware(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get('route')
        request.app.state.metrics.observe(getattr(route, 'path', None) or 'other',
                                          response.status_code, time.perf_counter() - t0)
        return response

    @app.exception_handler(AdapterError)
    async def adapter_error_handler(request: Request, exc: AdapterError):
        resp = err(exc.code, exc.msg)
        if exc.code == 429:
            # upstream throttling is classified separately from the local rate limiter
            resp.headers['X-RateLimit-Scope'] = 'upstream'
            if exc.retry_after:
                resp.headers['Retry-After'] = str(int(exc.retry_after))
        return resp

    @app.exception_handler(ScopeDenied)
    async def scope_denied_handler(request: Request, exc: ScopeDenied):
        # authorization class, not a business miss: real 401/403 status
        return JSONResponse(envelope(exc.code, exc.msg, None), status_code=exc.code)

    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_handler(request: Request, exc: asyncio.TimeoutError):
        return err(504, f'upstream timed out after {request.app.state.settings.hard_timeout_s}s')

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        return err(502, f'upstream failure: {type(exc).__name__}: {str(exc)[:180]}')

    R = app.add_api_route
    R('/{source}/search', resolve.search, methods=['GET'], response_model=Envelope, summary='search songs')
    R('/{source}/song/url', resolve.song_url, methods=['GET'], response_model=Envelope, summary='resolve playback url by song id')
    R('/{source}/song/info', resolve.song_info, methods=['GET'], response_model=Envelope, summary='song meta info by id')
    R('/{source}/lyric', resolve.lyric, methods=['GET'], response_model=Envelope, summary='lyrics (LRC text) by id')
    R('/{source}/album', resolve.album, methods=['GET'], response_model=Envelope, summary='album search: ordered tracks (P6)')
    R('/{source}/playlist', resolve.playlist, methods=['GET'], response_model=Envelope, summary='playlist search: ordered tracks (P6)')
    R('/v2/playback/resolve', playback.resolve, methods=['POST'], response_model=Envelope, summary='v2 managed playback: TrackRef -> resolved candidate')
    R('/v2/cache/invalidate', playback.invalidate, methods=['POST'], response_model=Envelope, summary='v2 scoped invalidation of one cached candidate')
    R('/kugou/vip/day', kugou_vip.vip_day, methods=['POST'], summary='claim today concept listening VIP')
    R('/kugou/vip/upgrade', kugou_vip.vip_upgrade, methods=['POST'], summary='upgrade concept vip reward')
    R('/kugou/vip/status', kugou_vip.vip_status, methods=['GET'], summary='structured vip entitlements + monthly claim records')
    R('/kugou/api/{path:path}', passthrough.kugou_get, methods=['GET'], summary='passthrough: any KuGouMusicApi endpoint')
    R('/kugou/api/{path:path}', passthrough.kugou_post, methods=['POST'], summary='passthrough POST')
    R('/netease/api/{path:path}', passthrough.netease_get, methods=['GET'], summary='passthrough: any NeteaseCloudMusicApi endpoint')
    R('/netease/api/{path:path}', passthrough.netease_post, methods=['POST'], summary='passthrough POST')
    R('/healthz', healthz, methods=['GET'], summary='liveness probe')
    R('/status', status, methods=['GET'], summary='parser health & cache stats')
    R('/metrics', metrics, methods=['GET'], summary='Prometheus exposition (plain text, not enveloped)')
    return app


app = create_app()
