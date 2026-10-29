'''
Function:
    v2 managed-playback response assembly.
    Keeps the shape decisions in one place: echo of the request identity, the
    actual resolved source, quality/verification facts and cache lifetimes.
Notes:
    delivered_quality is what the resolver actually produced (never the request),
    and `verified` is always False here: kwqq can only offer upstream declaration
    or partial byte evidence; full-file verification belongs to Songloft's
    preparation chain (K-02 tightens the admission rules in this seam).
'''
import time

from server.quality import resolve as resolve_quality


def prepare_profile(source: str, profile: dict) -> dict:
    '''original spelling + normalized tier (K-02 adds the pre-normalization whitelist)'''
    requested = str((profile or {}).get('quality') or 'auto').strip().lower() or 'auto'
    return {'requested_quality': requested,
            'tier': resolve_quality(source, requested),
            'target': str((profile or {}).get('target') or 'device').strip().lower() or 'device'}


def assemble(ref: dict, result: dict, prepared: dict, *, cached: bool = False,
             cache_ttl_s: int = 0, requested_identity: dict = None) -> dict:
    ext = str(result.get('ext') or '').lstrip('.').lower() or None
    return {
        'track_ref': ref,
        'resolved_source': str(result.get('source') or ref['source']),
        'requested_quality': prepared['requested_quality'],
        'delivered_quality': result.get('quality'),
        'codec': ext,
        'url': result.get('url') or '',
        'ext': ext,
        'size_bytes': result.get('size_bytes'),
        'bitrate_kbps': result.get('bitrate_kbps'),
        'duration_s': result.get('duration_s'),
        'cover': result.get('cover'),
        'headers': result.get('headers') or {},
        'parser': result.get('parser'),
        'platform_tag': result.get('platform_tag'),
        'verification': {
            'level': 'partial' if result.get('verified') else 'declared',
            'requires_byte_verification': True,
            'requires_transcode': False,
        },
        'verified': False,
        'fallback_reason': None,
        'resolved_at': int(time.time()),
        'cache_expires_at': int(time.time()) + int(cache_ttl_s) if cache_ttl_s else None,
        'upstream_expires_at': None,
        'cached': bool(cached),
    }
