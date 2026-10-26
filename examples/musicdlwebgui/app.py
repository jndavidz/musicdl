'''
Function:
    musicdl-webgui: an easy-to-use web GUI for musicdl.
    Search across platforms with per-source result limits, download everything
    into ONE flat directory with human-readable names (artist - title - album),
    quality-tier preference, and lyrics/cover/tags embedded into a single audio file.
Design notes (library coupling contract, see README "库耦合契约"):
    * search(persist_results=False)   -> no per-platform workdirs / pkl files
    * SongInfo._save_path override    -> one fixed download dir + readable names
    * client._download(...)           -> per-item download without pkl dumping
    * ProgressStub                    -> duck-typed progress adapter feeding SSE
      (the library's progress parameter is a callback channel; this is NOT a
       library patch — sanctioned per the coupling contract below)
    * SongInfoUtils.lrc_saver set     -> library extension point, no .lrc sidecar
      unless enabled in config (lyrics/cover/tags stay embedded in the ONE file)
Patch inventory (contract: count only decreases; new patches need README rationale):
    - SongInfoUtils.lrc_saver  (extension point, batch-5 sanctioned)  — 1 active
Module layout (roadmap D1; this file = FastAPI assembly + routes + entrypoint):
    config.py    config path/defaults + platform registry (no import side effects)
    quality.py   quality tiers / naming / dedupe keys / serialize_item
    kwqq_api.py  kwqq-api (NAS six-source) client: search + two-stage resolve
    library.py   musicdl in-process layer: client pool, lrc_saver patch,
                 ProgressStub, kuwo VIP path, search dispatch
    downloads.py result store + dedupe stats + DownloadEngine
    app.py       THIS file: FastAPI app, routes, lifespan, main()
Import-time side effects were moved into the FastAPI lifespan (roadmap D1):
first-run config bootstrap and download-dir creation now run at startup instead
of at module import.
Run:
    cd /mnt/d/_work/repos/musicdl && uv run python examples/musicdlwebgui/app.py --port 3004
'''
import sys
import json
import time
import uuid
import argparse
import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import (MODULE_DIR, CONFIG_PATH, DEFAULT_CONFIG, PLATFORMS, PLATFORM_MAP,
                    SETTINGS, save_config, touch_download_dir)
from quality import QUALITY_ORDER, QUALITY_PREF_RANKS, LOSSLESS_MBPM_FLOOR, MASTER_MBPM, serialize_item
import quality
from kwqq_api import api_online, api_resolve_into
from library import kuwo_vip_enabled, search_platform_sync
from downloads import engine, RESULT_STORE, STORE_LOCK, DEDUPE_STATS, DEDUPE_STATS_LOCK

'''---------------- kuwo explicit-tier table (webgui/server contract) ----------------'''

# NOTE: this literal MUST stay in app.py — server/tests/test_offline.py extracts it
# via ast (no import) from this exact file to keep the webgui/server kuwo tag tables
# in sync (section 5). It is injected into the quality module for serialize_item.
PLATFORM_TAG_TIER = {
    # kuwo (nmobi br 档, 匿名直出)
    '20900kmflac': 'master', 'master': 'master',
    'surround51': 'surround51', '20501kmflac': 'surround51',
    '2000kflac': 'lossless', 'flac': 'lossless',
    '320kmp3': '320k', '320': '320k', '128kmp3': '128k', '128': '128k',
    # kugou (quality 档, 概念版 cookie)
    'high': 'hires',
    # netease (granted level, 88VIP)
    'jymaster': 'master', 'jyeffect': 'hires', 'sky': 'hires', 'dolby': 'hires',
    'hires': 'hires', 'lossless': 'lossless', 'exhigh': '320k', 'standard': '128k',
}
quality.PLATFORM_TAG_TIER = PLATFORM_TAG_TIER

'''---------------- fastapi app ----------------'''


