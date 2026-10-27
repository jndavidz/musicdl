'''
Function:
    download engine: the in-memory search-result store and dedupe win-source
    statistics (ADR-0001 review data), task creation with cross-platform
    two-level dedupe folding, threaded per-item downloads with progress and
    QMC decryption hooks, cancel/retry, and task snapshots for the API layer.
'''
import re
import os
import json
import copy
import time
import uuid
import threading
import contextlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from config import SETTINGS, PLATFORM_MAP, REPO_ROOT
from quality import (serialize_item, render_stem, allocate_path, fmt_mb, normkey_text,
                     QUALITY_PREF_RANKS, LOSSLESS_MBPM_FLOOR)
from kwqq_api import api_resolve_into, ApiSongInfo, seconds2hms
from library import (get_client, get_lib_downloader, ProgressStub,
                     kuwo_vip_enabled, kuwo_vip_resolve, qmc_decrypt_file,
                     search_platform_sync)

# in-memory store of the latest search results (key -> SongInfo)
RESULT_STORE: dict = {}
STORE_LOCK = threading.Lock()

'''dedupe win-source statistics (in-memory + periodic state-dir persistence, D3).
   Counts CONTESTED dedupe picks only: clusters where the same song+album had
   candidates from BOTH the api channel and the lib direct channel, and the
   two-level pick (tier rank -> larger payload) chose one side. This is the
   data behind the ADR-0001 re-review clause: if lib wins stay near zero over
   a monitoring window (with no API outage in it), the six-source lib channel
   can be deleted instead of converted to metadata-only search.'''
DEDUPE_STATS: dict = {'contested': 0, 'wins': {'api': 0, 'lib': 0}, 'by_origin_source': {}}
DEDUPE_STATS_LOCK = threading.Lock()

'''dedupe stats persistence (roadmap D3): the ADR-0001 monitoring window must survive
   restarts, so DEDUPE_STATS is flushed to the runtime state dir (XDG_STATE_HOME, repo
   convention `$PWD/.state`) at most every DEDUPE_SAVE_INTERVAL_S of dedupe activity,
   plus once on app shutdown (lifespan). File shape == /api/stats/dedupe `data`;
   a corrupt/missing file is silently ignored and stats rebuild from zero.'''
DEDUPE_STATS_PATH = Path(os.environ.get('XDG_STATE_HOME', str(REPO_ROOT / '.state'))) / 'dedupe_stats.json'
DEDUPE_SAVE_INTERVAL_S = 600
_dedupe_last_save = 0.0
_dedupe_save_due = False


def load_dedupe_stats() -> None:
    '''restore persisted dedupe stats at startup (called from app lifespan, not at import — D1).'''
    global _dedupe_last_save
    try:
        raw = json.loads(DEDUPE_STATS_PATH.read_text(encoding='utf-8'))
        wins = raw.get('wins') or {}
        by_src = raw.get('by_origin_source') or {}
        with DEDUPE_STATS_LOCK:
            DEDUPE_STATS['contested'] = max(0, int(raw.get('contested', 0)))
            DEDUPE_STATS['wins'] = {'api': max(0, int(wins.get('api', 0))),
                                    'lib': max(0, int(wins.get('lib', 0)))}
            DEDUPE_STATS['by_origin_source'] = {str(k): max(0, int(v))
                                                for k, v in by_src.items() if isinstance(v, (int, float))}
        _dedupe_last_save = time.time()
    except Exception:
        pass   # missing/corrupt file: silently rebuild the window from zero


