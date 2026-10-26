'''
Function:
    musicdl-webgui quality/naming/dedupe helpers: quality-tier estimation from
    ext + real size/duration, the fake-quality guard, readable filename rendering
    and collision-safe path allocation, normalized cross-platform dedupe keys,
    and serialize_item (the API response shape for one search candidate).
'''
import re
import threading
import contextlib
from pathlib import Path

from config import SETTINGS, PLATFORM_MAP, DEFAULT_CONFIG
from musicdl.modules.utils import SongInfo  # noqa: F401  (annotation typing only)

LOSSLESS_EXTS = {'flac', 'wav', 'alac', 'ape', 'wv', 'tta', 'dsf', 'dff'}
QUALITY_ORDER = {'master': 0, 'surround51': 1, 'hires': 2, 'lossless': 3, '320k': 4, '128k': 5, 'other': 6, 'low': 7, 'pending': -1}
QUALITY_PREF_RANKS = {
    'hires_first': ['master', 'hires', 'lossless', '320k', '128k', 'other', 'low'],
    'lossless_first': ['master', 'hires', 'lossless', '320k', '128k', 'other', 'low'],
    'lossless_only': ['master', 'hires', 'lossless'],
    'master_only': ['master'],       # kuwo 20900kmflac only (192k/24bit/2ch, anonymous)
    'surround51_only': ['surround51', 'master', 'hires', 'lossless'],  # kuwo 20501kmflac, fall back to 2ch
    '320k': ['320k', 'master', 'hires', 'lossless', '128k', 'low', 'other'],
    '128k': ['128k', '320k', 'low', 'other', 'master', 'hires', 'lossless'],
    'any': ['master', 'hires', 'lossless', '320k', '128k', 'other', 'low'],
}
# 音质规格表 (每分钟体积 MB/min), 用于分级与假质量清洗:
#   母带级 24bit/192kHz FLAC : 45-70 | 高解析 24bit/96kHz : 20-35
#   CD 16bit/44.1kHz FLAC    : 5-10  | HQ 320kbps mp3 : ~2.34 | PQ 128kbps : ~0.9
#   档位定性基准（2026-09-07 docs/QUALITY-MATRIX.md）: 母带 = 24bit & ≥96kHz；
#   24bit/48kHz 仅入门级 Hi-Res（千千 rate=3000 上限即此），酷我 master(20900kmflac)
#   实测 192k/24bit ~39.8-41.7 MB/min 落在本表 42 阈之下，webgui 判级由显式档位/channels 修正。
# 音质规格表 v2 (每分钟体积 MB/min), calibrated against real downloads (2026-08,
# 邓丽君《又见炊烟》2:52 across all sources):
#   netease black-vip Hi-Res remasters land 29-38; qq third-party HR chain peaks
#   at 40.8; aggregators compress the very same tracks down to <=19 (br<=999);
#   plain CD sits at 5-10; 320k transcode is 2.34.
LOSSLESS_MBPM_FLOOR = 4       # lossless below this is a transcode (320k->flac is 2.34)

# 显式档位映射（QUALITY-MATRIX §2 可信标注 -> tier）：kuwo br 档 / kugou quality /
# netease granted level 均已实测与交付规格一致。咪咕 toneFlag(SQ/ZQ) 实测假无损、
# 千千 rate 逐曲不定 —— 两者的标注不可信，不进此表，走 MB/min 推算。
# ⚠️ THE LITERAL LIVES IN app.py — server/tests/test_offline.py ast-parses it out of
# app.py (no import) for the webgui/server kuwo tag-table sync check; app.py injects
# the parsed dict into this module global at import time.
PLATFORM_TAG_TIER: dict = {}
HIRES_MBPM = 17               # aggregator compression ceiling (~19) overlaps here
MASTER_MBPM = 42              # true studio-master territory starts past qq-HR peak (40.8)


def calc_mbpm(size_bytes, duration_s):
    '''volume in MB per minute; None when data missing (never guess).'''
    try:
        if not size_bytes or not duration_s: return None
        return round(size_bytes / 1048576 / (float(duration_s) / 60), 1)
    except Exception: return None


def estimate_kbps(size_bytes, duration_s):
    '''estimated bitrate in kbps; None when missing or absurd (bad source metadata).'''
    try:
        if not size_bytes or not duration_s: return None
        kbps = int(round(size_bytes * 8 / float(duration_s) / 1000))
        return kbps if 24 <= kbps <= 12000 else None   # master-grade flac can exceed 6000
    except Exception: return None