@asynccontextmanager
async def _startup_lifespan(app: FastAPI):
    '''startup side effects moved here from import time (roadmap D1):
    first-run config bootstrap (write default config.json) + download-dir creation.'''
    if not CONFIG_PATH.exists(): save_config(SETTINGS)
    touch_download_dir()
    yield


app = FastAPI(title='musicdl-webgui', version='1.0.0', description='Easy web GUI on top of musicdl',
              lifespan=_startup_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])


@app.middleware('http')
async def api_key_guard(request: Request, call_next):
    api_key = SETTINGS.get('api_key') or ''
    if api_key and request.url.path != '/healthz':
        provided = request.headers.get('x-api-key', '')
        if not provided:
            auth = request.headers.get('authorization', '')
            if auth.startswith('Basic '):
                import base64
                with contextlib.suppress(Exception):
                    provided = base64.b64decode(auth[6:]).decode('utf-8', errors='ignore').split(':', 1)[0]
        if provided != api_key:
            return JSONResponse({'code': 401, 'msg': 'unauthorized'}, status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="webgui"'})
    return await call_next(request)


class SearchBody(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=120)
    sources: dict = Field(..., description='{"qq": 5, "kuwo": 3} per-source limits')


class DownloadBody(BaseModel):
    keys: list = Field(..., min_length=1)
    quality_pref: str = Field(default=SETTINGS['quality_pref_default'])
    dedupe: bool = Field(default=True)


class RetryBody(BaseModel):
    item_id: str


class ResolveBody(BaseModel):
    keys: list = Field(..., min_length=1)
    quality_pref: str = Field(default=SETTINGS['quality_pref_default'])


@app.post('/api/resolve')
async def resolve_items(body: ResolveBody):
    '''pre-resolve pending kwqq-api items (per-song /song/url) so the UI can show the real
    ext/size/tier before downloading; server-side URL cache (600s) makes later downloads free.'''
    keys = body.keys[:50]
    if body.quality_pref not in QUALITY_PREF_RANKS:
        return JSONResponse({'code': 400, 'msg': f'quality_pref 必须是 {list(QUALITY_PREF_RANKS)} 之一'}, status_code=200)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(3)

    async def one(key: str):
        with STORE_LOCK:
            info = RESULT_STORE.get(key)
        if info is None or getattr(info, 'api_id', None) is None:
            return {'key': key, 'resolve_error': '条目不存在或非 API 来源'}
        async with sem:
            try:
                await asyncio.wait_for(loop.run_in_executor(None, api_resolve_into, info, body.quality_pref), timeout=45)
            except Exception as err:
                # metadata backfill inside api_resolve_into still counts: keep the
                # enriched entry so the UI retains duration/size even on url failures
                with STORE_LOCK: RESULT_STORE[key] = info
                entry = serialize_item(key, info, info.source or key.split(':', 1)[0])
                entry['resolve_error'] = str(err)[:180]
                return entry
        with STORE_LOCK:
            RESULT_STORE[key] = info
        return serialize_item(key, info, info.source or key.split(':', 1)[0])

    results = await asyncio.gather(*[one(k) for k in keys])
    ok, failed = [], []
    for r in results:
        if not r: continue
        (failed.append({'key': r['key'], 'error': r['resolve_error'], **{k: v for k, v in r.items() if k not in {'resolve_error'}}})
         if r.get('resolve_error') else ok.append(r))
    return {'code': 200, 'msg': 'ok', 'data': {'items': ok, 'failed': failed}}


class ConfigBody(BaseModel):
    download_dir: str | None = None
    naming_template: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=8)
    search_timeout_s: int | None = Field(default=None, ge=10, le=180)
    save_lrc_sidecar: bool | None = None
    quality_guard: bool | None = None
    quality_pref_default: str | None = None
    dedupe_default: bool | None = None
    api_key: str | None = None
    platform_defaults: dict | None = None
    platform_subsources: dict | None = None
    kuwo_vip_cookie: str | None = None


@app.get('/healthz')
async def healthz(): return {'code': 200, 'msg': 'up', 'data': {'ts': int(time.time())}}


