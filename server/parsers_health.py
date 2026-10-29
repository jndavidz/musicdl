'''
Function:
    Parser health tracking with cooldown-skipping.
    Wraps each `client._parsewithXxxApi` so dead or rate-limited third-party
    endpoints are bypassed quickly instead of burning seconds on every request.
Notes:
    Cooldowns are keyed by the LOGICAL parser name ("<source>:<parser>"), never by
    host: adding a host alias, switching between internal/external entries or
    falling back to a mirror must not reset an active cooldown (upstream 429 must
    not be bypassed by host rotation). HTTP 429 keeps the upstream Retry-After and
    is never recorded as a success.
'''
import re
import time
import threading
from musicdl.modules.utils import SongInfo, AudioLinkTester


def _status_code(exc) -> int | None:
    '''best-effort HTTP status from requests.HTTPError / urllib.error.HTTPError'''
    resp = getattr(exc, 'response', None)
    code = getattr(resp, 'status_code', None) or getattr(exc, 'code', None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


_RATE_LIMIT_RE = re.compile(r'(?:HTTP|status[=: ]+)\s*429\b|\b429\s*(?:Too Many Requests|Client Error)',
                            re.I)


def is_rate_limited(exc) -> bool:
    '''HTTP 429 only; a song id / url that merely CONTAINS "429" must not cool a parser'''
    if _status_code(exc) == 429:
        return True
    return bool(_RATE_LIMIT_RE.search(str(exc)[:300]))


def retry_after_from(exc) -> float | None:
    '''upstream Retry-After (seconds); None when absent/unparseable'''
    headers = None
    resp = getattr(exc, 'response', None)
    for source in (resp, exc):
        headers = getattr(source, 'headers', None)
        if headers:
            break
    if not headers:
        return None
    try:
        raw = headers.get('Retry-After') or headers.get('retry-after')
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return max(1.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return None   # HTTP-date form: fall back to the configured cooldown


class ParserHealth:
    def __init__(self, fail_threshold: int = 3, cooldown_s: int = 300):
        self.fail_threshold = max(1, int(fail_threshold))
        self.cooldown_s = max(10, int(cooldown_s))
        self._lock = threading.Lock()
        self._stats: dict = {}

    def _entry(self, name: str) -> dict:
        return self._stats.setdefault(name, {'attempts': 0, 'ok': 0, 'fail_streak': 0,
                                             'cooled_until': 0, 'last_ms': None,
                                             'last_error': None, 'throttled': False})

    '''record one parser call outcome'''
    def record(self, name: str, ok: bool, ms: float = None, error: str = None):
        with self._lock:
            st = self._entry(name)
            st['attempts'] += 1
            st['last_ms'] = round(ms) if ms else st['last_ms']
            if ok:
                st['ok'] += 1; st['fail_streak'] = 0; st['cooled_until'] = 0; st['throttled'] = False
            else:
                st['fail_streak'] += 1
                if error: st['last_error'] = str(error)[:160]
                if st['fail_streak'] >= self.fail_threshold: st['cooled_until'] = time.monotonic() + self.cooldown_s

    '''record an upstream rate limit: cools the logical parser for Retry-After (or
       the configured cooldown) regardless of which host/alias produced it.'''
    def record_throttle(self, name: str, retry_after: float = None, error: str = 'HTTP 429'):
        wait = max(1.0, float(retry_after)) if retry_after else float(self.cooldown_s)
        with self._lock:
            st = self._entry(name)
            st['attempts'] += 1
            st['fail_streak'] += 1
            st['throttled'] = True
            st['last_error'] = str(error)[:160]
            st['cooled_until'] = max(st['cooled_until'], time.monotonic() + wait)
        return wait

    '''seconds still remaining on the logical parser's cooldown (0 = usable)'''
    def cooldown_remaining(self, name: str) -> float:
        with self._lock:
            st = self._stats.get(name)
            if not st or not st['cooled_until']:
                return 0.0
            return max(0.0, st['cooled_until'] - time.monotonic())

    '''whether parser is in cooldown (should be skipped)'''
    def is_cooled_down(self, name: str) -> bool:
        return self.cooldown_remaining(name) > 0

    '''wrap every third-party parser on the client with health checks.
       stats are keyed by "<source>:<parser>" — method names overlap across platforms.
       Clients without a third-party chain (official-only sources like migu/qianqian)
       are returned unwrapped. Discovery is dir()-reflection on the class — no source
       scraping, so upstream parser renames can't silently break the cooldown net
       (chain-disabled parsers get wrapped too but are never invoked, hence never recorded).'''
    def wrap_client(self, client):
        if not hasattr(type(client), '_parsewiththirdpartapis'):
            return client
        names = [n for n in dir(type(client))
                 if n.startswith('_parsewith') and n != '_parsewiththirdpartapis']
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
                    # 429 cools the LOGICAL parser even if only one host/alias hit it
                    if is_rate_limited(err):
                        self.record_throttle(_name, retry_after_from(err), err)
                    else:
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
                'cooldown_remaining_s': round(max(0.0, st['cooled_until'] - now)) if st['cooled_until'] else 0,
                'throttled': bool(st.get('throttled')),
                'last_error': st['last_error'],
            } for name, st in self._stats.items()}
