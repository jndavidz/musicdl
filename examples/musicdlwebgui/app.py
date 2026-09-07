'''
Function:
    musicdl-webgui: an easy-to-use web GUI for musicdl.
    Search across platforms with per-source result limits, download everything
    into ONE flat directory with human-readable names (artist - title - album),
    quality-tier preference, and lyrics/cover/tags embedded into a single audio file.
Design notes (zero modification to the musicdl library):
    * search(persist_results=False)   -> no per-platform workdirs / pkl files
    * SongInfo._save_path override    -> one fixed download dir + readable names
    * client._download(...)           -> per-item download without pkl dumping
    * ProgressStub                    -> duck-typed rich.Progress replacement feeding SSE
    * SongInfoUtils.savelrctofile patched -> no .lrc sidecar unless enabled in config,
      so lyrics/cover/tags stay embedded inside the ONE audio file
Run:
    cd /mnt/d/repos/musicdl && uv run python examples/musicdlwebgui/app.py --port 3004
'''
import os
import re
import sys
import json
import copy
import time
import uuid
import argparse
import asyncio
import threading
import contextlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

'''---------------- config ----------------'''

_MODULE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get('MUSICDL_WEBGUI_CONFIG', _MODULE_DIR / 'config.json'))

DEFAULT_CONFIG = {
    'download_dir': '/mnt/d/MusicDL-Downloads',
    'host': '127.0.0.1',
    'port': 3004,
    'concurrency': 3,
    'search_timeout_s': 90,
    'max_limit_per_source': 30,
    'naming_template': '{artist} - {title} - {album}',
    'quality_pref_default': 'lossless_first',
    'dedupe_default': True,
    'quality_guard': True,
    'save_lrc_sidecar': False,
    'kwqq_api_base': 'http://10.10.10.2:3003',
    'kwqq_api_key': '',
    # 酷我 VIP cookie (kw_token=xxx; csrf=xxx) — 4000kflac 加密档 + QMC 解密。
    # ⚠️ deprecated: 已被匿名 master 通道(20900kmflac, 192k/24bit, 无 Cookie)覆盖,
    # 保留作为匿名通道失效时的备份路径 (加密档常量与解密器均为 musicdl 内置资源)
    'kuwo_vip_cookie': '',
    # aggregator subsource selection, e.g. {"tunehub": ["netease", "qq"], "gdstudio": ["netease"]}
    'platform_subsources': {},
    'api_key': '',
    'platform_defaults': {'qq': 5, 'netease': 5, 'kugou': 5, 'kuwo': 5, 'migu': 5, 'qianqian': 5},
}

