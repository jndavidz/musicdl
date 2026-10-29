'''
Function:
    v2 TrackRef: the stable remote-track identity contract for managed playback.
    A ref carries source + id plus only the identity-affecting extra fields
    (migu copyrightId, bilibili cid/page). Everything else in a caller's extra
    payload is dropped, so cache and singleflight keys cannot be dilated by
    non-identity noise.
Notes:
    - canonical() is the single structured encoding used as cache/singleflight
      key material (sorted keys, no whitespace, stable field order).
    - missing identity fields are a client error (RefError), never resolved as
      "best effort": a bare bvid or a migu id without copyrightId is ambiguous.
    - v1 routes keep their own (source,id,quality,copyright) keys untouched.
'''
import json
import hashlib

PROVIDER = 'kwqq'

'''extra fields that change which media a ref denotes, per source'''
IDENTITY_FIELDS = {
    'migu': ('copyrightId',),
    'bilibili': ('cid', 'page'),
}

'''sources whose identity needs at least one of these extra fields'''
REQUIRED_EXTRA = {
    'migu': ('copyrightId',),
    'bilibili': ('cid', 'page'),
}


class RefError(ValueError):
    '''malformed / incomplete TrackRef — maps to 400 invalid_request'''


def _as_cid(value) -> str:
    cid = str(value if value is not None else '').strip()
    if not cid.isdigit() or int(cid) <= 0:
        raise RefError(f'bilibili extra.cid must be a positive numeric cid, got {value!r}')
    return cid


def _as_page(value) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        raise RefError(f'bilibili extra.page must be an integer page number, got {value!r}')
    if page < 1:
        raise RefError(f'bilibili extra.page must be >= 1, got {page}')
    return page


def _normalize_extra(source: str, extra: dict) -> dict:
    extra = dict(extra or {})
    out = {}
    for field in IDENTITY_FIELDS.get(source, ()):
        value = extra.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if field == 'cid':
            out['cid'] = _as_cid(value)
        elif field == 'page':
            out['page'] = _as_page(value)
        else:
            out[field] = str(value).strip()
    return out


def make_ref(source: str, track_id, extra: dict = None, sources=()) -> dict:
    '''build a validated TrackRef; unknown sources are rejected by the caller's
       registry check, `sources` (when given) enforces it here too.'''
    source = str(source or '').strip()
    if not source:
        raise RefError('track_ref.source is required')
    if sources and source not in sources:
        raise RefError(f'unknown source "{source}" (available: {", ".join(sources)})')
    track_id = str(track_id if track_id is not None else '').strip()
    if not track_id:
        raise RefError('track_ref.id is required')
    norm_extra = _normalize_extra(source, extra or {})
    required = REQUIRED_EXTRA.get(source, ())
    if required and not any(f in norm_extra for f in required):
        if len(required) == 1:
            raise RefError(f'{source} track_ref requires extra.{required[0]}')
        raise RefError(f'{source} track_ref requires extra.{" or extra.".join(required)}')
    return {'kind': 'remote', 'provider': PROVIDER, 'source': source,
            'id': track_id, 'extra': norm_extra}


def canonical(ref: dict) -> str:
    '''stable structured encoding; key order in `extra` never changes the result'''
    payload = {'provider': ref.get('provider') or PROVIDER,
               'kind': ref.get('kind') or 'remote',
               'source': ref['source'], 'id': ref['id'],
               'extra': {k: ref['extra'][k] for k in sorted(ref.get('extra') or {})}}
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(ref: dict) -> str:
    return hashlib.sha256(canonical(ref).encode('utf-8')).hexdigest()[:32]


def canonical_policy(profile: dict) -> str:
    '''playback policy part of the cache key (quality + target profile)'''
    payload = {'quality': str((profile or {}).get('quality') or 'auto').strip().lower(),
               'target': str((profile or {}).get('target') or 'device').strip().lower()}
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def cache_key(ref: dict, profile: dict, credential_generation: int) -> str:
    '''identity + playback policy + credential generation; v2 namespace only'''
    return f'v2:{digest(ref)}:{hashlib.sha256(canonical_policy(profile).encode()).hexdigest()[:16]}:cred{int(credential_generation)}'
