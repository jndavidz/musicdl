'''
Function:
    musicdl in-process library layer: the SongInfoUtils.lrc_saver extension-point
    wiring (the single sanctioned library patch), the platform client pool with
    zero-cookie direct channels, the duck-typed ProgressStub feeding SSE, the
    kuwo VIP encrypted-master path (cookie-gated + QMC decrypt), the platform-
    agnostic lib downloader, and the search dispatch (kwqq-api vs lib direct).
'''
import threading
import contextlib
from pathlib import Path

from config import SETTINGS, PLATFORM_MAP, REPO_ROOT, touch_download_dir
from kwqq_api import api_search_sync

from musicdl.modules import BuildMusicClient, LoggerHandle
from musicdl.modules.utils import SongInfo, SongInfoUtils

_ORIGINAL_SAVELRCTOFILE = SongInfoUtils.savelrctofile


def _savelrc_sidecar_aware(audio_path, lyrics_text, *, overwrite: bool = False) -> bool:
    '''default OFF: keep lyrics embedded only, no extra .lrc file next to the audio.'''
    if not SETTINGS.get('save_lrc_sidecar'): return False
    return _ORIGINAL_SAVELRCTOFILE(audio_path, lyrics_text, overwrite=overwrite)


# batch-5 sanctioned extension point (songinfoutils.lrc_saver) — not a monkeypatch
SongInfoUtils.lrc_saver = staticmethod(_savelrc_sidecar_aware)

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


'''---------------- kuwo VIP encrypted-master path (cookie-gated + QMC decrypt) ----------------'''

_qmc_decryptor_cls = None


def _load_qmc_decryptor():
    """lazy-load scripts/kuwo_qmc_decryptor.py (no package __init__ there)."""
    global _qmc_decryptor_cls
    if _qmc_decryptor_cls is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'kuwo_qmc_decryptor', REPO_ROOT / 'scripts' / 'kuwo_qmc_decryptor.py')
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


'''---------------- lib downloader & search dispatch ----------------'''

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