PLATFORMS = [
    # ---- kwqq-API 六源 (NAS 服务: 账户态无损/熔断/缓存; 网易走 MUSIC_U, 酷狗走容器背书) ----
    {'id': 'kuwo',     'client': 'KuwoMusicClient',      'name': '酷我',        'short': '酷我',   'group': 'api', 'api_source': 'kuwo'},
    {'id': 'qq',       'client': 'QQMusicClient',        'name': 'QQ 音乐',     'short': 'QQ',    'group': 'api', 'api_source': 'qq'},
    {'id': 'qianqian', 'client': 'QianqianMusicClient',  'name': '千千',        'short': '千千',   'group': 'api', 'api_source': 'qianqian'},
    {'id': 'migu',     'client': 'MiguMusicClient',      'name': '咪咕',        'short': '咪咕',   'group': 'api', 'api_source': 'migu'},
    {'id': 'netease',  'client': 'NeteaseMusicClient',   'name': '网易云·自有', 'short': '网易自', 'group': 'api', 'api_source': 'netease'},
    {'id': 'kugou',    'client': 'KugouMusicClient',     'name': '酷狗·自有',   'short': '酷狗自', 'group': 'api', 'api_source': 'kugou'},
    # ---- 国内 (进程内库直连 + 国内平台; 与自有版互为备份/规格互补) ----
    {'id': 'netease_direct',   'client': 'NeteaseMusicClient',  'name': '网易云·直连', 'short': '网易',   'group': 'cn'},
    {'id': 'kugou_direct',     'client': 'KugouMusicClient',    'name': '酷狗·直连',   'short': '酷狗',   'group': 'cn'},
    {'id': 'kuwo_direct',      'client': 'KuwoMusicClient',     'name': '酷我·直连',   'short': '酷我',   'group': 'cn'},
    {'id': 'qq_direct',        'client': 'QQMusicClient',       'name': 'QQ·直连',     'short': 'QQ',     'group': 'cn'},
    {'id': 'qianqian_direct',  'client': 'QianqianMusicClient', 'name': '千千·直连',   'short': '千千',   'group': 'cn'},
    {'id': 'migu_direct',      'client': 'MiguMusicClient',     'name': '咪咕·直连',   'short': '咪咕',   'group': 'cn'},
    {'id': 'bilibili',         'client': 'BilibiliMusicClient', 'name': '哔哩哔哩',    'short': 'B站',    'group': 'cn'},
    {'id': 'soda',           'client': 'SodaMusicClient',      'name': '汽水音乐',    'short': '汽水',   'group': 'cn'},
    {'id': 'bodian',         'client': 'BodianMusicClient',    'name': '波点音乐',    'short': '波点',   'group': 'cn'},
    {'id': 'moov',           'client': 'MOOVMusicClient',      'name': '摩音符',      'short': 'MOOV',   'group': 'cn'},
    {'id': 'streetvoice',    'client': 'StreetVoiceMusicClient','name': '街声',       'short': '街声',   'group': 'cn'},
    {'id': 'fivesing',       'client': 'FiveSingMusicClient',  'name': '5SING音乐',   'short': '5SING',  'group': 'cn'},
    # ---- 聚合网关 (jbsou/xiaobai/tunehub/gdstudio 支持子源白名单与每子源数量) ----
    {'id': 'tunehub',   'client': 'TuneHubMusicClient',   'name': 'TuneHub',  'short': 'TH',     'group': 'agg',
     'subsources': [{'id': 'netease', 'name': '网易'}, {'id': 'qq', 'name': 'QQ'}, {'id': 'kuwo', 'name': '酷我'}]},
    {'id': 'gdstudio',  'client': 'GDStudioMusicClient',  'name': 'GD音乐台', 'short': 'GD',     'group': 'agg',
     'subsources': [{'id': 'netease', 'name': '网易'}, {'id': 'joox', 'name': 'JOOX'}, {'id': 'tidal', 'name': 'TIDAL'},
                    {'id': 'qobuz', 'name': 'Qobuz'}, {'id': 'apple', 'name': 'Apple'}, {'id': 'bilibili', 'name': 'B站'}]},
    {'id': 'jbsou',     'client': 'JBSouMusicClient',     'name': '煎饼搜',   'short': '煎饼',   'group': 'agg',
     'subsources': [{'id': 'netease', 'name': '网易'}, {'id': 'qq', 'name': 'QQ'}, {'id': 'kugou', 'name': '酷狗'}, {'id': 'kuwo', 'name': '酷我'}]},
    {'id': 'xiaobai',   'client': 'XiaoBaiMusicClient',   'name': '小白音乐', 'short': '小白',   'group': 'agg',
     'subsources': [{'id': 'netease', 'name': '网易'}, {'id': 'qq', 'name': 'QQ'}, {'id': 'kugou', 'name': '酷狗'}, {'id': 'kuwo', 'name': '酷我'}]},
    {'id': 'myfreemp3', 'client': 'MyFreeMP3MusicClient', 'name': 'MyFreeMP3','short': 'MFMP3',  'group': 'agg'},
    {'id': 'mp3juice',  'client': 'MP3JuiceMusicClient',  'name': 'MP3Juice', 'short': 'MJ',     'group': 'agg'},
    # ---- 广播 / 有声 (默认折叠) ----
    {'id': 'ximalaya', 'client': 'XimalayaMusicClient',  'name': '喜马拉雅',   'short': '喜马', 'group': 'radio'},
    {'id': 'lizhi',    'client': 'LizhiMusicClient',     'name': '荔枝FM',     'short': '荔枝', 'group': 'radio'},
    {'id': 'qingting', 'client': 'QingtingMusicClient',  'name': '蜻蜓FM',     'short': '蜻蜓', 'group': 'radio'},
    {'id': 'lrts',     'client': 'LRTSMusicClient',      'name': '懒人听书',   'short': '懒人', 'group': 'radio'},
    {'id': 'itunes',   'client': 'ITunesMusicClient',    'name': '苹果播客',   'short': '播客', 'group': 'radio'},
    # ---- 国外流媒体 / 独立 (默认折叠) ----
    {'id': 'apple',            'client': 'AppleMusicClient',          'name': 'Apple Music',  'short': 'Apple',  'group': 'global'},
    {'id': 'deezer',           'client': 'DeezerMusicClient',         'name': 'Deezer',       'short': 'Deezer', 'group': 'global'},
    {'id': 'tidal',            'client': 'TIDALMusicClient',          'name': 'TIDAL',        'short': 'TIDAL',  'group': 'global'},
    {'id': 'qobuz',            'client': 'QobuzMusicClient',          'name': 'Qobuz',        'short': 'Qobuz',  'group': 'global'},
    {'id': 'spotify',          'client': 'SpotifyMusicClient',        'name': 'Spotify',      'short': 'Spotify','group': 'global'},
    {'id': 'youtube',          'client': 'YouTubeMusicClient',        'name': '油管音乐',      'short': 'YT',     'group': 'global'},
    {'id': 'soundcloud',       'client': 'SoundCloudMusicClient',     'name': 'SoundCloud',   'short': 'SC',     'group': 'global'},
    {'id': 'joox',             'client': 'JooxMusicClient',           'name': 'JOOX',         'short': 'JOOX',   'group': 'global'},
    {'id': 'jiosaavn',         'client': 'JioSaavnMusicClient',       'name': 'JioSaavn',     'short': 'Saavn',  'group': 'global'},
    {'id': 'jamendo',          'client': 'JamendoMusicClient',        'name': 'Jamendo',      'short': 'Jamendo','group': 'global'},
    {'id': 'audius',           'client': 'AudiusMusicClient',         'name': 'Audius',       'short': 'Audius', 'group': 'global'},
    {'id': 'ccmixter',         'client': 'CCMixterMusicClient',       'name': 'ccMixter',     'short': 'Mixter', 'group': 'global'},
    {'id': 'fma',              'client': 'FMAMusicClient',            'name': 'FMA 自由音乐', 'short': 'FMA',    'group': 'global'},
    {'id': 'opengameart',      'client': 'OpenGameArtMusicClient',    'name': '开源游戏素材', 'short': 'OGA',    'group': 'global'},
    {'id': 'suno',             'client': 'SunoMusicClient',           'name': 'Suno AI 音乐', 'short': 'Suno',   'group': 'global'},
    {'id': 'wikimediacommons', 'client': 'WikimediaCommonsMusicClient','name': '维基共享资源', 'short': 'Wiki',   'group': 'global'},
    # ---- 其他: 站点抓取 / 杂项 (默认折叠) ----
    {'id': 'gequbao',  'client': 'GequbaoMusicClient',   'name': '歌曲宝',        'short': '歌曲宝', 'group': 'other'},
    {'id': 'yinyuedao','client': 'YinyuedaoMusicClient', 'name': '音乐岛',        'short': '音岛',   'group': 'other'},
    {'id': 'twot58',   'client': 'TwoT58MusicClient',    'name': '爱听音乐网',    'short': '爱听',   'group': 'other'},
    {'id': 'gequhai',  'client': 'GequhaiMusicClient',   'name': '歌曲海',        'short': '歌海',   'group': 'other'},
    {'id': 'livepoo',  'client': 'LivePOOMusicClient',   'name': '力音',          'short': '力音',   'group': 'other'},
    {'id': 'mitu',     'client': 'MituMusicClient',      'name': '米兔音乐',      'short': '米兔',   'group': 'other'},
    {'id': 'fangpi',   'client': 'FangpiMusicClient',    'name': '放屁音乐',      'short': '放屁',   'group': 'other'},
    {'id': 'xiageba',  'client': 'XiagebaMusicClient',   'name': '下歌吧',        'short': '下歌吧', 'group': 'other'},
    {'id': 'kkws',     'client': 'KKWSMusicClient',      'name': '开开无损音乐',  'short': '开开',   'group': 'other'},
    {'id': 'fivesong', 'client': 'FiveSongMusicClient',  'name': '5Song无损音乐', 'short': '5Song',  'group': 'other'},
    {'id': 'buguyy',   'client': 'BuguyyMusicClient',    'name': '布谷音乐',      'short': '布谷',   'group': 'other'},
    {'id': 'htqyy',    'client': 'HTQYYMusicClient',     'name': '好听轻音乐网',  'short': '好听',   'group': 'other'},
    {'id': 'yinyueku', 'client': 'YinyuekuMusicClient',  'name': '音乐库网',      'short': '音乐库', 'group': 'other'},
    {'id': 'itingwa',  'client': 'ITingWaMusicClient',   'name': '听蛙纯音乐网',  'short': '听蛙',   'group': 'other'},
    {'id': 'liziyy',   'client': 'LiziYYMusicClient',    'name': '梨子音乐',      'short': '梨子',   'group': 'other'},
    {'id': 'mgmp3',    'client': 'MGMP3MusicClient',     'name': '木瓜音乐',      'short': '木瓜',   'group': 'other'},
    {'id': 'sgogo',    'client': 'SgogoMusicClient',     'name': '搜歌网',        'short': '搜歌',   'group': 'other'},
    {'id': 'xmfwav',   'client': 'XMFWAVMusicClient',    'name': '小蜜蜂音乐网',  'short': '蜜蜂',   'group': 'other'},
]
PLATFORM_MAP = {p['id']: p for p in PLATFORMS}


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        with contextlib.suppress(Exception):
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8')) or {})
    return cfg


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


