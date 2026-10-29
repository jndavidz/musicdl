'''
Function:
    Bounded completed-download outbox for Songloft's idempotent incremental scan
    (S-08). One JSON file per completed item, named by a stable hash of the
    identity + published path, so re-publishing the same completion is a no-op
    and a retry never produces a duplicate event.
Notes:
    - the outbox lives next to the library but is never scanned as media;
    - entries carry identity + published path + size, never URLs, cookies or ekeys;
    - the directory is bounded: once it exceeds MAX_ENTRIES the oldest entries are
      dropped (Songloft is expected to consume and remove them).
'''
import os
import json
import time
import hashlib
import contextlib
import threading
from pathlib import Path

from config import SETTINGS

MAX_ENTRIES = 500
_lock = threading.Lock()


def outbox_dir() -> Path:
    configured = str(SETTINGS.get('outbox_dir') or '').strip()
    root = Path(configured) if configured else Path(SETTINGS['download_dir']) / '.outbox'
    return root


def entry_id(task_id: str, item_id: str, path: str, size_bytes) -> str:
    raw = f'{task_id}|{item_id}|{path}|{size_bytes}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def publish_completed(*, task_id: str, item_id: str, track_ref: dict, path: str,
                      size_bytes=None, ext: str = '', quality_tier: str = '') -> str | None:
    '''write (or rewrite idempotently) one completion notice; never raises.'''
    try:
        eid = entry_id(task_id, item_id, path, size_bytes)
        target = outbox_dir()
        payload = {'event': 'download.completed', 'id': eid,
                   'task_id': task_id, 'item_id': item_id,
                   'track_ref': dict(track_ref or {}),
                   'path': str(path), 'filename': Path(path).name,
                   'size_bytes': size_bytes, 'ext': str(ext or '').lstrip('.'),
                   'quality_tier': str(quality_tier or ''),
                   'published_at': int(time.time())}
        with _lock:
            target.mkdir(parents=True, exist_ok=True)
            dest = target / f'completed-{eid}.json'
            tmp = target / f'.{eid}.tmp'
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, dest)   # atomic: a reader never sees a half-written notice
            _prune(target)
        return str(dest)
    except Exception:
        return None


def _prune(target: Path) -> None:
    '''bounded outbox: drop the oldest notices beyond MAX_ENTRIES'''
    try:
        entries = sorted((p for p in target.glob('completed-*.json')),
                         key=lambda p: p.stat().st_mtime)
        for old in entries[:-MAX_ENTRIES] if len(entries) > MAX_ENTRIES else []:
            with contextlib.suppress(Exception):
                old.unlink()
    except Exception:
        pass


def list_entries(limit: int = 100) -> list:
    '''read-only view for the API/tests (newest first)'''
    target = outbox_dir()
    if not target.is_dir():
        return []
    out = []
    for path in sorted(target.glob('completed-*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        with contextlib.suppress(Exception):
            out.append(json.loads(path.read_text(encoding='utf-8')))
    return out