@app.get('/api/stats/dedupe')
async def dedupe_stats():
    '''contested dedupe win-source counters (in-memory) — ADR-0001 fallback-channel review data'''
    with DEDUPE_STATS_LOCK:
        data = {'contested': DEDUPE_STATS['contested'],
                'wins': dict(DEDUPE_STATS['wins']),
                'by_origin_source': dict(DEDUPE_STATS['by_origin_source'])}
    return {'code': 200, 'msg': 'ok', 'data': data}


@app.get('/api/config')
async def get_config():
    return {'code': 200, 'msg': 'ok', 'data': {
        'download_dir': SETTINGS['download_dir'], 'naming_template': SETTINGS['naming_template'],
        'concurrency': SETTINGS['concurrency'], 'search_timeout_s': SETTINGS['search_timeout_s'],
        'save_lrc_sidecar': SETTINGS['save_lrc_sidecar'], 'quality_pref_default': SETTINGS['quality_pref_default'],
        'dedupe_default': SETTINGS['dedupe_default'], 'max_limit_per_source': SETTINGS['max_limit_per_source'],
        'quality_guard': SETTINGS.get('quality_guard', True),
        'lossless_mbpm_floor': LOSSLESS_MBPM_FLOOR, 'master_mbpm': MASTER_MBPM,
        'mp3_size_floors_mb': {'320k': 5, '128k': 2},
        'has_api_key': bool(SETTINGS.get('api_key')), 'config_path': str(CONFIG_PATH),
        'kwqq_api_base': SETTINGS['kwqq_api_base'], 'kwqq_api_online': api_online(),
        'kuwo_vip_enabled': kuwo_vip_enabled(),
        'platform_defaults': dict(SETTINGS['platform_defaults']),
        'platform_subsources': dict(SETTINGS.get('platform_subsources') or {}),
        'platforms': [{**p, 'default_limit': SETTINGS['platform_defaults'].get(p['id'], 5)} for p in PLATFORMS],
    }}


@app.put('/api/config')
async def put_config(body: ConfigBody):
    changed = []
    if body.download_dir:
        SETTINGS['download_dir'] = body.download_dir.strip(); touch_download_dir(); changed.append('download_dir')
    if body.naming_template is not None:
        template = body.naming_template.strip() or DEFAULT_CONFIG['naming_template']
        if '{title}' not in template: return JSONResponse({'code': 400, 'msg': '命名模板必须包含 {title}'}, status_code=200)
        SETTINGS['naming_template'] = template; changed.append('naming_template')
    if body.concurrency is not None: SETTINGS['concurrency'] = body.concurrency; changed.append('concurrency (重启后生效)')
    if body.search_timeout_s is not None: SETTINGS['search_timeout_s'] = body.search_timeout_s; changed.append('search_timeout_s')
    if body.save_lrc_sidecar is not None: SETTINGS['save_lrc_sidecar'] = body.save_lrc_sidecar; changed.append('save_lrc_sidecar')
    if body.quality_guard is not None: SETTINGS['quality_guard'] = body.quality_guard; changed.append('quality_guard')
    if body.quality_pref_default:
        if body.quality_pref_default not in QUALITY_PREF_RANKS:
            return JSONResponse({'code': 400, 'msg': f'quality_pref_default 必须是 {list(QUALITY_PREF_RANKS)} 之一'}, status_code=200)
        SETTINGS['quality_pref_default'] = body.quality_pref_default; changed.append('quality_pref_default')
    if body.dedupe_default is not None: SETTINGS['dedupe_default'] = body.dedupe_default; changed.append('dedupe_default')
    if body.api_key is not None: SETTINGS['api_key'] = body.api_key.strip(); changed.append('api_key')
    if body.platform_defaults is not None:
        SETTINGS['platform_defaults'] = {k: max(1, min(int(v), SETTINGS['max_limit_per_source']))
                                         for k, v in body.platform_defaults.items() if k in PLATFORM_MAP}
        changed.append('platform_defaults')
    if body.kuwo_vip_cookie is not None:
        SETTINGS['kuwo_vip_cookie'] = body.kuwo_vip_cookie.strip(); changed.append('kuwo_vip_cookie')
    if body.platform_subsources is not None:
        clean_subs = {}
        for pid, subs in (body.platform_subsources or {}).items():
            meta = PLATFORM_MAP.get(pid)
            if not meta or not meta.get('subsources'): continue
            valid = [x['id'] for x in meta['subsources']]
            clean_subs[pid] = [s for s in subs if s in valid] or valid
        SETTINGS['platform_subsources'] = clean_subs; changed.append('platform_subsources')
    if changed: save_config(SETTINGS)
    return {'code': 200, 'msg': f'updated: {", ".join(changed) or "nothing"}', 'data': {'changed': changed}}