SETTINGS = load_config()
if not CONFIG_PATH.exists(): save_config(SETTINGS)


def touch_download_dir():
    with contextlib.suppress(Exception): os.makedirs(SETTINGS['download_dir'], exist_ok=True)


touch_download_dir()

'''---------------- library patch: single-file-per-song by default ----------------'''

from musicdl.modules import BuildMusicClient, LoggerHandle  # noqa: E402
from musicdl.modules.utils import SongInfo, SongInfoUtils  # noqa: E402

_ORIGINAL_SAVELRCTOFILE = SongInfoUtils.savelrctofile


def _savelrc_sidecar_aware(audio_path, lyrics_text, *, overwrite: bool = False) -> bool:
    '''default OFF: keep lyrics embedded only, no extra .lrc file next to the audio.'''
    if not SETTINGS.get('save_lrc_sidecar'): return False
    return _ORIGINAL_SAVELRCTOFILE(audio_path, lyrics_text, overwrite=overwrite)


SongInfoUtils.savelrctofile = staticmethod(_savelrc_sidecar_aware)

'''---------------- musicdl client pool ----------------'''

_logger = LoggerHandle()
_clients: dict = {}
_client_lock = threading.Lock()


def get_client(platform_id: str):
    platform_id = (platform_id or '').strip().lower()
    if platform_id not in PLATFORM_MAP: raise KeyError(f'unknown platform "{platform_id}"')
    with _client_lock:
        client = _clients.get(platform_id)
        if client is not None: return client
        meta = PLATFORM_MAP[platform_id]
        # ⚠️ DO NOT inject personal cookies into these direct-connection clients.
        # musicdl gates its third-party mirror parsers on cookie identity:
        #   netease.py — a non-default cookie skips the mirror parser entirely
        #   kuwo.py    — any cookie disables the third-party resolution chain
        # The direct channels' high-spec output (netease quasi-master 37.8 MB/min)
        # comes from those cookie-free mirror APIs; adding cookies would silently
        # downgrade them. VIP benefits belong to the kwqq-API sources only.
        client = BuildMusicClient(module_cfg={
            'type': meta['client'], 'work_dir': SETTINGS['download_dir'],
            'search_size_per_source': int(SETTINGS['platform_defaults'].get(platform_id, 5)),
            'search_size_per_page': 30, 'strict_limit_search_size_per_page': True,
            'auto_set_proxies': False, 'random_update_ua': False, 'max_retries': 3,
            'maintain_session': False, 'logger_handle': _logger, 'disable_print': True,
            'default_search_cookies': {}, 'default_download_cookies': {}, 'default_parse_cookies': {},
        })
        _clients[platform_id] = client
        return client


'''---------------- kuwo VIP encrypted-master path (cookie-gated + QMC decrypt) ----------------'''

_qmc_decryptor_cls = None


def _load_qmc_decryptor():
    """lazy-load scripts/kuwo_qmc_decryptor.py (no package __init__ there)."""
    global _qmc_decryptor_cls
    if _qmc_decryptor_cls is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'kuwo_qmc_decryptor', _REPO_ROOT / 'scripts' / 'kuwo_qmc_decryptor.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _qmc_decryptor_cls = mod.KuwoQmcDecryptor
    return _qmc_decryptor_cls


def kuwo_vip_enabled() -> bool:
    return bool(SETTINGS.get('kuwo_vip_cookie'))


