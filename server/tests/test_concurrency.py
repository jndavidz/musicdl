'''offline tests for the real concurrency boundary (K-03), no upstream needed.
   Proves:
     - a caller timeout returns control but capacity stays occupied until the
       worker thread really exits (thread peak stays at max_workers);
     - the bounded waiter bucket answers 503 instead of growing;
     - a slow blocking worker does not stall the event loop;
     - late results are dropped (never delivered);
     - the v1 HTTP contract still answers 504 and never caches a timed-out result.
   Run: XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_concurrency.py'''
import asyncio
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from server.config import Settings
from server.app import create_app
from server.adapters.base import SourceAdapter, AdapterError
from server.parsers_health import ParserHealth

PASSED, FAILED = 0, []


def check(name, cond, detail=''):
    global PASSED
    print(f'  {"PASS" if cond else "FAIL"} {name} {detail}')
    if cond: PASSED += 1
    else: FAILED.append(name)


class DummyClient:
    '''no third-party parser methods -> ParserHealth.wrap_client returns it as-is'''


class TestAdapter(SourceAdapter):
    source_key = 'test'

    def _build_client(self):
        return DummyClient()


def build(workers=1, waiters=1):
    st = Settings(env={'MAX_CONCURRENCY': str(workers), 'MAX_WAITERS': str(waiters),
                       'HARD_TIMEOUT_S': '5', 'IO_TIMEOUT_S': '5'})
    return TestAdapter(st, ParserHealth())


class ThreadProbe:
    '''counts live worker threads and the observed peak'''

    def __init__(self):
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self):
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)

    def leave(self):
        with self.lock:
            self.current -= 1


print('== concurrency boundary offline ==')

# ---- A: timeout does not free capacity until the worker really exits ----
print('[A] capacity held past a caller timeout')


async def case_capacity():
    adapter = build(workers=1, waiters=2)
    probe, entered, release = ThreadProbe(), threading.Event(), threading.Event()

    def blocked():
        probe.enter(); entered.set()
        release.wait(10)
        probe.leave()
        return 'late-result'

    task = asyncio.create_task(adapter.run_with_timeout(blocked, 0.2))
    await asyncio.sleep(0.05)
    timed_out = False
    try:
        await task
    except asyncio.TimeoutError:
        timed_out = True
    after_timeout = adapter.runtime_stats()

    started2 = threading.Event()

    def quick():
        started2.set()
        return 'ok'

    task2 = asyncio.create_task(adapter.run_with_timeout(quick, 3))
    await asyncio.sleep(0.25)
    second_waited = not started2.is_set()
    release.set()
    result2 = await asyncio.wait_for(task2, timeout=5)
    await asyncio.sleep(0.05)
    final = adapter.runtime_stats()
    adapter.shutdown()
    return timed_out, after_timeout, second_waited, probe, result2, final


timed_out, after, second_waited, probe, result2, final = asyncio.run(case_capacity())
check('caller timed out', timed_out)
check('capacity still occupied after the timeout (active=1)', after['active'] == 1, f"active={after['active']}")
check('second job did not start while the old thread was alive', second_waited)
check('thread peak stays at max_workers=1', probe.peak == 1, f'peak={probe.peak}')
check('second job completes once the worker exits', result2 == 'ok')
check('late result is dropped, not delivered', final['late_dropped'] == 1 and final['active'] == 0,
      f"late={final['late_dropped']} active={final['active']}")

# ---- B: bounded waiter bucket -> 503 ----
print('[B] bounded waiter bucket')


async def case_waiters():
    adapter = build(workers=1, waiters=1)
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set(); release.wait(10); return 'late'

    t1 = asyncio.create_task(adapter.run_with_timeout(blocked, 5))
    await asyncio.sleep(0.1)
    t2 = asyncio.create_task(adapter.run_with_timeout(lambda: 'never', 5))
    await asyncio.sleep(0.1)
    over = None
    try:
        await adapter.run_with_timeout(lambda: 'x', 5)
    except AdapterError as err:
        over = err
    stats = adapter.runtime_stats()
    release.set()
    await asyncio.wait_for(t1, timeout=5)
    await asyncio.wait_for(t2, timeout=5)
    adapter.shutdown()
    return over, stats


