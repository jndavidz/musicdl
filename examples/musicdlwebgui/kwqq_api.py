'''
Function:
    kwqq-api client (six sources backed by the NAS kw-qq-music-api service):
    metadata-only search, two-stage per-song url resolve (quality tiers, ekey
    decryption notes, header backfill), and the connectivity probe. ApiSongInfo
    is a duck-typed stand-in matching the SongInfo attribute surface used here.
'''
import os
import contextlib

import requests

from config import SETTINGS, PLATFORM_MAP
from quality import LOSSLESS_EXTS


class ApiSongInfo:
    '''duck-typed stand-in matching the SongInfo attribute surface used by this app.'''

    def __init__(self, **kw):
        self.api_id = None; self.api_source = None; self.api_extra = {}
        self.with_valid_download_url = True
        self.download_url = None; self.protocol = 'HTTP'
        self.downloaded_contents = None; self.chunk_size = 1024 * 1024
        self.default_download_headers = {}; self.default_download_cookies = {}
        self.episodes = None; self.lyric = ''; self.cover_url = ''
        self.platform_tag = ''; self.work_dir = './'; self._save_path = None
        self.song_name = ''; self.singers = ''; self.album = ''
        self.ext = ''; self.file_size_bytes = None; self.file_size = ''
        self.duration_s = None; self.duration = ''; self.bitrate_kbps = None
        self.samplerate = None; self.channels = None; self.codec = None
        self.root_source = ''; self.source = ''
        self.__dict__.update(kw)

    @property
    def save_path(self):
        if self._save_path: return self._save_path
        return os.path.join(self.work_dir, f'{self.song_name or "unknown"}.{self.ext or "mp3"}')


