'''
Function:
    Kugou concept-VIP ops — semantic endpoints over the generic passthrough.
'''
import json as _json
import time
from datetime import datetime, timezone, timedelta as _td
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from server import proxy
from server.envelope import ok

PROXY_TIMEOUT = 40


def _shanghai_today() -> str:
    return datetime.now(timezone(_td(hours=8))).strftime('%Y-%m-%d')


def _vip_result(raw_status_body: bytes) -> Response:
    d = _json.loads(raw_status_body.decode('utf-8', errors='ignore'))
    code, err_msg = d.get('error_code'), d.get('error_msg', '')
    if d.get('status') == 1:
        return ok({'success': True, 'data': d.get('data'), 'raw_code': code})
    semantic = {131001: 'already claimed today', 297002: 'upgrade reward already claimed'}.get(code)
    return JSONResponse({'code': 200 if semantic else 500, 'msg': semantic or err_msg or f'error_code {code}',
                         'data': {'success': bool(semantic), 'error_code': code},
                         'timestamp': int(time.time() * 1000)},
                        status_code=200)


async def vip_day(request: Request):
    s = request.app.state
    day = _shanghai_today()
    status, ctype, raw = await s.adapters['kugou'].run(
        lambda: proxy.fetch('kugou', 'GET', 'youth/day/vip', {'receive_day': day},
                            cookie_fn=s.adapters['kugou'].account_cookie, timeout=PROXY_TIMEOUT))
    return _vip_result(raw)


async def vip_upgrade(request: Request):
    s = request.app.state
    status, ctype, raw = await s.adapters['kugou'].run(
        lambda: proxy.fetch('kugou', 'GET', 'youth/day/vip/upgrade',
                            cookie_fn=s.adapters['kugou'].account_cookie, timeout=PROXY_TIMEOUT))
    return _vip_result(raw)


async def vip_status(request: Request):
    s = request.app.state

    def _fetch(path):
        return proxy.fetch('kugou', 'GET', path,
                           cookie_fn=s.adapters['kugou'].account_cookie, timeout=PROXY_TIMEOUT)

    _, _, union_raw = await s.adapters['kugou'].run(_fetch, 'youth/union/vip')
    _, _, rec_raw = await s.adapters['kugou'].run(_fetch, 'youth/month/vip/record')

    def _load(raw):
        try:
            d = _json.loads(raw.decode('utf-8', errors='ignore'))
            return d.get('data') if isinstance(d.get('data'), dict) else {}
        except Exception:
            return {}

    union, record = _load(union_raw), _load(rec_raw)

    def _busi(product_type):
        for item in (union.get('busi_vip') or []):
            if isinstance(item, dict) and item.get('product_type') == product_type:
                return {'is_vip': bool(item.get('is_vip')), 'begin': item.get('vip_begin_time'),
                        'end': item.get('vip_end_time')}
        return {'is_vip': False, 'begin': None, 'end': None}

    claims = [{'day': r.get('day'), 'vip_type': r.get('vip_type')} for r in (record.get('list') or []) if isinstance(r, dict)]
    return ok({
        'svip_concept': _busi('svip'),          # 概念版 VIP
        'tvip_listening': _busi('tvip'),        # 畅听 VIP
        'claimed_days_this_month': len(claims),
        'claim_records': claims,
        'month': record.get('month'),
        'future_duration': record.get('future_duration'),
        'raw': {'union': union, 'record': record},
    })
