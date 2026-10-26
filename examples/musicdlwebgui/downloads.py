'''
Function:
    download engine: the in-memory search-result store and dedupe win-source
    statistics (ADR-0001 review data), task creation with cross-platform
    two-level dedupe folding, threaded per-item downloads with progress and
    QMC decryption hooks, cancel/retry, and task snapshots for the API layer.
'''
import re
import copy
import time
import uuid
import threading
import contextlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from config import SETTINGS, PLATFORM_MAP
from quality import (serialize_item, render_stem, allocate_path, fmt_mb,
                     QUALITY_PREF_RANKS, LOSSLESS_MBPM_FLOOR)
from kwqq_api import api_resolve_into
from library import (get_client, get_lib_downloader, ProgressStub,
                     kuwo_vip_enabled, kuwo_vip_resolve, qmc_decrypt_file)

# in-memory store of the latest search results (key -> SongInfo)
RESULT_STORE: dict = {}
STORE_LOCK = threading.Lock()

'''dedupe win-source statistics (in-memory, resets on restart).
   Counts CONTESTED dedupe picks only: clusters where the same song+album had
   candidates from BOTH the api channel and the lib direct channel, and the
   two-level pick (tier rank -> larger payload) chose one side. This is the
   data behind the ADR-0001 re-review clause: if lib wins stay near zero over
   a monitoring window (with no API outage in it), the six-source lib channel
   can be deleted instead of converted to metadata-only search.'''
DEDUPE_STATS: dict = {'contested': 0, 'wins': {'api': 0, 'lib': 0}, 'by_origin_source': {}}
DEDUPE_STATS_LOCK = threading.Lock()


def _record_dedupe_win(cluster_items: list, best_item: dict) -> None:
    origins = {it['origin'] for it in cluster_items}
    if len(cluster_items) < 2 or not {'api', 'lib'} <= origins:
        return
    with DEDUPE_STATS_LOCK:
        DEDUPE_STATS['contested'] += 1
        origin = best_item['origin']
        DEDUPE_STATS['wins'][origin] += 1
        key = f'{origin}:{best_item["source"]}'
        DEDUPE_STATS['by_origin_source'][key] = DEDUPE_STATS['by_origin_source'].get(key, 0) + 1


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