@app.post('/api/search')
async def search(body: SearchBody):
    unknown = [s for s in body.sources if s not in PLATFORM_MAP]
    if unknown: return JSONResponse({'code': 404, 'msg': f'未知平台: {unknown}'}, status_code=200)
    keyword = body.keyword.strip()
    loop = asyncio.get_running_loop()

    async def run_one(pid: str, limit: int):
        try:
            infos = await asyncio.wait_for(loop.run_in_executor(None, search_platform_sync, pid, keyword, int(limit)),
                                           timeout=int(SETTINGS['search_timeout_s']))
            return pid, infos, None
        except Exception as err:
            return pid, [], f'{type(err).__name__}: {str(err)[:160]}'

    outcomes = await asyncio.gather(*[run_one(pid, limit) for pid, limit in body.sources.items()])
    results, failed, new_store = [], {}, {}
    for pid, infos, error in outcomes:
        if error: failed[pid] = error
        for info in infos:
            key = f'{pid}:{uuid.uuid4().hex[:8]}'
            entry = serialize_item(key, info, pid)
            results.append(entry)
            if entry['has_url']: new_store[key] = info
    with STORE_LOCK:
        if len(RESULT_STORE) > 800: RESULT_STORE.clear()   # simple capacity cap
        RESULT_STORE.update(new_store)
    results.sort(key=lambda r: (not r['has_url'], QUALITY_ORDER.get(r['quality_tier'], 9)))
    return {'code': 200, 'msg': 'ok', 'data': {'keyword': keyword, 'total': len(results), 'items': results, 'failed': failed}}


