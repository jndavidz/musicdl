'''
Function:
    Quality tier domain — the single owner of cross-source tier knowledge (ADR-0003):
      - alias normalization (MusicFree four tiers + native spellings)
      - per-source tier whitelists
      - 192k rule: real tier where it exists (netease 'higher'), else snap to the
        nearest tier >= 192k (320k) — 'auto' stays the only "best available" request
      - lossless switch gate (ENABLE_LOSSLESS) for the sources that honor it
      - unified 8-element lossless extension set (aligned with library / webgui)
    Platform-private parameter mappings (br/rate/level/quality ids) stay in each
    adapter and must reference these constants instead of raw string literals.
    Consumer capability context (ADR-0002): MusicFree plugins only consume <=320k mp3;
    the lossless/master tiers are effectively webgui-only (webgui decrypts mflac+ekey).
'''
import os


ALIASES = {
    # MusicFree 四档定义: low=128kbps / standard=192kbps / high=320kbps / super 封顶 320kbps
    'low': '128k', 'standard': '192k', 'high': '320k', 'super': '320k',
    'auto': 'auto', '320k': '320k', '128k': '128k', '192k': '192k', 'flac': 'flac', 'hires': 'hires',
    'master': 'master', 'surround51': 'surround51', 'surround5.1': 'surround51', '5.1': 'surround51',
}

'''sources with a REAL 192k upstream tier; every other source snaps 192k -> 320k'''
REAL_192K = frozenset({'netease'})

'''tiers gated by the ENABLE_LOSSLESS switch (where honored — netease/kugou gate by
   container account instead, bilibili by BILI_SESSDATA)'''
LOSSLESS_TIERS = frozenset({'flac', 'hires', 'master', 'surround51'})

LOSSLESS_MSG = 'lossless tier disabled on this server (ENABLE_LOSSLESS=false)'

'''post-decrypt lossless containers, full set (library/webgui-aligned; the old 3-element
   {'flac','wav','ape'} adapter copies missed alac/wv/tta/dsf/dff)'''
LOSSLESS_EXTS = frozenset({'flac', 'wav', 'ape', 'alac', 'wv', 'tta', 'dsf', 'dff'})

'''per-source tier whitelist — replaces the 9 per-adapter inline copies.
   (kuwo has no usable 192k: its 192kmp3 silently downgrades to 128k, so 192k snaps.)'''
DEFAULT_TIERS = frozenset({'auto', '128k', '320k', 'flac', 'hires'})
ALLOWED_TIERS = {
    'kuwo':      frozenset({'auto', '128k', '320k', 'flac', 'hires', 'master', 'surround51'}),
    'qq':        DEFAULT_TIERS,
    'qianqian':  DEFAULT_TIERS,
    'migu':      DEFAULT_TIERS,
    'netease':   frozenset({'auto', '128k', '192k', '320k', 'flac', 'hires'}),
    'kugou':     DEFAULT_TIERS,
    'bilibili':  DEFAULT_TIERS,
    'deezer':    DEFAULT_TIERS,
    'gdstudio':  DEFAULT_TIERS,
}


def normalize(requested: str) -> str:
    '''MusicFree/native spellings -> internal tier; unknown -> auto.'''
    return ALIASES.get((requested or '').lower(), 'auto')


def resolve(source_key: str, requested: str) -> str:
    '''normalize + 192k snap + whitelist. Idempotent; the one entry adapters call.'''
    tier = normalize(requested)
    if tier == '192k' and source_key not in REAL_192K:
        tier = '320k'
    if tier not in ALLOWED_TIERS.get(source_key, DEFAULT_TIERS):
        return 'auto'
    return tier


def requires_lossless(tier: str) -> bool:
    return tier in LOSSLESS_TIERS


def lossless_allowed(tier: str, enable_lossless: bool) -> bool:
    '''True when the tier may proceed under the server's ENABLE_LOSSLESS switch.'''
    return not requires_lossless(tier) or enable_lossless
