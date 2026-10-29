'''
Function:
    Generic passthrough to the sibling kugou-api / ncm-api containers. Covers ALL
    upstream endpoints (catalog browsing / vip ops / comments / ...); account cookie
    injected via the adapter's public account_cookie() (absent file -> anonymous);
    body streamed verbatim; blocked account-dangerous paths; API-key guarded globally.
'''
import functools as _ft
from fastapi import Request
from fastapi.responses import Response

from server import proxy

PROXY_TIMEOUT = 40
# passthrough relays share the SAME logical upstream entry points as the adapters,
# so an upstream 429 cooldown applies to them too (no bypass via /{src}/api/*)
COOLDOWN_NAME = {'kugou': 'kugou:container', 'netease': 'netease:ncm-api'}


def _make_handler(source: str, method: str):
    async def handler(request: Request, path: str):
        s = request.app.state
        adapter = s.adapters[source]
        body = await request.body() if method == 'POST' else None
        fn = _ft.partial(proxy.fetch, source=source, method=method, path=path,
                         query=dict(request.query_params),
                         body=body, content_type=request.headers.get('content-type', 'application/json'),
                         cookie_fn=adapter.account_cookie, timeout=PROXY_TIMEOUT)
        status, ctype, out = await adapter.run(adapter.guarded_sync, COOLDOWN_NAME[source], fn)
        return Response(content=out, status_code=status, media_type=ctype)
    handler.__name__ = f'{source}_proxy_{method.lower()}'
    return handler


kugou_get = _make_handler('kugou', 'GET')
kugou_post = _make_handler('kugou', 'POST')
netease_get = _make_handler('netease', 'GET')
netease_post = _make_handler('netease', 'POST')
