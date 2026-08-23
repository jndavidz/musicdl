'''
Function:
    Parser health tracking with cooldown-skipping.
    Wraps each `client._parsewithXxxApi` so dead third-party endpoints are
    bypassed quickly instead of burning seconds on every request.
'''
import re
import time
import inspect
import threading
from musicdl.modules.utils import SongInfo, AudioLinkTester


class ParserHealth:
    def __init__(self, fail_threshold: int = 3, cooldown_s: int = 300):
        self.fail_threshold = max(1, int(fail_threshold))
        self.cooldown_s = max(10, int(cooldown_s))
        self._lock = threading.Lock()
        self._stats: dict = {}

    '''record one parser call outcome'''
    def record(self, name: str, ok: bool, ms: float = None, error: str = None):
        with self._lock:
            st = self._stats.setdefault(name, {'attempts': 0, 'ok': 0, 'fail_streak': 0, 'cooled_until': 0, 'last_ms': None, 'last_error': None})
            st['attempts'] += 1
            st['last_ms'] = round(ms) if ms else st['last_ms']
            if ok:
                st['ok'] += 1; st['fail_streak'] = 0; st['cooled_until'] = 0
            else:
                st['fail_streak'] += 1
                if error: st['last_error'] = str(error)[:160]
                if st['fail_streak'] >= self.fail_threshold: st['cooled_until'] = time.monotonic() + self.cooldown_s

    '''whether parser is in cooldown (should be skipped)'''
    def is_cooled_down(self, name: str) -> bool:
        with self._lock:
            st = self._stats.get(name)
            return bool(st and st['cooled_until'] and st['cooled_until'] > time.monotonic())

    '''wrap every third-party parser on the client with health checks.
       stats are keyed by "<source>:<parser>" — method names overlap across platforms.'''
    def wrap_client(self, client):
        chain_src = inspect.getsource(type(client)._parsewiththirdpartapis)
        names = []
        for m in re.finditer(r'self\.(_parsewith\w+)', chain_src):
            if m.group(1) not in names: names.append(m.group(1))
        prefix = f'{client.source}:'
        for name in names:
            if getattr(getattr(client, name), '_health_wrapped', False): continue
            orig = getattr(client, name)
            def wrapped(search_result, request_overrides=None, _name=prefix + name, _orig=orig):
                if self.is_cooled_down(_name): return SongInfo(source=client.source)
                t0 = time.perf_counter()
                try:
                    result = _orig(search_result, request_overrides)
                    ok = bool(result.with_valid_download_url and result.ext in AudioLinkTester.VALID_AUDIO_EXTS)
                    self.record(_name, ok, (time.perf_counter() - t0) * 1000)
                    return result
                except Exception as err:
                    self.record(_name, False, (time.perf_counter() - t0) * 1000, err)
                    raise
            wrapped._health_wrapped = True
            setattr(client, name, wrapped)
        return client

    '''snapshot for /status'''
    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {name: {
                'attempts': st['attempts'], 'ok': st['ok'],
                'success_rate': round(st['ok'] / st['attempts'], 3) if st['attempts'] else None,
                'fail_streak': st['fail_streak'], 'last_ms': st['last_ms'],
                'cooled_down': bool(st['cooled_until'] and st['cooled_until'] > now),
                'last_error': st['last_error'],
            } for name, st in self._stats.items()}
