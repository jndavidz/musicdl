'''
Function:
    Scoped service credentials for the v2 playback contract.
    The legacy download API key (API_KEY) keeps its v1 reach and never implies a
    v2 scope. Callers present a dedicated service token via X-Service-Token; each
    token carries an explicit scope set and a credential generation that becomes
    part of every v2 cache key (rotating a token invalidates its cached URLs
    without touching anyone else's).
Notes:
    SERVICE_TOKENS is a JSON object: {"<token>": {"scopes": [...], "generation": N}}.
    Malformed configuration fails fast at startup (ScopeConfigError), same policy
    as TRUSTED_NETWORKS in config.py. Tokens are compared in constant time.
'''
import hmac
import json

PLAYBACK_ISSUE = 'playback:issue'
CACHE_INVALIDATE = 'cache:invalidate'
MEDIA_PREPARE = 'media:prepare'

KNOWN_SCOPES = frozenset({PLAYBACK_ISSUE, CACHE_INVALIDATE, MEDIA_PREPARE})


class ScopeConfigError(ValueError):
    '''SERVICE_TOKENS is malformed — startup must fail, not degrade silently'''


class ScopeDenied(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


class ScopeRegistry:
    def __init__(self, raw: str, download_key: str = '', default_generation: int = 1):
        self._download_key = str(download_key or '')
        self._default_generation = max(1, int(default_generation))
        self._grants: list = []   # [(token, scopes, generation)] — list keeps compare_digest scanning simple
        raw = (raw or '').strip()
        if not raw:
            return
        try:
            parsed = json.loads(raw)
        except ValueError as err:
            raise ScopeConfigError(f'SERVICE_TOKENS is not valid JSON: {err}')
        if not isinstance(parsed, dict):
            raise ScopeConfigError('SERVICE_TOKENS must be a JSON object keyed by token')
        for token, entry in parsed.items():
            if not token:
                raise ScopeConfigError('SERVICE_TOKENS contains an empty token')
            if isinstance(entry, list):
                entry = {'scopes': entry}
            if not isinstance(entry, dict):
                raise ScopeConfigError(f'SERVICE_TOKENS[{token[:6]}...] must be an object or list')
            scopes = entry.get('scopes') or []
            if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
                raise ScopeConfigError(f'SERVICE_TOKENS[{token[:6]}...].scopes must be a list of strings')
            unknown = set(scopes) - KNOWN_SCOPES
            if unknown:
                raise ScopeConfigError(f'SERVICE_TOKENS[{token[:6]}...] has unknown scopes {sorted(unknown)}')
            generation = entry.get('generation', self._default_generation)
            try:
                generation = max(1, int(generation))
            except (TypeError, ValueError):
                raise ScopeConfigError(f'SERVICE_TOKENS[{token[:6]}...].generation must be an integer')
            self._grants.append((token, frozenset(scopes), generation))

    def _lookup(self, token: str):
        for known, scopes, generation in self._grants:
            if hmac.compare_digest(token, known):
                return {'scopes': scopes, 'generation': generation}
        return None

    def authorize(self, token: str, scope: str) -> dict:
        '''raises ScopeDenied(401) for missing/unknown token, (403) for a scope miss;
           the legacy download key is explicitly rejected, not treated as a grant.'''
        token = str(token or '')
        if not token:
            raise ScopeDenied(401, 'missing service credential (X-Service-Token)')
        if self._download_key and hmac.compare_digest(token, self._download_key):
            raise ScopeDenied(403, 'the download API key does not grant playback service scopes')
        grant = self._lookup(token)
        if grant is None:
            raise ScopeDenied(401, 'unknown service credential')
        if scope not in grant['scopes']:
            raise ScopeDenied(403, f'service credential lacks scope "{scope}"')
        return grant

    def has_scope(self, grant: dict, scope: str) -> bool:
        return scope in (grant or {}).get('scopes', frozenset())
