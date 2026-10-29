'''
Function:
    musicdl-webgui config layer: config path & defaults, the platform registry,
    and config load/save. Loaded read-only at import; the first-run config write
    and download-dir creation run in the FastAPI lifespan (app.py) instead of at
    import time (roadmap D1).
'''
import os
import sys
import json
import copy
import contextlib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = _REPO_ROOT
CONFIG_PATH = Path(os.environ.get('MUSICDL_WEBGUI_CONFIG', MODULE_DIR / 'config.json'))

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
    # K-05 strict source mode: when true the six-source in-process library fallback
    # (ADR-0001 frozen mode) is disabled; only kwqq-API sources may search/download.
    'kwqq_only': False,
    # completed-download outbox for Songloft S-08 (empty -> <download_dir>/.outbox)
    'outbox_dir': '',
    # bounded download queue: over-full task creation answers 503 instead of growing
    'max_queued_items': 200,
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
    {'id': 'heishan',  'client': 'HeishanMusicClient',   'name': '黑山·163cn',     'short': '黑山',   'group': 'other'},
    {'id': 'mitu',     'client': 'MituMusicClient',      'name': '米兔音乐',      'short': '米兔',   'group': 'other'},
    {'id': 'fangpi',   'client': 'FangpiMusicClient',    'name': '放屁音乐',      'short': '放屁',   'group': 'other'},
    {'id': 'xiageba',  'client': 'XiagebaMusicClient',   'name': '下歌吧',        'short': '下歌吧', 'group': 'other'},
    {'id': 'kkws',     'client': 'KKWSMusicClient',      'name': '开开无损音乐',  'short': '开开',   'group': 'other'},
    {'id': 'fivesong', 'client': 'FiveSongMusicClient',  'name': '5Song无损音乐', 'short': '5Song',  'group': 'other'},
    {'id': 'buguyy',   'client': 'BuguyyMusicClient',    'name': '布谷音乐',      'short': '布谷',   'group': 'other'},
    {'id': 'htqyy',    'client': 'HTQYYMusicClient',     'name': '好听轻音乐网',  'short': '好听',   'group': 'other'},
    {'id': 'yinyueku', 'client': 'YinyuekuMusicClient',  'name': '音乐库网',      'short': '音乐库', 'group': 'other'},
    {'id': 'leedodo',  'client': 'LeedodoMusicClient',   'name': 'Leedodo轻音乐',  'short': '轻音',   'group': 'other'},
    {'id': 'gequke',   'client': 'GequkeMusicClient',    'name': '歌曲客',        'short': '曲客',   'group': 'other'},
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
    return _apply_env(cfg)


# 容器部署用：compose 只注入差异项，避免把整份 config.json 塞进镜像或 compose
_ENV_OVERRIDES = {
    'MUSICDL_WEBGUI_DOWNLOAD_DIR': 'download_dir',
    'MUSICDL_WEBGUI_HOST': 'host',
    'MUSICDL_WEBGUI_PORT': 'port',
    'MUSICDL_WEBGUI_KWQQ_API_BASE': 'kwqq_api_base',
    'MUSICDL_WEBGUI_KWQQ_API_KEY': 'kwqq_api_key',
    'MUSICDL_WEBGUI_KWQQ_ONLY': 'kwqq_only',
    'MUSICDL_WEBGUI_OUTBOX_DIR': 'outbox_dir',
}


def _apply_env(cfg: dict) -> dict:
    for env, key in _ENV_OVERRIDES.items():
        v = os.environ.get(env)
        if v is None or v == '':
            continue
        if key == 'port':
            cfg[key] = int(v)
        elif key == 'kwqq_only':
            cfg[key] = v.strip().lower() in {'1', 'true', 'yes', 'on'}
        else:
            cfg[key] = v
    return cfg


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


# in-memory settings, loaded read-only at import (a pure file read). The first-run
# write-back and the download-dir creation are NOT done here anymore — they run in
# the app lifespan (app.py) at startup, replacing the old import-time side effects.
SETTINGS = load_config()


def touch_download_dir():
    with contextlib.suppress(Exception): os.makedirs(SETTINGS['download_dir'], exist_ok=True)
