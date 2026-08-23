'''
Function:
    Minimal thread-safe TTL cache (process-local, no external deps)
'''
import time
import threading


class TTLCache:
    def __init__(self, ttl_seconds: int, max_items: int = 2048):
        self.ttl = max(1, int(ttl_seconds))
        self.max_items = max(16, int(max_items))
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            item = self._store.get(key)
            if not item: return None
            expires_at, value = item
            if expires_at < time.monotonic():
                self._store.pop(key, None); return None
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

    def stats(self) -> dict:
        with self._lock:
            return {'items': len(self._store), 'ttl': self.ttl}