over, stats = asyncio.run(case_waiters())
check('over-full queue answers 503 capacity', over is not None and over.code == 503,
      f'code={getattr(over, "code", None)}')
check('waiting counted, never above the static bound', stats['waiting'] == 1 and stats['max_waiters'] == 1,
      f"waiting={stats['waiting']}")

# ---- C: a slow blocking worker does not stall the event loop ----
print('[C] slow blocking work leaves the loop responsive')


async def case_loop():
    adapter = build(workers=2, waiters=2)
    ticks = 0
    task = asyncio.create_task(adapter.run_with_timeout(lambda: time.sleep(0.5) or 'slow', 3))
    while not task.done():
        ticks += 1
        await asyncio.sleep(0.05)
    await task
    adapter.shutdown()
    return ticks


ticks = asyncio.run(case_loop())
check('event loop kept ticking during a 0.5s blocking worker', ticks >= 5, f'ticks={ticks}')

# ---- D: HTTP seam keeps the 504 contract and never caches a timed-out resolve ----
print('[D] v1 HTTP contract on timeout')


def _free_port() -> int:
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close(); return port


def start_app(app):
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    base = f'http://127.0.0.1:{port}'
    for _ in range(50):
        try:
            urllib.request.urlopen(base + '/healthz', timeout=1)
            return base, server
        except Exception:
            time.sleep(0.2)
    raise RuntimeError('app did not start')


class SlowAdapter:
    source_key = 'qq'

    def __init__(self):
        self.calls = 0
        self.release = threading.Event()

    async def song_url(self, song_id, quality, **kw):
        self.calls += 1
        if not self.release.is_set():
            await asyncio.Event().wait()      # hangs until the route budget expires
        return {'id': song_id, 'source': self.source_key, 'quality': quality,
                'url': 'http://example.test/a.mp3', 'ext': 'mp3', 'size_bytes': 1000,
                'bitrate_kbps': 320, 'duration_s': 180, 'cover': None, 'verified': True,
                'headers': {}, 'parser': 'fake', 'elapsed_ms': 1, 'cached': False}


def raw(base, path, timeout=10):
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {}


app = create_app(Settings(env={'API_KEY': '', 'HARD_TIMEOUT_S': '0.4', 'RATE_LIMIT': '',
                              'TRUSTED_NETWORKS': '127.0.0.0/8'}))
base, server = start_app(app)
slow = SlowAdapter()
app.state.adapters['qq'] = slow

st, body = raw(base, '/qq/song/url?id=s1')
check('v1 timeout -> HTTP 504 envelope', st == 504 and body.get('code') == 504, f'status={st} code={body.get("code")}')
slow.release.set()
st, body = raw(base, '/qq/song/url?id=s1')
check('timed-out resolve was not cached (adapter re-called)', slow.calls == 2, f'calls={slow.calls}')
check('follow-up resolve succeeds normally', st == 200 and (body.get('data') or {}).get('url'))
st, body = raw(base, '/status')
runtime = (body.get('data') or {}).get('runtime') or {}
rt = next(iter(runtime.values()), {}) if runtime else {}
check('status exposes per-source runtime counters',
      {'active', 'waiting', 'max_workers', 'max_waiters', 'timed_out', 'late_dropped'} <= set(rt),
      f'sources={sorted(runtime)} keys={sorted(rt)}')
server.should_exit = True

print(f'\nRESULT: {PASSED} passed, {len(FAILED)} failed' + (f' -> {FAILED}' if FAILED else ''))
sys.exit(1 if FAILED else 0)