def kuwo_vip_resolve(song_id: str):
    """VIP cookie path: mobi.s convert_url2 @ 4000kflac -> encrypted mgg url + ekey."""
    cookie = SETTINGS.get('kuwo_vip_cookie') or ''
    if not cookie: return None
    try:
        from musicdl.modules.utils.kuwoutils import KuwoMusicClientUtils
        client = get_client('kuwo_direct')
        query = ('user=0&corp=kuwo&source=kwplayer_ar_5.1.0.0_B_jiakong_vh.apk'
                 '&p2p=1&type=convert_url2&sig=0&br=4000kflac&format=4000kflac&rid=' + str(song_id))
        resp = client.get(
            'http://mobi.kuwo.cn/mobi.s?f=kuwo&q=' + KuwoMusicClientUtils.encryptquery(query),
            headers={'user-agent': 'okhttp/3.10.0', 'Cookie': cookie}, timeout=20)
        text = resp.text or ''
        fields = {}
        for kv in text.replace('\n', '&').split('&'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                fields[k.strip()] = v.strip()
        url = fields.get('url') or ''
        ekey = fields.get('ekey') or fields.get('kgekey') or ''
        if url.startswith('http') and ekey:
            return {'url': url, 'ekey': ekey}
        return None
    except Exception:
        return None


def qmc_decrypt_file(encrypted_path: str, ekey: str) -> str:
    """decrypt in place next to the source file; returns the plaintext path (.flac)."""
    src = Path(encrypted_path)
    out = src.with_suffix('.flac')
    _load_qmc_decryptor().decrypt(str(src), ekey, str(out))
    src.unlink(missing_ok=True)
    return str(out)

'''---------------- kwqq-api client (six sources backed by the NAS service) ----------------'''

import requests  # noqa: E402


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


# platform quality tags that describe a LOSSY tier (per-source native naming)
_LOSSY_TAG_RE = re.compile(r'mp3|standard|exhigh|\b128\b|\b320\b|\bpq\b|\bhq\b', re.I)
# sources whose platform_tag faithfully reflects the delivered file (qq's third-party
# chain frequently upgrades the request, so its annotation must not trigger the guard)
_TAG_TRUSTED_SOURCES = {'kuwo', 'netease', 'kugou', 'migu', 'qianqian'}


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


_dl_client = None
_dl_client_lock = threading.Lock()


def get_lib_downloader():
    '''platform-agnostic BaseMusicClient used to fetch API-resolved urls & write tags.'''
    global _dl_client
    with _dl_client_lock:
        if _dl_client is None:
            from musicdl.modules.sources.base import BaseMusicClient
            touch_download_dir()
            _dl_client = BaseMusicClient(work_dir=SETTINGS['download_dir'], disable_print=True,
                                         logger_handle=_logger, max_retries=3, maintain_session=False)
        return _dl_client


def search_platform_sync(platform_id: str, keyword: str, limit: int) -> list:
    meta = PLATFORM_MAP[platform_id]
    if meta.get('group') == 'api':                     # kwqq-api backed sources
        return api_search_sync(platform_id, keyword, limit)
    client = get_client(platform_id)
    limit = max(1, min(int(limit), int(SETTINGS['max_limit_per_source'])))
    client.search_size_per_source = limit          # per-search dynamic limit (per subsource for aggregators)
    client.search_size_per_page = max(10, min(limit, 30))
    if meta.get('group') == 'agg':                 # apply UI-selected aggregator subsource whitelist
        subs = (SETTINGS.get('platform_subsources') or {}).get(platform_id)
        if subs: client.allowed_music_sources = list(subs)
    song_infos = client.search(keyword=keyword, num_threadings=min(limit, 5), persist_results=False,
                               main_process_context=ProgressStub()) or []
    # library only uses search_size_per_source for paging; enforce the hard cap here
    valid = [info for info in song_infos if isinstance(info, SongInfo)]
    return valid[:limit]

'''---------------- helpers: quality tiers / readable naming / dedupe ----------------'''

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
PLATFORM_TAG_TIER = {
    # kuwo (nmobi br 档, 匿名直出)
    '20900kmflac': 'master', 'master': 'master',
    'surround51': 'surround51', '20501kmflac': 'surround51',
    '2000kflac': 'lossless', 'flac': 'lossless',
    '320kmp3': '320k', '320': '320k', '128kmp3': '128k', '128': '128k',
    # kugou (quality 档, 概念版 cookie)
    'high': 'hires',
    # netease (granted level, 88VIP)
    'jymaster': 'master', 'jyeffect': 'hires', 'sky': 'hires', 'dolby': 'hires',
    'hires': 'hires', 'lossless': 'lossless', 'exhigh': '320k', 'standard': '128k',
}
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


# in-memory store of the latest search results (key -> SongInfo)
RESULT_STORE: dict = {}
STORE_LOCK = threading.Lock()

'''---------------- progress stub replacing rich.Progress ----------------'''


class _TaskRec:
    __slots__ = ('completed', 'total')

    def __init__(self, total): self.completed, self.total = 0, total


class ProgressStub:
    '''covers every progress.* usage inside base._download and HLSDownloader.'''

    def __init__(self, on_update=None):
        self.tasks: dict[int, _TaskRec] = {}
        self.on_update = on_update

    def add_task(self, description='', total=None, **fields) -> int:
        task_id = len(self.tasks) + 1
        self.tasks[task_id] = _TaskRec(total)
        return task_id

    def update(self, task_id, total=None, completed=None, advance=None, description=None, **fields):
        rec = self.tasks.get(task_id)
        if rec is None: return
        if total is not None: rec.total = total
        if completed is not None: rec.completed = completed
        if advance: rec.completed += advance
        self.on_update and self.on_update(rec.completed, rec.total)

    def advance(self, task_id, advance=1):
        rec = self.tasks.get(task_id)
        if rec is None: return
        rec.completed += advance
        self.on_update and self.on_update(rec.completed, rec.total)


'''---------------- download engine ----------------'''


class DownloadEngine:
    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self.tasks_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=max(1, int(SETTINGS['concurrency'])), thread_name_prefix='webgui-dl')

    @staticmethod
    def _rank(item: dict, pref: str) -> int:
        order = QUALITY_PREF_RANKS.get(pref, QUALITY_PREF_RANKS['any'])
        return order.index(item['quality_tier']) if item['quality_tier'] in order else len(order)

    def create_task(self, keys: list, quality_pref: str, dedupe: bool) -> dict:
        task_id = uuid.uuid4().hex[:12]
        with STORE_LOCK:
            missing = [k for k in keys if k not in RESULT_STORE]
            stored = {k: RESULT_STORE[k] for k in keys if k in RESULT_STORE}
        if missing:
            raise KeyError(f'部分搜索结果已过期，请重新搜索: {", ".join(missing[:5])}')
        serialized = {}
        for k, info in stored.items():
            pid = info.source if info.source in PLATFORM_MAP else k.split(':', 1)[0]
            serialized[k] = {**serialize_item(k, info, pid), '_info': info}
        # cross-platform duplicate folding, two-level:
        #   L1 same normalized song (title+version words+lead artist)
        #   L2 same normalized album — different albums may be different masters /
        #      remasters, so they are kept as independent candidates unless one side
        #      has no album info at all.
        def _album_norm(item) -> str:
            a = re.sub(r'[（(【\[].*?[)）\]】]', '', str(item['_info'].album or ''))
            return re.sub(r"[\s'+·～~!@#$%^&*_+=`,.?;:\"\u2018\u2019\u201c\u201d]+", '', a).lower()

        skipped_reason: dict[str, str] = {}
        if dedupe:
            groups: dict[str, list] = {}
            for k in keys: groups.setdefault(serialized[k]['dedupe_key'], []).append(k)
            for group in groups.values():
                # L2 split by album within the same-song cluster; entries without an
                # album join the largest known-album cluster (no evidence to differ).
                by_album: dict[str, list] = {}
                for k in group:
                    by_album.setdefault(_album_norm(serialized[k]), []).append(k)
                if len(by_album) > 1 and '' in by_album:
                    blanks = by_album.pop('')
                    if by_album:
                        biggest = max(by_album.values(), key=len)
                        biggest.extend(blanks)
                    else:
                        by_album[''] = blanks
                for cluster in by_album.values():
                    # two-level pick: quality-tier rank first, then larger payload
                    # (more data == higher real spec within the same tier), then stable id
                    best = min(cluster, key=lambda k: (
                        self._rank(serialized[k], quality_pref),
                        -(serialized[k]['file_size_bytes'] or 0),
                        k))
                    for k in cluster:
                        if k != best:
                            skipped_reason[k] = f'同曲同专辑已有更优版本({serialized[best]["source"]})'
        items = []
        for idx, k in enumerate(keys):
            s = serialized[k]
            if k in skipped_reason: status, error = 'skipped', skipped_reason[k]
            elif s['suspect']:
                if s['quality_tier'] in {'master', 'surround51', 'hires', 'lossless'}:
                    reason = f"疑似假无损({s.get('mbpm')}MB/分钟 < {LOSSLESS_MBPM_FLOOR})"
                else:
                    reason = f"疑似假质量({fmt_mb(s['file_size_bytes'])} 低于{s['quality_tier']}下限)"
                status, error = 'skipped', reason
            elif quality_pref == 'lossless_only' and s['quality_tier'] not in {'master', 'surround51', 'hires', 'lossless'}:
                status, error = 'skipped', '音质偏好为仅无损'
            else: status, error = 'queued', ''
            items.append({
                'item_id': f'{task_id}-{idx}', 'key': k, 'song_name': s['song_name'],
                'singers': s['singers'], 'album': s['album'], 'source': s['source'], 'ext': s['ext'],
                'quality_tier': s['quality_tier'], 'status': status, 'error': error,
                'progress': 100.0 if status == 'skipped' else 0, 'speed': '',
                'saved_path': '', 'downloaded_bytes': 0, 'total_bytes': s['file_size_bytes'] or 0,
                '_info': s['_info'],
            })
        task = {'task_id': task_id, 'created_at': time.strftime('%H:%M:%S'), 'quality_pref': quality_pref,
                'dedupe': dedupe, 'cancel_flag': False, 'items': items, 'status': 'running'}
        with self.tasks_lock:
            self.tasks[task_id] = task
            finished = [t for t, v in self.tasks.items() if v['status'] in {'completed', 'partial', 'cancelled'} and t != task_id]
            for old in finished[:-10]: self.tasks.pop(old, None)
        for item in items:
            if item['status'] == 'queued': self.pool.submit(self._run_item, task_id, item['item_id'])
        self._refresh_status(task_id)
        return self.snapshot(task_id)

    def _run_item(self, task_id: str, item_id: str):
        task = self.tasks.get(task_id)
        item = next((i for i in task['items'] if i['item_id'] == item_id), None) if task else None
        if not item or item['status'] != 'queued': return
        if task['cancel_flag']:
            item['status'] = 'cancelled'; self._refresh_status(task_id); return
        item['status'] = 'downloading'
        last_speed_tick, start_ts = [time.time()], time.time()

        def on_progress(completed, total):
            item['downloaded_bytes'], item['total_bytes'] = completed, total or item['total_bytes']
            if item['total_bytes']:
                item['progress'] = round(min(99.0, completed / item['total_bytes'] * 100.0), 1)
                now = time.time()
                if now - last_speed_tick[0] > 0.8 and completed > 0:
                    speed = completed / max(now - start_ts, 1e-6)
                    item['speed'] = f'{speed / 1024 / 1024:.2f} MB/s'
                    last_speed_tick[0] = now

        save_path = ''
        try:
            info = copy.deepcopy(item.pop('_info'))
            is_api = getattr(info, 'api_id', None) is not None
            vip_ekey = None
            if not is_api and not info.with_valid_download_url: raise RuntimeError('下载链接无效或已过期，请重新搜索')
            # kuwo VIP: encrypted 4000kflac master tier (cookie-gated); falls back to
            # the normal anonymous chain below when the VIP resolve yields nothing.
            if getattr(info, 'source', '') == 'kuwo_direct' and kuwo_vip_enabled() and info.identifier:
                # kuwo VIP: encrypted 4000kflac master tier; falls back to the normal
                # anonymous chain below when the VIP resolve yields nothing.
                vip = kuwo_vip_resolve(str(info.identifier))
                if vip:
                    info.download_url = vip['url']; info.ext = 'mgg'
                    vip_ekey = vip['ekey']
                    info.with_valid_download_url = True
                    item['platform_tag'] = 'VIP·4000kflac'
            if is_api:
                # two-stage: resolve a fresh direct url (quality per preference), then fetch via generic downloader
                api_resolve_into(info, task['quality_pref'])
                # kuwo zhenpin (anonymous master/surround51): resolve already fetched url+ekey
                if not vip_ekey and (info.api_extra or {}).get('ekey') and info.download_url:
                    vip_ekey = info.api_extra['ekey']
                    native = str(getattr(info, 'platform_tag', '') or '')
                    info.ext = 'mflac' if 'mflac' in native else 'mgg'
                    item['platform_tag'] = '臻品·加密'
                if getattr(info, 'api_fallback_note', None): item['api_note'] = info.api_fallback_note
                item['platform_tag'] = info.platform_tag   # surface the granted tier in the queue view
                info.with_valid_download_url = True
            ext = str(info.ext or 'mp3').lower().lstrip('.')
            pid = info.source if info.source in PLATFORM_MAP else item['source']
            stem = render_stem(SETTINGS['naming_template'], info, pid)
            save_path = allocate_path(stem, ext)
            info.work_dir = str(Path(save_path).parent)
            info._save_path = save_path
            stub = ProgressStub(on_progress)
            progress_id = stub.add_task(description=item['song_name'], total=None)
            downloaded = []
            client = get_lib_downloader() if is_api else get_client(pid)
            client._download(info, {}, downloaded, stub, progress_id, True)
            if vip_ekey and downloaded:
                decrypted = qmc_decrypt_file(str(downloaded[0].save_path), vip_ekey)
                downloaded[0]._save_path = downloaded[0].save_path = decrypted
                was_tag = str(item.get('platform_tag') or '')
                item['platform_tag'] = ('VIP·母带解密' if 'VIP' in was_tag else '臻品·已解密')
                # 解密后按通道定档: zhenpin 匿名 20900kmflac=master(192k/24bit 实测)、
                # 20501kmflac=surround51(6ch)；VIP cookie 4000kflac 采样率未实测, 保守 hires
                item['quality_tier'] = ('hires' if 'VIP' in was_tag else
                                        ('surround51' if 'surround51' in was_tag else 'master'))
            if not downloaded: raise RuntimeError('下载失败（链接可能已过期），请重新搜索后再试')
            final = downloaded[0]
            real_spec = ''
            with contextlib.suppress(Exception):
                sr, br = getattr(final, 'samplerate', None), getattr(final, 'bitrate', None)
                if sr: real_spec = f'{round(sr / 1000, 1)}kHz' + (f' / {int(br)}kbps 实测' if br else '')
            item.update({'status': 'success', 'progress': 100.0, 'speed': '',
                         'saved_path': str(final.save_path), 'real_spec': real_spec})
        except Exception as err:
            item['status'], item['error'], item['speed'] = 'failed', str(err)[:300], ''
            with contextlib.suppress(Exception):  # remove broken partial file so retry starts clean
                if save_path:
                    path = Path(save_path)
                    if path.exists() and (not item['total_bytes'] or path.stat().st_size < item['total_bytes']): path.unlink()
        finally:
            item.pop('_info', None)
            self._refresh_status(task_id)

    def cancel_task(self, task_id: str) -> dict:
        task = self.tasks.get(task_id)
        if not task: raise KeyError(f'unknown task {task_id}')
        task['cancel_flag'] = True
        for item in task['items']:
            if item['status'] == 'queued':
                item['_info'] = None; item['status'] = 'cancelled'; item['error'] = '已取消'
            elif item['status'] == 'downloading': item['status'] = 'cancelling'
        self._refresh_status(task_id)
        return self.snapshot(task_id)

    def retry_item(self, task_id: str, item_id: str) -> dict:
        task = self.tasks.get(task_id)
        if not task: raise KeyError(f'unknown task {task_id}')
        item = next((i for i in task['items'] if i['item_id'] == item_id), None)
        if not item: raise KeyError(f'unknown item {item_id}')
        if item['status'] not in {'failed', 'cancelled', 'cancelling'}: raise ValueError('仅失败或已取消的条目可重试')
        with STORE_LOCK:
            valid = RESULT_STORE.get(item['key'])
        if valid is None or not valid.with_valid_download_url: raise RuntimeError('原搜索结果已失效，请重新搜索后勾选下载')
        item.update({'status': 'queued', 'error': '', 'progress': 0, 'speed': '', '_info': valid})
        self.pool.submit(self._run_item, task_id, item_id)
        return self.snapshot(task_id)

    def _refresh_status(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task: return
        statuses = {i['status'] for i in task['items']}
        if statuses <= {'success', 'skipped'}: task['status'] = 'completed'
        elif 'downloading' in statuses or 'queued' in statuses: task['status'] = 'running'
        elif 'cancelling' in statuses: task['status'] = 'cancelling'
        elif 'failed' in statuses or 'cancelled' in statuses: task['status'] = 'partial'
        else: task['status'] = 'completed'

    def snapshot(self, task_id: str) -> dict:
        task = self.tasks.get(task_id)
        if not task: raise KeyError(f'unknown task {task_id}')
        items = [{k: v for k, v in i.items() if not k.startswith('_')} for i in task['items']]
        counts = {}
        for i in items: counts[i['status']] = counts.get(i['status'], 0) + 1
        return {'task_id': task_id, 'created_at': task['created_at'], 'status': task['status'],
                'quality_pref': task['quality_pref'], 'dedupe': task['dedupe'],
                'counts': counts, 'items': items}

    def list_tasks(self) -> list:
        with self.tasks_lock:
            ids = list(self.tasks.keys())[-20:]
        return [self.snapshot(t) for t in reversed(ids)]


engine = DownloadEngine()

'''---------------- fastapi app ----------------'''

app = FastAPI(title='musicdl-webgui', version='1.0.0', description='Easy web GUI on top of musicdl')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])


