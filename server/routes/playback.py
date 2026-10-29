'''
Function:
    v2 playback resolve route: POST /v2/playback/resolve.
    Accepts only a TrackRef + play profile; requires a dedicated scoped service
    credential (playback:issue). Never accepts caller URLs, cookies or ekeys.
Notes:
    Cache keys are the structured (identity, policy, credential generation) triple
    from trackref.cache_key; v1 routes keep their own key space untouched.
    A candidate rejected by the strict profile is never stored in the cache.
'''
from fastapi import Request

from server import trackref
from server.adapters import AdapterError
from server.cache import cached
from server.envelope import ok
from server.playback import assemble
from server.playback_profile import ProfileError, classify, normalize_request
from server.routes.resolve import get_adapter
from server.schemas import InvalidateBody, PlaybackResolveBody, PlaybackResolveData
from server.scopes import CACHE_INVALIDATE, MEDIA_PREPARE, PLAYBACK_ISSUE, ScopeDenied
from server.config import SOURCES

FRESHNESS = frozenset({'allow_cache', 'revalidate'})


def _ref_from(body):
    '''shared request validation for resolve + invalidate (400 on bad identity)'''
    try:
        return trackref.make_ref(body.track_ref.source, body.track_ref.id,
                                 body.track_ref.extra, SOURCES)
    except trackref.RefError as err:
        raise AdapterError(400, str(err))


async def resolve(request: Request, body: PlaybackResolveBody):
    s = request.app.state
    grant = s.scopes.authorize(request.headers.get('x-service-token', ''), PLAYBACK_ISSUE)
    ref = _ref_from(body)
    adapter = get_adapter(s, ref['source'])
    freshness = str(body.freshness or 'allow_cache').strip()
    if freshness not in FRESHNESS:
        raise AdapterError(400, f'unknown freshness "{freshness}" (want allow_cache or revalidate)')
    try:
        prepared = normalize_request(ref['source'], body.profile.quality, body.profile.target)
    except ProfileError as err:
        raise AdapterError(err.code, err.msg)
    allow_normalize = prepared['target'] == 'media_prepare'
    if allow_normalize and not s.scopes.has_scope(grant, MEDIA_PREPARE):
        raise ScopeDenied(403, 'profile.target=media_prepare requires the "media:prepare" scope')
    profile = body.profile.model_dump()
    key = trackref.cache_key(ref, profile, grant['generation'])

    async def _resolve():
        kwargs = adapter.identity_kwargs(ref['extra'])
        result = await adapter.song_url(ref['id'], prepared['tier'], **kwargs)
        try:
            verdict = classify(result, prepared, allow_normalize_input=allow_normalize)
        except ProfileError as err:
            raise AdapterError(err.code, f'{ref["source"]}: {err.msg}')
        out_ref = {**ref, 'extra': adapter.identity_out(ref['extra'], result)}
        return assemble(out_ref, result, prepared, verdict,
                        cache_ttl_s=s.settings.url_cache_ttl)

    # revalidate = exactly ONE controlled re-resolution (singleflight coalesces
    # concurrent ones); the end-to-end retry budget belongs to the outermost
    # command, so kwqq never stacks its own retry rounds on top.
    if freshness == 'revalidate':
        # drop the stale entry first, then resolve through cached() so concurrent
        # revalidations coalesce and later allow_cache callers see the fresh value
        s.v2_url_cache.delete(key)
        data, _ = await cached(s.v2_url_cache, (key,), _resolve)
    else:
        data, hit = await cached(s.v2_url_cache, (key,), _resolve)
        data = {**data, 'cached': hit}
    return ok(PlaybackResolveData(**data).model_dump())


async def invalidate(request: Request, body: InvalidateBody):
    '''evict the cached candidate for ONE identity+policy under the caller's own
       credential generation. Cross-scope tokens are rejected; no wildcards.'''
    s = request.app.state
    grant = s.scopes.authorize(request.headers.get('x-service-token', ''), CACHE_INVALIDATE)
    ref = _ref_from(body)
    profile = body.profile.model_dump()
    key = trackref.cache_key(ref, profile, grant['generation'])
    removed = s.v2_url_cache.delete(key)
    return ok({'invalidated': removed, 'identity_digest': trackref.digest(ref),
               'generation': grant['generation'], 'profile': profile})