def quality_tier(ext, size_bytes=None, duration_s=None, channels=None) -> str:
    '''ext of an already-DECRYPTED file + real size/duration -> display tier.
       `channels` (kuwo surround51 = 6ch) short-circuits the MB/min ladder:
       16bit/6ch lands ~17.1 MB/min, right at the hires floor, so classify by layout.'''
    e = str(ext or '').lower().lstrip('.') or 'unknown'
    if e in LOSSLESS_EXTS:
        if channels == 6: return 'surround51'
        m = calc_mbpm(size_bytes, duration_s)
        if m is None:
            # metadata incomplete -> base tier by ext; big files are likely hi-res
            return 'hires' if (size_bytes or 0) >= 60 * 1024 * 1024 else 'lossless'
        if m >= MASTER_MBPM: return 'master'
        if m >= HIRES_MBPM: return 'hires'
        return 'lossless'
    kbps = estimate_kbps(size_bytes, duration_s)
    if e == 'mp3':
        return '320k' if (kbps or 0) >= 240 else ('128k' if (kbps or 0) >= 96 else 'low')
    if e in {'m4a', 'aac', 'ogg', 'opus', 'wma'}:
        return '320k' if (kbps or 0) >= 200 else '128k'
    return 'other'


def is_suspect_quality(tier: str, size_bytes, duration_s=None) -> bool:
    '''fake-quality guard: lossless judged by MB/min floor (user spec table),
       mp3 tiers by absolute size floors. Missing data never flags.'''
    if not SETTINGS.get('quality_guard', True): return False
    if tier in {'master', 'surround51', 'hires', 'lossless'}:
        m = calc_mbpm(size_bytes, duration_s)
        return m is not None and m < LOSSLESS_MBPM_FLOOR
    floor_mb = {'320k': 5, '128k': 2}.get(tier)
    if not floor_mb: return False
    return bool(size_bytes) and size_bytes < floor_mb * 1024 * 1024


_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class _SafeDict(dict):
    def __missing__(self, key): return ''


def render_stem(template: str, info: SongInfo, platform_id: str) -> str:
    '''render "{artist} - {title} - {album}" style stem; drop empty segments gracefully.'''
    text = template or DEFAULT_CONFIG['naming_template']
    def clean_val(v: str) -> str:
        v = str(v or '').strip()
        return '' if v.lower() in {'null', 'none', 'n/a', '未知', 'undefined'} else v
    stem = text.format_map(_SafeDict({
        'artist': clean_val(info.singers),
        'title': clean_val(info.song_name) or '未知曲目',
        'album': clean_val(info.album),
        'source': PLATFORM_MAP.get(platform_id, {}).get('short', platform_id),
        'ext': str(info.ext or '').lstrip('.'),
    }))
    segs = [seg.strip() for seg in stem.split('-')]
    if len(segs) > 1: stem = ' - '.join([seg for seg in segs if seg])
    stem = re.sub(r'\s+', ' ', _ILLEGAL_RE.sub(' ', stem)).strip(' .-')
    return (stem or '未知曲目')[:180]


_path_lock = threading.Lock()


def allocate_path(stem: str, ext: str) -> str:
    with _path_lock:
        root = Path(SETTINGS['download_dir'])
        ext = (ext or 'mp3').lower().lstrip('.')
        path, idx = root / f'{stem}.{ext}', 1
        while path.exists(): path, idx = root / f'{stem} ({idx}).{ext}', idx + 1
        return str(path)


_PAREN_RE = re.compile(r'[（(【\[]([^)）\]]*)[)）\]]')
# bracket contents that describe audio quality/format, not the song version -> ignored in dedupe key
_QUALITY_TAG_RE = re.compile(r'^(flac|wav|mp3|aac|ape|无损|hi-?res|hires|320k?bp?s?|320|128|192|音质|sq|hq|高品?质?|正版|完整?版?)$', re.I)


def normkey(info: SongInfo) -> str:
    '''normalized cross-platform song key; keeps LIVE/DJ/piano etc. version words so
    different renditions are NOT folded together, drops pure quality tags like (FLAC).'''
    def clean(text) -> str:
        text = str(text or '')
        return re.sub(r'[\s\'+·～~!@#$%^&*_+=`,.?;:"’‘“”]+', '', text).lower()
    raw = str(info.song_name or '')
    version_tags = ''.join(t for t in _PAREN_RE.findall(raw) if not _QUALITY_TAG_RE.match(t.strip()))
    core = _PAREN_RE.sub('', raw)
    first_singer = re.split(r'[/、,&]|feat\.?', str(info.singers or ''))[0]
    return f'{clean(core)}~{clean(version_tags)}|{clean(first_singer)}'


def parse_duration_seconds(duration_str):
    with contextlib.suppress(Exception):
        parts = [int(x) for x in str(duration_str).split(':')]
        return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
    return None


def fmt_mb(size_bytes) -> str:
    return f'{(size_bytes or 0) / 1048576:.1f}MB'


def parse_size_bytes(file_size_str):
    with contextlib.suppress(Exception):
        fs = str(file_size_str).upper().strip()
        if 'GB' in fs: return int(float(fs.replace('GB', '')) * 1024 ** 3)
        if 'KB' in fs: return int(float(fs.replace('KB', '')) * 1024)
        if 'MB' in fs: return int(float(fs.replace('MB', '')) * 1024 ** 2)
    return None


