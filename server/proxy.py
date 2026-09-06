'''
Function:
    Generic passthrough to the sibling kugou-api / ncm-api containers.
    - injects each container's account cookie automatically
    - blocks account-dangerous paths (logout/captcha/sms/register...)
    - streams upstream bytes verbatim (no re-parse) — overhead ~1ms
'''
import urllib.request
import urllib.parse
import urllib.error
import gzip

from .config import settings

PROXY_CFG = {
    'kugou': {
        'base': settings.kugou_api_base,
        'blocked': ('logout', 'captcha', 'sms', 'register', 'setcookie', 'cellphone', 'user/update'),
        'kugou_cookie': True,
        'netease_cookie': False,
    },
    'netease': {
        'base': settings.ncm_api_base,
        'blocked': ('logout', 'captcha', 'sms', 'register', 'setcookie', 'cellphone'),
        'kugou_cookie': False,
        'netease_cookie': True,
    },
}


def blocked_segment(source: str, path: str):
    low = (path or '').lower()
    for b in PROXY_CFG[source]['blocked']:
        if b in low:
            return b
    return None


def fetch(source: str, method: str, path: str, query: dict = None,
          body: bytes = None, content_type: str = 'application/json',
          kugou_cookie_fn=None, timeout: int = 30,
          netease_cookie: str = '') -> tuple:
    '''returns (upstream_status, content_type, body_bytes) verbatim.
       Never raises on HTTP errors — upstream 4xx/5xx are passed through.'''
    bad = blocked_segment(source, path)
    if bad:
        return 403, 'application/json', f'{{"code":403,"msg":"blocked path segment: {bad}"}}'.encode()
    cfg = PROXY_CFG[source]
    qs = urllib.parse.urlencode(query or {})
    url = f"{cfg['base']}/{path.lstrip('/')}" + (f'?{qs}' if qs else '')
    headers = {'Accept-Encoding': 'gzip', 'User-Agent': 'kwqq-api-proxy'}
    data = None
    if method == 'POST':
        data = body or b''
        headers['Content-Type'] = content_type
    if cfg['kugou_cookie'] and kugou_cookie_fn:
        sep = '&' if '?' in url else '?'
        url += f"{sep}cookie={urllib.parse.quote(kugou_cookie_fn())}"
    elif cfg['netease_cookie'] and (netease_cookie or settings.netease_cookie):
        mu = netease_cookie or settings.netease_cookie
        sep = '&' if '?' in url else '?'
        url += f'{sep}cookie={urllib.parse.quote(mu)}'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.GzipFile(fileobj=_io.BytesIO(raw)).read()
            return resp.status, resp.headers.get('Content-Type', 'application/json'), raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        if e.headers.get('Content-Encoding') == 'gzip':
            try: raw = gzip.GzipFile(fileobj=_io.BytesIO(raw)).read()
            except Exception: pass
        return e.code, e.headers.get('Content-Type', 'application/json'), raw