@app.middleware('http')
async def api_key_guard(request: Request, call_next):
    api_key = SETTINGS.get('api_key') or ''
    if api_key and request.url.path != '/healthz':
        provided = request.headers.get('x-api-key', '')
        if not provided:
            auth = request.headers.get('authorization', '')
            if auth.startswith('Basic '):
                import base64
                with contextlib.suppress(Exception):
                    provided = base64.b64decode(auth[6:]).decode('utf-8', errors='ignore').split(':', 1)[0]
        if provided != api_key:
            return JSONResponse({'code': 401, 'msg': 'unauthorized'}, status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="webgui"'})
    return await call_next(request)


class SearchBody(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=120)
    sources: dict = Field(..., description='{"qq": 5, "kuwo": 3} per-source limits')


class DownloadBody(BaseModel):
    keys: list = Field(..., min_length=1)
    quality_pref: str = Field(default=SETTINGS['quality_pref_default'])
    dedupe: bool = Field(default=True)


class RetryBody(BaseModel):
    item_id: str


class ResolveBody(BaseModel):
    keys: list = Field(..., min_length=1)
    quality_pref: str = Field(default=SETTINGS['quality_pref_default'])


@app.post('/api/resolve')
async def resolve_items(body: ResolveBody):
    '''pre-resolve pending kwqq-api items (per-song /song/url) so the UI can show the real
    ext/size/tier before downloading; server-side URL cache (600s) makes later downloads free.'''
    keys = body.keys[:50]
    if body.quality_pref not in QUALITY_PREF_RANKS:
        return JSONResponse({'code': 400, 'msg': f'quality_pref 必须是 {list(QUALITY_PREF_RANKS)} 之一'}, status_code=200)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(3)

    async def one(key: str):
        with STORE_LOCK:
            info = RESULT_STORE.get(key)
        if info is None or getattr(info, 'api_id', None) is None:
            return {'key': key, 'resolve_error': '条目不存在或非 API 来源'}
        async with sem:
            try:
                await asyncio.wait_for(loop.run_in_executor(None, api_resolve_into, info, body.quality_pref), timeout=45)
            except Exception as err:
                # metadata backfill inside api_resolve_into still counts: keep the
                # enriched entry so the UI retains duration/size even on url failures
                with STORE_LOCK: RESULT_STORE[key] = info
                entry = serialize_item(key, info, info.source or key.split(':', 1)[0])
                entry['resolve_error'] = str(err)[:180]
                return entry
        with STORE_LOCK:
            RESULT_STORE[key] = info
        return serialize_item(key, info, info.source or key.split(':', 1)[0])

    results = await asyncio.gather(*[one(k) for k in keys])
    ok, failed = [], []
    for r in results:
        if not r: continue
        (failed.append({'key': r['key'], 'error': r['resolve_error'], **{k: v for k, v in r.items() if k not in {'resolve_error'}}})
         if r.get('resolve_error') else ok.append(r))
    return {'code': 200, 'msg': 'ok', 'data': {'items': ok, 'failed': failed}}


class ConfigBody(BaseModel):
    download_dir: str | None = None
    naming_template: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=8)
    search_timeout_s: int | None = Field(default=None, ge=10, le=180)
    save_lrc_sidecar: bool | None = None
    quality_guard: bool | None = None
    quality_pref_default: str | None = None
    dedupe_default: bool | None = None
    api_key: str | None = None
    platform_defaults: dict | None = None
    platform_subsources: dict | None = None
    kuwo_vip_cookie: str | None = None


