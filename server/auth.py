'''
Function:
    Service-level API key guard. Lucky's per-sub-rule Basic Auth only challenges the
    exact `/` path, so functional paths need their own protection when exposed.
    Disabled when API_KEY is empty. Requests from trusted LAN networks bypass the
    check (direct intranet access needs no key); the Lucky router IP is explicitly
    untrusted because it relays all external traffic.
'''
from fastapi import Request
from fastapi.responses import JSONResponse


def install_auth(app, st) -> None:
    if not st.api_key:
        return
    import base64 as _b64
    import ipaddress as _ip

    def _from_trusted_lan(client_host: str) -> bool:
        if client_host in st.untrusted_hosts: return False
        try:
            addr = _ip.ip_address(client_host.split('%')[0])
        except Exception:
            return False
        return any(addr in net for net in st.trusted_networks)

    @app.middleware('http')
    async def api_key_guard(request: Request, call_next):
        client_host = request.client.host if request.client else ''
        if request.url.path != '/healthz' and not _from_trusted_lan(client_host):
            provided = request.headers.get('x-api-key', '')
            if not provided:
                auth = request.headers.get('authorization', '')
                if auth.startswith('Basic '):
                    try: provided = _b64.b64decode(auth[6:]).decode('utf-8', errors='ignore').split(':', 1)[0]
                    except Exception: provided = ''
            if provided != request.app.state.settings.api_key:
                return JSONResponse({'code': 401, 'msg': 'unauthorized: missing or invalid API key', 'data': None},
                                    status_code=401, headers={'WWW-Authenticate': 'Basic realm="Authorization Required"'})
        return await call_next(request)
