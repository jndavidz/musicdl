'''
Function:
    Process-local async singleflight: concurrent callers on the same structured
    key share ONE leader execution.
Notes:
    - waiters await the leader through asyncio.shield, so cancelling one waiter
      never cancels the work other legitimate waiters are still waiting for;
    - the key is removed in the leader's finally: a failed leader leaves no
      negative cache and the next caller can retry within its own budget;
    - the leader is a separate task, so a caller timeout/disconnect does not
      abort the shared work either.
'''
import asyncio


class SingleFlight:
    def __init__(self):
        self._inflight: dict = {}

    @property
    def inflight(self) -> int:
        return len(self._inflight)

    async def run(self, key, fn):
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._leader(key, fn))
            self._inflight[key] = task
        return await asyncio.shield(task)

    async def _leader(self, key, fn):
        try:
            return await fn()
        finally:
            # only pop when we are still the registered leader (a newer leader can
            # never coexist: pop happens before a new run() can install one)
            if self._inflight.get(key) is asyncio.current_task():
                self._inflight.pop(key, None)