@app.get('/healthz')
async def healthz(): return {'code': 200, 'msg': 'up', 'data': {'ts': int(time.time())}}


@app.get('/api/config')
async def get_config():
    return {'code': 200, 'msg': 'ok', 'data': {
        'download_dir': SETTINGS['download_dir'], 'naming_template': SETTINGS['naming_template'],
        'concurrency': SETTINGS['concurrency'], 'search_timeout_s': SETTINGS['search_timeout_s'],
        'save_lrc_sidecar': SETTINGS['save_lrc_sidecar'], 'quality_pref_default': SETTINGS['quality_pref_default'],
        'dedupe_default': SETTINGS['dedupe_default'], 'max_limit_per_source': SETTINGS['max_limit_per_source'],
        'quality_guard': SETTINGS.get('quality_guard', True),
        'lossless_mbpm_floor': LOSSLESS_MBPM_FLOOR, 'master_mbpm': MASTER_MBPM,
        'mp3_size_floors_mb': {'320k': 5, '128k': 2},
        'has_api_key': bool(SETTINGS.get('api_key')), 'config_path': str(CONFIG_PATH),
        'kwqq_api_base': SETTINGS['kwqq_api_base'], 'kwqq_api_online': api_online(),
        'kuwo_vip_enabled': kuwo_vip_enabled(),
        'platform_defaults': dict(SETTINGS['platform_defaults']),
        'platform_subsources': dict(SETTINGS.get('platform_subsources') or {}),
        'platforms': [{**p, 'default_limit': SETTINGS['platform_defaults'].get(p['id'], 5)} for p in PLATFORMS],
    }}


