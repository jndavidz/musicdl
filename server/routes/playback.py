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
from server.schemas import PlaybackResolveBody, PlaybackResolveData
from server.scopes import MEDIA_PREPARE, PLAYBACK_ISSUE, ScopeDenied
from server.config import SOURCES


async def resolve(request: Request, body: PlaybackResolveBody):
    s = request.app.state
    grant = s.scopes.authorize(request.headers.get('x-service-token', ''), PLAYBACK_ISSUE)
    try:
        ref = trackref.make_ref(body.track_ref.source, body.track_ref.id,
                                body.track_ref.extra, SOURCES)
    except trackref.RefError as err:
        raise AdapterError(400, str(err))
    adapter = get_adapter(s, ref['source'])
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

    if str(body.freshness or 'allow_cache').strip() == 'revalidate':
        data = await _resolve()
    else:
        data, hit = await cached(s.v2_url_cache, (key,), _resolve)
        data = {**data, 'cached': hit}
    return ok(PlaybackResolveData(**data).model_dump())