def _api_get(path: str, params: dict = None, timeout: float = 35):
    base = str(SETTINGS['kwqq_api_base']).rstrip('/')
    headers = {'X-API-Key': SETTINGS['kwqq_api_key']} if SETTINGS.get('kwqq_api_key') else {}
    resp = requests.get(f'{base}{path}', params=params or {}, headers=headers, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if body.get('code') != 200:
        raise RuntimeError(f"API code={body.get('code')}: {str(body.get('msg', ''))[:140]}")
    return body.get('data')


def api_online() -> bool:
    try:
        base = str(SETTINGS['kwqq_api_base']).rstrip('/')
        headers = {'X-API-Key': SETTINGS['kwqq_api_key']} if SETTINGS.get('kwqq_api_key') else {}
        return requests.get(f'{base}/healthz', headers=headers, timeout=3).ok
    except Exception:
        return False


def seconds2hms(seconds) -> str:
    with contextlib.suppress(Exception):
        s = int(round(float(seconds)))
        return f'{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}'
    return ''


def api_search_sync(platform_id: str, keyword: str, limit: int) -> list:
    '''metadata-only search via kwqq-api; download urls are resolved lazily per song.'''
    meta = PLATFORM_MAP[platform_id]
    data = _api_get(f"/{meta['api_source']}/search", {'keywords': keyword, 'limit': limit},
                    timeout=max(15, int(SETTINGS['search_timeout_s'])))
    items = (data or {}).get('items') or []
    out = []
    for it in items[:limit]:
        dur = it.get('duration_s')
        out.append(ApiSongInfo(
            song_name=str(it.get('name') or ''), singers=str(it.get('singer') or ''),
            album=str(it.get('album') or ''), ext=str(it.get('ext') or '').lstrip('.'),
            file_size_bytes=it.get('size_bytes'), file_size='', bitrate_kbps=None,
            duration_s=dur, duration=seconds2hms(dur), codec=None, samplerate=None,
            cover_url=str(it.get('cover') or ''), lyric='',
            source=platform_id, root_source=f"{meta['api_source']}@api",
            download_url=None, protocol='HTTP',
            platform_tag=str(it.get('stock_tier') or ''),
            api_id=str(it.get('id')), api_source=meta['api_source'],
            api_extra=dict(it.get('extra') or {}),
        ))
    return out


_API_QUALITY_MAP = {'hires_first': 'hires', 'lossless_first': 'flac', 'lossless_only': 'flac',
                    'master_only': 'master', 'surround51_only': 'surround51',
                    '320k': '320k', '128k': '128k', 'any': 'auto'}


def api_resolve_into(info: ApiSongInfo, quality_pref: str):
    '''two-stage resolve. Order matters: /song/info metadata backfill runs FIRST so
    duration/cover/size survive even when the url resolve later fails (404 etc.).'''
    q = _API_QUALITY_MAP.get(quality_pref, 'auto')
    params = {'id': info.api_id, 'quality': q}
    copyright_id = (info.api_extra or {}).get('copyrightId')
    if info.api_source == 'migu' and copyright_id: params['copyright'] = copyright_id
    # migu-style resolvers omit duration/cover -> fetch from /song/info up front
    if not getattr(info, 'duration_s', None) or not info.cover_url:
        with contextlib.suppress(Exception):
            meta = _api_get(f"/{info.api_source}/song/info", params) or {}
            if meta.get('duration_s'):
                info.duration_s = meta['duration_s']; info.duration = seconds2hms(meta['duration_s'])
            if meta.get('size_bytes') and not info.file_size_bytes:
                info.file_size_bytes = meta['size_bytes']
            info.cover_url = str(meta.get('cover') or '') or info.cover_url
    try:
        data = _api_get(f"/{info.api_source}/song/url", params) or {}
    except RuntimeError as err:
        if q != 'auto' and ('403' in str(err) or '404' in str(err)):
            # lossless tier disabled on the API side -> graceful fallback to auto
            params['quality'] = 'auto'
            data = _api_get(f"/{info.api_source}/song/url", params) or {}
            info.api_fallback_note = f'{q}档不可用已回退auto'
        else:
            raise
    url = data.get('url')
    if not url: raise RuntimeError('API 未返回可用直链')
    info.download_url = url
    info.platform_tag = str(data.get('platform_tag') or '')
    # kuwo zhenpin: encrypted container + QMC key -> download hook decrypts to flac/ogg
    if data.get('ekey'):
        info.api_extra = {**(info.api_extra or {}), 'ekey': data['ekey']}
        info.ext = 'mflac' if 'mflac' in str(data.get('platform_tag') or '') else 'mgg'
    # unblock/mirror links (e.g. netease match -> kuwo CDN) require anti-hotlink headers
    resp_headers = data.get('headers') or {}
    if isinstance(resp_headers, dict) and resp_headers:
        info.default_download_headers = {**resp_headers, **getattr(info, 'default_download_headers', {})}
    if data.get('ext'): info.ext = str(data['ext']).lstrip('.')
    if data.get('size_bytes'): info.file_size_bytes = data['size_bytes']
    if data.get('duration_s'):
        info.duration_s = data['duration_s']; info.duration = seconds2hms(data['duration_s'])
    # kugou/migu/qianqian style resolvers omit size -> probe it via HEAD (Content-Length)
    if not info.file_size_bytes:
        with contextlib.suppress(Exception):
            h = requests.head(url, timeout=(3, 8), allow_redirects=True,
                              headers={'User-Agent': 'Mozilla/5.0'})
            cl = int(h.headers.get('Content-Length', 0) or 0)
            if cl > 0: info.file_size_bytes = cl
    if quality_pref in {'lossless_first', 'lossless_only'} and str(info.ext).lower() not in LOSSLESS_EXTS and not getattr(info, 'api_fallback_note', None):
        info.api_fallback_note = 'API 返回非无损(检查 ENABLE_LOSSLESS)'
    if quality_pref == 'lossless_only' and str(info.ext).lower() not in LOSSLESS_EXTS:
        raise RuntimeError('音质偏好为仅无损, 但 API 未返回无损资源')
    # lyrics & cover, best effort
    with contextlib.suppress(Exception):
        info.lyric = (_api_get(f"/{info.api_source}/lyric", {'id': info.api_id}) or {}).get('lyric') or ''
    with contextlib.suppress(Exception):
        cover = (_api_get(f"/{info.api_source}/song/info", {'id': info.api_id}) or {}).get('cover')
        info.cover_url = cover or info.cover_url