@app.put('/api/config')
async def put_config(body: ConfigBody):
    changed = []
    if body.download_dir:
        SETTINGS['download_dir'] = body.download_dir.strip(); touch_download_dir(); changed.append('download_dir')
    if body.naming_template is not None:
        template = body.naming_template.strip() or DEFAULT_CONFIG['naming_template']
        if '{title}' not in template: return JSONResponse({'code': 400, 'msg': '命名模板必须包含 {title}'}, status_code=200)
        SETTINGS['naming_template'] = template; changed.append('naming_template')
    if body.concurrency is not None: SETTINGS['concurrency'] = body.concurrency; changed.append('concurrency (重启后生效)')
    if body.search_timeout_s is not None: SETTINGS['search_timeout_s'] = body.search_timeout_s; changed.append('search_timeout_s')
    if body.save_lrc_sidecar is not None: SETTINGS['save_lrc_sidecar'] = body.save_lrc_sidecar; changed.append('save_lrc_sidecar')
    if body.quality_guard is not None: SETTINGS['quality_guard'] = body.quality_guard; changed.append('quality_guard')
    if body.quality_pref_default:
        if body.quality_pref_default not in QUALITY_PREF_RANKS:
            return JSONResponse({'code': 400, 'msg': f'quality_pref_default 必须是 {list(QUALITY_PREF_RANKS)} 之一'}, status_code=200)
        SETTINGS['quality_pref_default'] = body.quality_pref_default; changed.append('quality_pref_default')
    if body.dedupe_default is not None: SETTINGS['dedupe_default'] = body.dedupe_default; changed.append('dedupe_default')
    if body.api_key is not None: SETTINGS['api_key'] = body.api_key.strip(); changed.append('api_key')
    if body.platform_defaults is not None:
        SETTINGS['platform_defaults'] = {k: max(1, min(int(v), SETTINGS['max_limit_per_source']))
                                         for k, v in body.platform_defaults.items() if k in PLATFORM_MAP}
        changed.append('platform_defaults')
    if body.kuwo_vip_cookie is not None:
        SETTINGS['kuwo_vip_cookie'] = body.kuwo_vip_cookie.strip(); changed.append('kuwo_vip_cookie')
    if body.platform_subsources is not None:
        clean_subs = {}
        for pid, subs in (body.platform_subsources or {}).items():
            meta = PLATFORM_MAP.get(pid)
            if not meta or not meta.get('subsources'): continue
            valid = [x['id'] for x in meta['subsources']]
            clean_subs[pid] = [s for s in subs if s in valid] or valid
        SETTINGS['platform_subsources'] = clean_subs; changed.append('platform_subsources')
    if changed: save_config(SETTINGS)
    return {'code': 200, 'msg': f'updated: {", ".join(changed) or "nothing"}', 'data': {'changed': changed}}


@app.post('/api/search')
async def search(body: SearchBody):
    unknown = [s for s in body.sources if s not in PLATFORM_MAP]
    if unknown: return JSONResponse({'code': 404, 'msg': f'未知平台: {unknown}'}, status_code=200)
    keyword = body.keyword.strip()
    loop = asyncio.get_running_loop()

    async def run_one(pid: str, limit: int):
        try:
            infos = await asyncio.wait_for(loop.run_in_executor(None, search_platform_sync, pid, keyword, int(limit)),
                                           timeout=int(SETTINGS['search_timeout_s']))
            return pid, infos, None
        except Exception as err:
            return pid, [], f'{type(err).__name__}: {str(err)[:160]}'

    outcomes = await asyncio.gather(*[run_one(pid, limit) for pid, limit in body.sources.items()])
    results, failed, new_store = [], {}, {}
    for pid, infos, error in outcomes:
        if error: failed[pid] = error
        for info in infos:
            key = f'{pid}:{uuid.uuid4().hex[:8]}'
            entry = serialize_item(key, info, pid)
            results.append(entry)
            if entry['has_url']: new_store[key] = info
    with STORE_LOCK:
        if len(RESULT_STORE) > 800: RESULT_STORE.clear()   # simple capacity cap
        RESULT_STORE.update(new_store)
    results.sort(key=lambda r: (not r['has_url'], QUALITY_ORDER.get(r['quality_tier'], 9)))
    return {'code': 200, 'msg': 'ok', 'data': {'keyword': keyword, 'total': len(results), 'items': results, 'failed': failed}}


