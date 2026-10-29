'''
Function:
    Strict managed-playback admission policy (v2 only).
      1. the ORIGINAL quality spelling is whitelisted before legacy normalization,
         so `master`/`flac`/`hires` can never be silently rewritten to `auto`;
      2. a candidate becomes device-deliverable only as mp3 at <=320kbps; lossless
         containers, encrypted containers (ekey) and >320k claims are rejected;
      3. AAC/M4A is accepted ONLY as a Songloft media-preparation input and is
         always marked requires_transcode (never direct-play);
      4. verification is never reported as full: kwqq offers upstream declaration
         or partial byte evidence; the full-file check is Songloft's job.
Notes:
    v1 endpoints keep their old quality/lossless/ekey behavior untouched — this
    module is imported by the v2 route only.
'''
from server.quality import ALIASES, LOSSLESS_EXTS, LOSSLESS_TIERS, resolve as resolve_quality

'''containers a managed-playback device may receive as-is'''
PLAYABLE_EXTS = frozenset({'mp3'})

'''AAC family: only a normalization INPUT for Songloft's preparation chain'''
NORMALIZE_INPUT_EXTS = frozenset({'aac', 'm4a', 'm4s', 'm4b'})

'''encrypted / DRM containers that must never reach a device or a transcoder'''
ENCRYPTED_EXTS = frozenset({'mflac', 'mgg', 'ncm', 'mxp', 'qmcflac', 'qmc0', 'qmc3',
                            'bkcmp3', 'bkcflac', 'kgm', 'vpr', 'kwm', 'tkm'})

MAX_PLAY_BITRATE_KBPS = 320
PLAY_TIERS = frozenset({'auto', '128k', '192k', '320k'})
TARGETS = frozenset({'device', 'media_prepare'})

# delivered_quality ladder from measured bitrate (never from the adapter's wish)
_QUALITY_BY_KBPS = ((240, '320k'), (160, '192k'), (96, '128k'))
_TIER_RANK = {'128k': 1, '192k': 2, '320k': 3}


class ProfileError(ValueError):
    '''policy rejection: carries the honest HTTP class (400 request / 415 media)'''
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def normalize_request(source: str, raw_quality, target=None) -> dict:
    '''whitelist the caller's original spelling, then normalize; lossless requests
       are rejected outright instead of falling back to auto.'''
    raw = str(raw_quality if raw_quality is not None else 'auto').strip().lower() or 'auto'
    if raw not in ALIASES:
        raise ProfileError(400, f'unknown quality "{raw}" (want one of: {", ".join(sorted(ALIASES))})')
    tier = ALIASES[raw]
    if tier in LOSSLESS_TIERS or tier not in PLAY_TIERS:
        raise ProfileError(400, f'quality "{raw}" is not playable in the managed profile '
                                f'(request auto/320k/192k/128k; lossless stays v1-download only)')
    target = str(target or 'device').strip().lower() or 'device'
    if target not in TARGETS:
        raise ProfileError(400, f'unknown profile.target "{target}" (want device or media_prepare)')
    return {'requested_quality': raw, 'tier': resolve_quality(source, raw), 'target': target}


def delivered_quality(ext: str, bitrate_kbps, adapter_quality=None):
    '''measured bitrate first; the adapter's declared tier is only a last resort'''
    try:
        kbps = int(bitrate_kbps) if bitrate_kbps is not None else None
    except (TypeError, ValueError):
        kbps = None
    if ext == 'mp3' and kbps:
        for floor, label in _QUALITY_BY_KBPS:
            if kbps >= floor:
                return label
        return 'low'
    if adapter_quality in _TIER_RANK:
        return adapter_quality
    return None


def classify(result: dict, prepared: dict, *, allow_normalize_input: bool = False) -> dict:
    '''admission verdict for one resolved candidate; raises ProfileError on rejection'''
    ext = str(result.get('ext') or '').lstrip('.').lower()
    level = 'partial' if result.get('verified') else 'declared'
    verdict = {'codec': ext or None, 'verification_level': level,
               'requires_byte_verification': True, 'requires_transcode': False,
               'ready': False, 'delivered_quality': None, 'fallback_reason': None}

    if result.get('ekey') or ext in ENCRYPTED_EXTS:
        raise ProfileError(415, f'encrypted media ({ext or "ekey"}) is not playable; '
                                f'it stays a v1 download/decrypt artifact')
    if not ext:
        raise ProfileError(415, 'codec evidence missing — refusing to treat the candidate as playable')
    if ext in LOSSLESS_EXTS:
        raise ProfileError(415, f'lossless container "{ext}" is not playable in the managed profile')
    if ext in NORMALIZE_INPUT_EXTS:
        if not allow_normalize_input:
            raise ProfileError(415, f'"{ext}" may only enter a Songloft media-preparation '
                                    f'(target=media_prepare) request')
        verdict.update(requires_transcode=True, requires_byte_verification=True,
                       delivered_quality=None,
                       fallback_reason=f'{ext} input for transcoding; never delivered directly')
        return verdict
    if ext not in PLAYABLE_EXTS:
        raise ProfileError(415, f'unsupported codec "{ext}" for managed playback (mp3 only)')

    try:
        kbps = int(result.get('bitrate_kbps')) if result.get('bitrate_kbps') is not None else None
    except (TypeError, ValueError):
        kbps = None
    if kbps is not None and kbps > MAX_PLAY_BITRATE_KBPS:
        raise ProfileError(415, f'delivered bitrate {kbps}kbps exceeds the {MAX_PLAY_BITRATE_KBPS}k ceiling')

    dq = delivered_quality(ext, kbps, result.get('quality'))
    verdict['delivered_quality'] = dq
    has_payload_evidence = bool(kbps) or (bool(result.get('size_bytes')) and bool(result.get('duration_s')))
    if not has_payload_evidence:
        verdict['fallback_reason'] = 'insufficient evidence (no bitrate/size/duration) — byte verification required'
        return verdict
    requested_rank = _TIER_RANK.get(prepared.get('tier'))
    delivered_rank = _TIER_RANK.get(dq)
    if requested_rank and delivered_rank and delivered_rank < requested_rank:
        verdict['fallback_reason'] = f'downgraded: requested {prepared["tier"]}, delivered {dq}'
    verdict['ready'] = True
    return verdict
