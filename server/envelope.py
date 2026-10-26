'''
Function:
    Unified response envelope: {"code", "msg", "data", "timestamp"}.
    Business miss = HTTP 200 + code 403/404; upstream fault = real 502/504 status
    (contract: docs/API-REFERENCE.md).
'''
import time
from fastapi.responses import JSONResponse


def envelope(code: int, msg: str, data) -> dict:
    return {'code': code, 'msg': msg, 'data': data, 'timestamp': int(time.time() * 1000)}


def ok(data) -> dict:
    return envelope(200, 'success', data)


def err(code: int, msg: str) -> JSONResponse:
    return JSONResponse(envelope(code, msg, None), status_code=200 if code in {403, 404} else code)
