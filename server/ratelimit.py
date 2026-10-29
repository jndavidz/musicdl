'''
Function:
    Fixed-window rate limiter for untrusted clients only. Requests from
    TRUSTED_NETWORKS (same check as auth.py) pass through untouched; everything
    else shares one bucket keyed by client IP. 429 responses carry
    X-RateLimit-Limit / -Remaining / -Reset and Retry-After headers.
Notes:
    Hand-rolled instead of SlowAPI (roadmap C2 naming deviation): slowapi/limits
    cannot express the trusted-network exemption that defines this requirement,
    and the NAS host is too weak to want the extra dependency chain. Consistency
    of the in-process window relies on workers=1 (same as the TTL caches).
    RATE_LIMIT format "N/period" (period: second|minute|hour|day); empty = disabled.
'''
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from server.auth import from_trusted_lan
from server.envelope import envelope

_PERIODS = {'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400}
EXEMPT_PATHS = {'/healthz', '/metrics'}


def parse_rate(raw: str):
    '''"N/period" -> (count, window_seconds); empty -> None; malformed -> ValueError'''
    raw = (raw or '').strip().lower()
    if not raw:
        return None
    count_s, _, period = raw.partition('/')
    count = int(count_s)
    window = _PERIODS.get((period or 'minute').strip())
    if window is None or count <= 0:
        raise ValueError(f'malformed RATE_LIMIT {raw!r} (want e.g. "120/minute")')
    return count, window


class _FixedWindow:
    def __init__(self, count: int, window_s: int):
        self.count, self.window = count, window_s
        self._lock = threading.Lock()
        self._buckets: dict = {}

    def take(self, key: str):
        '''returns (allowed, remaining, reset_epoch)'''
        now = time.time()
        with self._lock:
            start, used = self._buckets.get(key, (now, 0))
            if now - start >= self.window:
                start, used = now, 0
            used += 1
            self._buckets[key] = (start, used)
            if len(self._buckets) > 4096:  # bound memory against source-IP spoofing
                cutoff = now - self.window
                self._buckets = {k: v for k, v in self._buckets.items() if v[0] > cutoff} or {key: (start, used)}
        reset = start + self.window
        return used <= self.count, self.count - used, reset


def install_ratelimit(app, st) -> None:
    parsed = parse_rate(st.rate_limit)
    if not parsed:
        return
    limiter = _FixedWindow(*parsed)

    @app.middleware('http')
    async def rate_limit_guard(request: Request, call_next):
        client_host = request.client.host if request.client else ''
        if request.url.path in EXEMPT_PATHS or not client_host or from_trusted_lan(st, client_host):
            return await call_next(request)
        allowed, remaining, reset = limiter.take(client_host)
        if not allowed:
            retry_after = max(1, int(reset - time.time()))
            resp = JSONResponse(envelope(429, 'rate limit exceeded, slow down', None), status_code=429)
            resp.headers.update({
                'Retry-After': str(retry_after),
                'X-RateLimit-Scope': 'local',   # distinct from upstream 429 (X-RateLimit-Scope: upstream)
                'X-RateLimit-Limit': str(limiter.count),
                'X-RateLimit-Remaining': '0',
                'X-RateLimit-Reset': str(int(reset)),
            })
            return resp
        response = await call_next(request)
        response.headers.setdefault('X-RateLimit-Limit', str(limiter.count))
        response.headers.setdefault('X-RateLimit-Remaining', str(max(0, remaining)))
        response.headers.setdefault('X-RateLimit-Reset', str(int(reset)))
        return response