# DRM/encrypted container formats that can never be played once downloaded
ENCRYPTED_EXTS = {'mgg', 'mxp', 'ncm', 'mflac', 'm4a?'}

# platform quality tags that describe a LOSSY tier (per-source native naming)
_LOSSY_TAG_RE = re.compile(r'mp3|standard|exhigh|\b128\b|\b320\b|\bpq\b|\bhq\b', re.I)
# sources whose platform_tag faithfully reflects the delivered file (qq's third-party
# chain frequently upgrades the request, so its annotation must not trigger the guard)
_TAG_TRUSTED_SOURCES = {'kuwo', 'netease', 'kugou', 'migu', 'qianqian'}


def serialize_item(key: str, info, platform_id: str) -> dict:
    size_bytes = info.file_size_bytes or parse_size_bytes(info.file_size)
    duration_s = info.duration_s or parse_duration_seconds(info.duration)
    ext_l = str(info.ext or '').lower().lstrip('.')
    # DRM/encrypted containers are unusable once downloaded -> surfaced as 失效.
    # Exception: kuwo zhenpin mflac/mgg ships with ekey and auto-decrypts on download.
    # computed (never assigned): SongInfo.with_valid_download_url is a read-only property.
    has_ekey = bool((getattr(info, 'api_extra', {}) or {}).get('ekey'))
    decryptable = ext_l in {'mflac', 'mgg'} and has_ekey
    usable = bool(info.with_valid_download_url) and (ext_l not in ENCRYPTED_EXTS or decryptable)
    tier = quality_tier(ext_l, size_bytes, duration_s)
    is_api = PLATFORM_MAP.get(platform_id, {}).get('group') == 'api'
    # kwqq-api metadata search carries no ext/size; the real format is only known after
    # the per-song /song/url resolve at download time -> show an honest "pending" badge.
    if is_api and not str(info.ext or '').strip(): tier = 'pending'
    # search-stage stock (qq file sizes / netease hr-sq-h): show real payload even
    # while ext is unknown; also feeds the size column for pending rows.
    if not size_bytes and is_api:
        size_bytes = int(getattr(info, 'stock_size_bytes', 0) or 0) or None
    platform_tag = str(getattr(info, 'platform_tag', '') or '')
    api_src = str(getattr(info, 'api_source', '') or '')
    # 显式档位优先（QUALITY-MATRIX §2）：kuwo/kugou/netease 的标注已实测与交付规格
    # 一致（含酷我加密档——解密后规格由显式档位声明，下载钩子自动 QMC 解密）。
    # MB/min 推算仅作无显式标注时的兜底；标注与体积矛盾时以 tooltip 提示。
    explicit_tier = PLATFORM_TAG_TIER.get(platform_tag) if is_api else None
    if explicit_tier is None and is_api and '24bit' in platform_tag:
        explicit_tier = 'hires'   # qianqian tracklink bits=24 (server-declared file attribute)
    if explicit_tier:
        tier = explicit_tier
    suspect, suspect_reason = False, ''
    if tier != 'pending':
        # (1) 平台标注前置: 可信源的有损档标注 + 无损文件 = 转码铁证, 先于体积推算
        if (platform_tag and is_api and api_src in _TAG_TRUSTED_SOURCES
                and _LOSSY_TAG_RE.search(platform_tag) and str(info.ext or '').lower().lstrip('.') in LOSSLESS_EXTS):
            suspect, suspect_reason = True, f'平台标注「{platform_tag}」为有损档, 文件却是{str(info.ext).upper()}, 疑似转码'
        # (2) 体积推算兜底 (规格表 MB/分钟)
        elif is_suspect_quality(tier, size_bytes, duration_s):
            m = calc_mbpm(size_bytes, duration_s)
            if tier in {'master', 'surround51', 'hires', 'lossless'} and m is not None:
                conflict = f'（与平台标注「{platform_tag}」矛盾）' if platform_tag else ''
                suspect_reason = f'疑似假无损({m}MB/分钟 < {LOSSLESS_MBPM_FLOOR}){conflict}'
            else:
                suspect_reason = f"疑似假质量({fmt_mb(size_bytes)} 低于{tier}下限)"
    return {
        'key': key, 'source': platform_id, 'origin': 'api' if is_api else 'lib',
        'song_name': str(info.song_name or ''), 'singers': str(info.singers or ''),
        'album': str(info.album or ''), 'duration': str(info.duration or ''),
        'duration_s': duration_s, 'ext': str(info.ext or '').lstrip('.'),
        'file_size': str(info.file_size or ''), 'file_size_bytes': size_bytes,
        'quality_tier': tier, 'bitrate_kbps': estimate_kbps(size_bytes, duration_s),
        'mbpm': calc_mbpm(size_bytes, duration_s),
        'platform_tag': platform_tag,
        'suspect': suspect, 'suspect_reason': suspect_reason,
        'root_source': '' if is_api else str(getattr(info, 'root_source', '') or ''),
        'has_url': usable, 'dedupe_key': normkey(info),
    }
