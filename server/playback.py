'''
Function:
    v2 managed-playback response assembly.
    Keeps shape decisions in one place: echo of the request identity, the actual
    resolved source, honest quality/verification facts (from the strict admission
    policy in playback_profile.py) and cache lifetimes.
Notes:
    delivered_quality is what the resolver actually produced (never the request),
    `verified` is always False here (kwqq never fully verifies a file — Songloft's
    preparation chain does), and `ready` says whether the candidate may be
    delivered once byte verification passes.
'''
import time


def assemble(ref: dict, result: dict, prepared: dict, verdict: dict, *, cached: bool = False,
             cache_ttl_s: int = 0) -> dict:
    ext = str(result.get('ext') or '').lstrip('.').lower() or None
    return {
        'track_ref': ref,
        'resolved_source': str(result.get('source') or ref['source']),
        'requested_quality': prepared['requested_quality'],
        'delivered_quality': verdict.get('delivered_quality'),
        'codec': verdict.get('codec') or ext,
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
            'level': verdict.get('verification_level') or 'declared',
            'requires_byte_verification': bool(verdict.get('requires_byte_verification', True)),
            'requires_transcode': bool(verdict.get('requires_transcode', False)),
        },
        'ready': bool(verdict.get('ready')),
        'verified': False,
        'fallback_reason': verdict.get('fallback_reason'),
        'resolved_at': int(time.time()),
        'cache_expires_at': int(time.time()) + int(cache_ttl_s) if cache_ttl_s else None,
        'upstream_expires_at': None,
        'cached': bool(cached),
    }