@app.get('/api/search/stream')
async def search_stream(request: Request, keyword: str = Query(..., min_length=1), sources: str = Query(...)):
    '''progressive search: one SSE event per finished platform so the UI can show live progress.'''
    async def event_stream():
        try:
            src_map = {k: int(v) for k, v in json.loads(sources).items() if k in PLATFORM_MAP and int(v) >= 1}
        except Exception:
            yield f'data: {json.dumps({"type": "done", "total": 0, "failed": {"_": "sources 参数非法"}}, ensure_ascii=False)}\n\n'; return
        if not src_map:
            yield f'data: {json.dumps({"type": "done", "total": 0, "failed": {"_": "无有效平台"}}, ensure_ascii=False)}\n\n'; return
        loop = asyncio.get_running_loop()

        async def run_one(pid: str, limit: int):
            try:
                infos = await asyncio.wait_for(loop.run_in_executor(None, search_platform_sync, pid, keyword.strip(), int(limit)),
                                               timeout=int(SETTINGS['search_timeout_s']))
                return pid, infos, None
            except Exception as err:
                return pid, [], f'{type(err).__name__}: {str(err)[:160]}'

        total_sent, failed_all = 0, {}
        coros = [run_one(pid, limit) for pid, limit in src_map.items()]
        for coro in asyncio.as_completed(coros):
            pid, infos, error = await coro
            entries = []
            for info in infos:
                key = f'{pid}:{uuid.uuid4().hex[:8]}'
                entry = serialize_item(key, info, pid)
                entries.append(entry)
                if entry['has_url']:
                    with STORE_LOCK:
                        if len(RESULT_STORE) > 800: RESULT_STORE.clear()
                        RESULT_STORE[key] = info
            total_sent += len(entries)
            if error: failed_all[pid] = error
            payload = {'type': 'source_done', 'source': pid, 'count': len(entries),
                       'failed': error, 'items': entries}
            yield f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'
        yield f'data: {json.dumps({"type": "done", "total": total_sent, "failed": failed_all}, ensure_ascii=False)}\n\n'

    return StreamingResponse(event_stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/downloads')
async def create_download(body: DownloadBody):
    if body.quality_pref not in QUALITY_PREF_RANKS:
        return JSONResponse({'code': 400, 'msg': f'quality_pref 必须是 {list(QUALITY_PREF_RANKS)} 之一'}, status_code=200)
    try:
        snapshot = engine.create_task(body.keys, body.quality_pref, bool(body.dedupe))
    except KeyError as err:
        return JSONResponse({'code': 410, 'msg': str(err)}, status_code=200)
    except Exception as err:
        return JSONResponse({'code': 500, 'msg': f'{type(err).__name__}: {err}'}, status_code=500)
    return {'code': 200, 'msg': 'ok', 'data': snapshot}


@app.get('/api/tasks')
async def list_tasks(): return {'code': 200, 'msg': 'ok', 'data': engine.list_tasks()}


@app.get('/api/tasks/{task_id}')
async def get_task(task_id: str):
    try: return {'code': 200, 'msg': 'ok', 'data': engine.snapshot(task_id)}
    except KeyError: return JSONResponse({'code': 404, 'msg': 'task not found'}, status_code=200)


@app.post('/api/tasks/{task_id}/retry')
async def retry_item(task_id: str, body: RetryBody):
    try: return {'code': 200, 'msg': 'ok', 'data': engine.retry_item(task_id, body.item_id)}
    except (KeyError, ValueError, RuntimeError) as err:
        return JSONResponse({'code': 400, 'msg': str(err)}, status_code=200)


@app.delete('/api/tasks/{task_id}')
async def cancel_task(task_id: str):
    try: return {'code': 200, 'msg': 'ok', 'data': engine.cancel_task(task_id)}
    except KeyError: return JSONResponse({'code': 404, 'msg': 'task not found'}, status_code=200)


@app.get('/api/tasks/{task_id}/events')
async def task_events(task_id: str, request: Request):
    async def event_stream():
        ticks_after_done = 0
        while True:
            if await request.is_disconnected(): break
            try: snap = engine.snapshot(task_id)
            except KeyError:
                yield f'event: gone\ndata: {json.dumps({"task_id": task_id})}\n\n'; break
            yield f'data: {json.dumps(snap, ensure_ascii=False)}\n\n'
            if snap['status'] in {'completed', 'partial', 'cancelled'}:
                ticks_after_done += 1
                if ticks_after_done >= 3: break
            await asyncio.sleep(0.6)
    return StreamingResponse(event_stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


STATIC_DIR = _MODULE_DIR / 'static'


@app.get('/')
async def index(): return FileResponse(STATIC_DIR / 'index.html')


def main():
    parser = argparse.ArgumentParser(description='musicdl-webgui server')
    parser.add_argument('--host', default=SETTINGS['host'])
    parser.add_argument('--port', type=int, default=int(SETTINGS['port']))
    parser.add_argument('--download-dir', default=None, help='override & persist download directory')
    args = parser.parse_args()
    if args.download_dir:
        SETTINGS['download_dir'] = args.download_dir; touch_download_dir(); save_config(SETTINGS)
    print('=' * 64)
    print(f'musicdl-webgui   http://{args.host}:{args.port}')
    print(f'download dir  : {SETTINGS["download_dir"]}')
    print(f'naming        : {SETTINGS["naming_template"]}.<ext>')
    print(f'platforms     : {", ".join(p["name"] for p in PLATFORMS)}')
    print(f'lrc sidecar   : {"on" if SETTINGS["save_lrc_sidecar"] else "off (lyrics embedded)"}')
    print('=' * 64)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