def save_dedupe_stats() -> None:
    '''persist DEDUPE_STATS (same shape as /api/stats/dedupe data); silent on any failure.'''
    try:
        DEDUPE_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEDUPE_STATS_LOCK:
            data = {'contested': DEDUPE_STATS['contested'], 'wins': dict(DEDUPE_STATS['wins']),
                    'by_origin_source': dict(DEDUPE_STATS['by_origin_source'])}
        tmp = DEDUPE_STATS_PATH.with_name(DEDUPE_STATS_PATH.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(DEDUPE_STATS_PATH)   # atomic swap: readers never see a half-written file
    except Exception:
        pass


def _record_dedupe_win(cluster_items: list, best_item: dict) -> None:
    origins = {it['origin'] for it in cluster_items}
    if len(cluster_items) < 2 or not {'api', 'lib'} <= origins:
        return
    global _dedupe_save_due, _dedupe_last_save
    with DEDUPE_STATS_LOCK:
        DEDUPE_STATS['contested'] += 1
        origin = best_item['origin']
        DEDUPE_STATS['wins'][origin] += 1
        key = f'{origin}:{best_item["source"]}'
        DEDUPE_STATS['by_origin_source'][key] = DEDUPE_STATS['by_origin_source'].get(key, 0) + 1
        if not _dedupe_save_due and time.time() - _dedupe_last_save >= DEDUPE_SAVE_INTERVAL_S:
            _dedupe_save_due = True
    if _dedupe_save_due:
        _dedupe_save_due = False
        _dedupe_last_save = time.time()
        save_dedupe_stats()


'''download task persistence (roadmap D2): the queue survives a process restart.
   Direct urls expire (kwqq-api URL_CACHE_TTL = 10min), so only each item's identity
   is persisted — api channel: api_id + api_source; lib channel: platform + native
   identifier — and the worker re-resolves a fresh url before downloading. Items that
   were mid-flight keep their partial path in `_inflight` so a crash-restart can
   delete that partial file before re-downloading. Same atomic tmp+replace pattern
   and XDG_STATE_HOME location as the D3 dedupe counters.'''
TASKS_PATH = Path(os.environ.get('XDG_STATE_HOME', str(REPO_ROOT / '.state'))) / 'download_tasks.json'
MAX_PERSISTED_TASKS = 20
TERMINAL_ITEM_STATUSES = {'success', 'skipped', 'failed', 'cancelled'}
_tasks_write_lock = threading.Lock()


def _info_descriptor(info, platform_id: str) -> dict:
    '''identity-only snapshot of a candidate: enough to re-resolve a url after restart.'''
    desc = {
        'origin': 'api' if getattr(info, 'api_id', None) is not None else 'lib',
        'platform': platform_id,
        'song_name': str(info.song_name or ''), 'singers': str(info.singers or ''),
        'album': str(info.album or ''), 'ext': str(info.ext or '').lstrip('.'),
        'duration_s': getattr(info, 'duration_s', None),
        'file_size_bytes': getattr(info, 'file_size_bytes', None),
        'platform_tag': str(getattr(info, 'platform_tag', '') or ''),
        'cover_url': str(getattr(info, 'cover_url', '') or ''),
        'root_source': str(getattr(info, 'root_source', '') or ''),
    }
    if desc['origin'] == 'api':
        desc['api_id'] = str(getattr(info, 'api_id', '') or '')
        desc['api_source'] = str(getattr(info, 'api_source', '') or '')
        desc['api_extra'] = dict(getattr(info, 'api_extra', {}) or {})
    else:
        desc['identifier'] = str(getattr(info, 'identifier', '') or '')
    return desc


def _rehydrate_info(desc: dict):
    '''rebuild a runnable candidate from its descriptor; None when it can no longer be
       identified (the item then fails with a "search again" message instead of guessing).'''
    if not isinstance(desc, dict): return None
    if desc.get('origin') == 'api':
        if not desc.get('api_id') or not desc.get('api_source'): return None
        duration_s = desc.get('duration_s')
        return ApiSongInfo(
            song_name=desc.get('song_name') or '', singers=desc.get('singers') or '',
            album=desc.get('album') or '', ext=str(desc.get('ext') or '').lstrip('.'),
            file_size_bytes=desc.get('file_size_bytes'), duration_s=duration_s,
            duration=seconds2hms(duration_s), platform_tag=desc.get('platform_tag') or '',
            cover_url=desc.get('cover_url') or '', source=desc.get('platform') or '',
            root_source=desc.get('root_source') or '', download_url=None,
            api_id=str(desc['api_id']), api_source=str(desc['api_source']),
            api_extra=dict(desc.get('api_extra') or {}))
    platform = str(desc.get('platform') or '')
    if platform not in PLATFORM_MAP or not desc.get('song_name'): return None
    identifier = str(desc.get('identifier') or '')
    wanted = normkey_text(desc.get('song_name'), desc.get('singers'))
    ext = str(desc.get('ext') or '').lower().lstrip('.')
    queries = [str(desc['song_name'])]
    singers = str(desc.get('singers') or '').strip()
    if singers: queries.append(f"{desc['song_name']} {singers}")
    for query in queries:
        try:
            candidates = search_platform_sync(platform, query, 10)
        except Exception:
            continue
        if identifier:
            for cand in candidates:
                if str(getattr(cand, 'identifier', '') or '') == identifier and cand.with_valid_download_url:
                    return cand
        matches = [c for c in candidates
                   if normkey_text(c.song_name, c.singers) == wanted and c.with_valid_download_url]
        same_ext = [c for c in matches if ext and str(c.ext or '').lower().lstrip('.') == ext]
        hit = same_ext or matches
        if hit: return hit[0]
    return None


def _task_to_disk(task: dict) -> dict:
    return {
        'task_id': task['task_id'], 'created_at': task.get('created_at', ''),
        'quality_pref': task.get('quality_pref', 'any'), 'dedupe': bool(task.get('dedupe', True)),
        'cancel_flag': bool(task.get('cancel_flag', False)), 'status': task.get('status', 'running'),
        'items': [{k: v for k, v in item.items() if k != '_info'} for item in task['items']],
    }


def _write_tasks_file(tasks: list) -> None:
    '''atomic queue snapshot; silent on any failure (downloads must never break on IO).'''
    try:
        TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {'version': 1, 'saved_at': int(time.time()), 'tasks': tasks}
        tmp = TASKS_PATH.with_name(TASKS_PATH.name + '.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(TASKS_PATH)
    except Exception:
        pass


def _read_tasks_file() -> list:
    try:
        raw = json.loads(TASKS_PATH.read_text(encoding='utf-8'))
        tasks = raw.get('tasks') if isinstance(raw, dict) else None
        return tasks if isinstance(tasks, list) else []
    except Exception:
        return []


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
                    _record_dedupe_win([serialized[k] for k in cluster], serialized[best])
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
                '_info': s['_info'], '_restore': _info_descriptor(s['_info'], s['source']),
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
        self.persist()
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
            info = item.pop('_info', None)
            if info is None:
                info = _rehydrate_info(item.get('_restore') or {})
                if info is None:
                    raise RuntimeError('服务重启后无法重新解析该条目，请重新搜索后下载')
            info = copy.deepcopy(info)
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
            item['_inflight'] = save_path
            self.persist()
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
            # 容器内以 root 写 Synology 共享会得到 000 权限（ACL 生效），其他服务读不到 → 显式放开
            with contextlib.suppress(Exception):
                os.chmod(final.save_path, int(os.environ.get('MUSICDL_DOWNLOAD_FILE_MODE', '644'), 8))
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
            item.pop('_inflight', None)
            self._refresh_status(task_id)
            self.persist()

    def cancel_task(self, task_id: str) -> dict:
        task = self.tasks.get(task_id)
        if not task: raise KeyError(f'unknown task {task_id}')
        task['cancel_flag'] = True
        for item in task['items']:
            if item['status'] == 'queued':
                item['_info'] = None; item['status'] = 'cancelled'; item['error'] = '已取消'
            elif item['status'] == 'downloading': item['status'] = 'cancelling'
        self._refresh_status(task_id)
        self.persist()
        return self.snapshot(task_id)

    def retry_item(self, task_id: str, item_id: str) -> dict:
        task = self.tasks.get(task_id)
        if not task: raise KeyError(f'unknown task {task_id}')
        item = next((i for i in task['items'] if i['item_id'] == item_id), None)
        if not item: raise KeyError(f'unknown item {item_id}')
        if item['status'] not in {'failed', 'cancelled', 'cancelling'}: raise ValueError('仅失败或已取消的条目可重试')
        with STORE_LOCK:
            valid = RESULT_STORE.get(item['key'])
        if valid is not None and valid.with_valid_download_url:
            item['_info'] = valid
        elif not item.get('_restore'):
            # no live search result and no restart descriptor -> only a fresh search can help
            raise RuntimeError('原搜索结果已失效，请重新搜索后勾选下载')
        item.update({'status': 'queued', 'error': '', 'progress': 0, 'speed': '',
                     'downloaded_bytes': 0})
        self.pool.submit(self._run_item, task_id, item_id)
        self._refresh_status(task_id)
        self.persist()
        return self.snapshot(task_id)

    def persist(self) -> None:
        '''flush the in-memory queue to the runtime state dir (D2); never raises.'''
        try:
            with self.tasks_lock:
                tasks = [_task_to_disk(t) for t in list(self.tasks.values())[-MAX_PERSISTED_TASKS:]]
            with _tasks_write_lock:
                _write_tasks_file(tasks)
        except Exception:
            pass

    @staticmethod
    def _rebuild_task(raw: dict):
        if not isinstance(raw, dict): return None
        task_id = str(raw.get('task_id') or '')
        items_raw = raw.get('items')
        if not task_id or not isinstance(items_raw, list): return None
        items = []
        for idx, raw_item in enumerate(items_raw):
            if not isinstance(raw_item, dict): continue
            item = {k: v for k, v in raw_item.items() if k != '_info'}
            item.setdefault('item_id', f'{task_id}-{idx}')
            item.setdefault('status', 'failed')
            item.setdefault('progress', 0)
            item.setdefault('speed', '')
            item.setdefault('saved_path', '')
            item.setdefault('downloaded_bytes', 0)
            item.setdefault('total_bytes', 0)
            item.setdefault('error', '')
            if not isinstance(item.get('_restore'), dict):
                item.update(status='failed', error='任务快照缺少恢复信息，请重新搜索')
            items.append(item)
        return {'task_id': task_id, 'created_at': str(raw.get('created_at') or ''),
                'quality_pref': str(raw.get('quality_pref') or 'any'),
                'dedupe': bool(raw.get('dedupe', True)),
                'cancel_flag': bool(raw.get('cancel_flag', False)),
                'items': items, 'status': str(raw.get('status') or 'running')}

    def restore(self) -> int:
        '''rehydrate the persisted queue at startup (lifespan). Only tasks that were still
           running are resubmitted: queued items re-resolve on the worker thread; mid-flight
           items had their partial file removed and are re-queued; a cancel requested before
           the restart is honoured. Returns the number of items re-queued.'''
        requeued = 0
        for raw in _read_tasks_file()[-MAX_PERSISTED_TASKS:]:
            try:
                task = self._rebuild_task(raw)
                if task is None: continue
                with self.tasks_lock:
                    if task['task_id'] in self.tasks: continue
                    self.tasks[task['task_id']] = task
                if task['status'] == 'cancelling' or (task['status'] == 'running' and task['cancel_flag']):
                    for item in task['items']:
                        if item['status'] not in TERMINAL_ITEM_STATUSES:
                            item.update(status='cancelled', error='已取消')
                    self._refresh_status(task['task_id'])
                    continue
                if task['status'] != 'running': continue
                for item in task['items']:
                    if item['status'] in {'downloading', 'cancelling'}:
                        inflight = item.pop('_inflight', '')
                        if inflight:
                            with contextlib.suppress(Exception):
                                partial = Path(inflight)
                                if partial.is_file(): partial.unlink()
                        item.update(status='queued', error='', progress=0, speed='',
                                    downloaded_bytes=0)
                    elif item['status'] == 'queued':
                        item.update(error='', progress=0, speed='', downloaded_bytes=0)
                self._refresh_status(task['task_id'])
                for item in task['items']:
                    if item['status'] == 'queued':
                        self.pool.submit(self._run_item, task['task_id'], item['item_id'])
                        requeued += 1
            except Exception:
                continue   # one malformed task must not stop the rest of the queue
        if requeued: self.persist()
        return requeued

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
