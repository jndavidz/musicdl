'''
Function:
    Minimal thread-safe TTL cache (process-local, no external deps)
'''
import itertools
import time
import threading

from server.singleflight import SingleFlight

'''process-wide leader registry: keys are (cache.uid, cache_key) so caches that
   happen to share a textual key never merge, and a recycled id() cannot alias'''
_flight = SingleFlight()
_uid_seq = itertools.count(1)


class TTLCache:
    def __init__(self, ttl_seconds: int, max_items: int = 2048):
        self.ttl = max(1, int(ttl_seconds))
        self.max_items = max(16, int(max_items))
        self.uid = next(_uid_seq)
        self._store: dict = {}
        self._lock = threading.Lock()
        self._hits = self._misses = 0

    def get(self, key: str):
        with self._lock:
            item = self._store.get(key)
            if not item:
                self._misses += 1
                return None
            expires_at, value = item
            if expires_at < time.monotonic():
                self._store.pop(key, None); self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value):
        with self._lock:
            if len(self._store) >= self.max_items:
                # naive cleanup: drop expired first, then oldest-by-expiry half
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._store.items() if exp < now]
                for k in expired: self._store.pop(k, None)
                if len(self._store) >= self.max_items:
                    for k, _ in sorted(self._store.items(), key=lambda kv: kv[1][0])[: self.max_items // 2]:
                        self._store.pop(k, None)
            self._store[key] = (time.monotonic() + self.ttl, value)

    def delete(self, key: str) -> bool:
        '''scoped invalidation: evict one exact key (returns whether it existed)'''
        with self._lock:
            existed = self._store.pop(key, None) is not None
            if not existed: self._misses += 1
            return existed

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {'items': len(self._store), 'ttl': self.ttl,
                    'hits': self._hits, 'misses': self._misses,
                    'hit_rate': round(self._hits / total, 3) if total else None}


async def cached(cache: TTLCache, key_parts: tuple, fn) -> tuple:
    '''single cache idiom for all routes: key_parts joined by ':'; fn is the async
       resolver. Returns (value, hit). Note the store-treats-''-as-hit asymmetry is
       intentional: lyric '' is a valid cached value, hence `is not None` checks.
       Concurrent misses on the same key share ONE leader execution (singleflight);
       a failed leader stores nothing, so the next caller may retry.'''
    key = ':'.join(str(p) for p in key_parts)
    hit = cache.get(key)
    if hit is not None:
        return hit, True

    async def _compute_and_store():
        value = await fn()
        cache.set(key, value)
        return value

    value = await _flight.run((cache.uid, key), _compute_and_store)
    return value, False