@app.get('/api/search/stream')
async def search_stream(request: Request, keyword: str = Query(..., min_length=1), sources: str = Query(...)):
    '''progressive search: one SSE event per finished platform so the UI can show live progress.'''
    async def event_stream():
        try:
            src_map = {k: int(v) for k, v in json.loads(sources).items() if k in PLATFORM_MAP and int(v) >= 1}
        except Exception:
            yield f'data: {json.dumps({"type": "done", "total": 0, "failed": {"_": "sources 参数非法"}}, ensure_ascii=False)}\n\n'; return
        if not src_map:
            yield f'data: {json.dumps({"type": "done", "total": 0, "failed": {"_": "无有效平台"}}, ensure_ascii=False)}\n\n'; return
        loop = asyncio.get_running_loop()

        async def run_one(pid: str, limit: int):
            try:
                infos = await asyncio.wait_for(loop.run_in_executor(None, search_platform_sync, pid, keyword.strip(), int(limit)),
                                               timeout=int(SETTINGS['search_timeout_s']))
                return pid, infos, None
            except Exception as err:
                return pid, [], f'{type(err).__name__}: {str(err)[:160]}'

        total_sent, failed_all = 0, {}
        coros = [run_one(pid, limit) for pid, limit in src_map.items()]
        for coro in asyncio.as_completed(coros):
            pid, infos, error = await coro
            entries = []
            for info in infos:
                key = f'{pid}:{uuid.uuid4().hex[:8]}'
                entry = serialize_item(key, info, pid)
                entries.append(entry)
                if entry['has_url']:
                    with STORE_LOCK:
                        if len(RESULT_STORE) > 800: RESULT_STORE.clear()
                        RESULT_STORE[key] = info
            total_sent += len(entries)
            if error: failed_all[pid] = error
            payload = {'type': 'source_done', 'source': pid, 'count': len(entries),
                       'failed': error, 'items': entries}
            yield f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'
        yield f'data: {json.dumps({"type": "done", "total": total_sent, "failed": failed_all}, ensure_ascii=False)}\n\n'

    return StreamingResponse(event_stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/downloads')
async def create_download(body: DownloadBody):
    if body.quality_pref not in QUALITY_PREF_RANKS:
        return JSONResponse({'code': 400, 'msg': f'quality_pref 必须是 {list(QUALITY_PREF_RANKS)} 之一'}, status_code=200)
    try:
        snapshot = engine.create_task(body.keys, body.quality_pref, bool(body.dedupe))
    except KeyError as err:
        return JSONResponse({'code': 410, 'msg': str(err)}, status_code=200)
    except Exception as err:
        return JSONResponse({'code': 500, 'msg': f'{type(err).__name__}: {err}'}, status_code=500)
    return {'code': 200, 'msg': 'ok', 'data': snapshot}


@app.get('/api/tasks')
async def list_tasks(): return {'code': 200, 'msg': 'ok', 'data': engine.list_tasks()}


@app.get('/api/tasks/{task_id}')
async def get_task(task_id: str):
    try: return {'code': 200, 'msg': 'ok', 'data': engine.snapshot(task_id)}
    except KeyError: return JSONResponse({'code': 404, 'msg': 'task not found'}, status_code=200)


@app.post('/api/tasks/{task_id}/retry')
async def retry_item(task_id: str, body: RetryBody):
    try: return {'code': 200, 'msg': 'ok', 'data': engine.retry_item(task_id, body.item_id)}
    except (KeyError, ValueError, RuntimeError) as err:
        return JSONResponse({'code': 400, 'msg': str(err)}, status_code=200)


@app.delete('/api/tasks/{task_id}')
async def cancel_task(task_id: str):
    try: return {'code': 200, 'msg': 'ok', 'data': engine.cancel_task(task_id)}
    except KeyError: return JSONResponse({'code': 404, 'msg': 'task not found'}, status_code=200)


@app.get('/api/tasks/{task_id}/events')
async def task_events(task_id: str, request: Request):
    async def event_stream():
        ticks_after_done = 0
        while True:
            if await request.is_disconnected(): break
            try: snap = engine.snapshot(task_id)
            except KeyError:
                yield f'event: gone\ndata: {json.dumps({"task_id": task_id})}\n\n'; break
            yield f'data: {json.dumps(snap, ensure_ascii=False)}\n\n'
            if snap['status'] in {'completed', 'partial', 'cancelled'}:
                ticks_after_done += 1
                if ticks_after_done >= 3: break
            await asyncio.sleep(0.6)
    return StreamingResponse(event_stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


STATIC_DIR = MODULE_DIR / 'static'


@app.get('/')
async def index(): return FileResponse(STATIC_DIR / 'index.html')


def main():
    parser = argparse.ArgumentParser(description='musicdl-webgui server')
    parser.add_argument('--host', default=SETTINGS['host'])
    parser.add_argument('--port', type=int, default=int(SETTINGS['port']))
    parser.add_argument('--download-dir', default=None, help='override & persist download directory')
    args = parser.parse_args()
    if args.download_dir:
        SETTINGS['download_dir'] = args.download_dir; touch_download_dir(); save_config(SETTINGS)
    print('=' * 64)
    print(f'musicdl-webgui   http://{args.host}:{args.port}')
    print(f'download dir  : {SETTINGS["download_dir"]}')
    print(f'naming        : {SETTINGS["naming_template"]}.<ext>')
    print(f'platforms     : {", ".join(p["name"] for p in PLATFORMS)}')
    print(f'lrc sidecar   : {"on" if SETTINGS["save_lrc_sidecar"] else "off (lyrics embedded)"}')
    print('=' * 64)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
