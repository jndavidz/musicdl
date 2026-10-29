'''offline tests for the WebGUI strict-source / identity-snapshot / atomic-publish
   work (K-05). No network, no NAS: search + resolve + file fetch are all stubbed
   at the documented seams (kwqq_api / library / downloads).
   Sections:
     A. API search -> download -> atomic publish -> outbox (golden path)
     B. identity-only snapshots: no ekey/url/api_extra persisted
     C. kwqq_only strict mode: no library bypass for search/create/restore/retry
     D. forged/legacy snapshots: identity whitelist, pause instead of re-run
     E. atomic publish + path-root guard + interruption cleanup
     F. outbox idempotence + bounded queue
     G. inbound auth rejects anonymous writes
   Run: XDG_STATE_HOME=$PWD/.state .venv/bin/python examples/musicdlwebgui/tests/test_offline.py'''
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEBGUI = HERE.parent
sys.path.insert(0, str(WEBGUI))

TMP = Path(tempfile.mkdtemp(prefix='musicdl-webgui-offline-'))
os.environ['XDG_STATE_HOME'] = str(TMP / 'state')
os.environ['MUSICDL_WEBGUI_CONFIG'] = str(TMP / 'config.json')

import config              # noqa: E402
import quality             # noqa: E402
import kwqq_api            # noqa: E402
import library             # noqa: E402
import outbox              # noqa: E402
import downloads           # noqa: E402
from musicdl.modules.utils import SongInfo   # noqa: E402

PASSED, FAILED = 0, []


def check(name, cond, detail=''):
    global PASSED
    print(f'  {"PASS" if cond else "FAIL"} {name} {detail}')
    if cond: PASSED += 1
    else: FAILED.append(name)


DL_DIR = TMP / 'music'
DL_DIR.mkdir(parents=True, exist_ok=True)
config.SETTINGS.update({'download_dir': str(DL_DIR), 'api_key': '', 'kwqq_only': False,
                        'outbox_dir': '', 'max_queued_items': 50, 'concurrency': 3,
                        'search_timeout_s': 10, 'max_limit_per_source': 10,
                        'naming_template': '{artist} - {title} - {album}',
                        'quality_pref_default': 'any', 'quality_guard': True,
                        'save_lrc_sidecar': False, 'dedupe_default': True})

# ---- stubs at the documented seams ----
SECRET_EKEY = 'SECRET-EKEY-VALUE'


def fake_search(platform_id, keyword, limit):
    return [kwqq_api.ApiSongInfo(
        song_name='尾戒', singers='测试歌手', album='测试专辑', ext='', duration_s=180,
        source=platform_id, root_source=f'{platform_id}@api', download_url=None,
        api_id='song-1', api_source='kuwo', api_extra={'ekey': SECRET_EKEY, 'url': 'http://x/y'},
        cover_url='')]


def fake_resolve(info, quality_pref):
    info.download_url = 'http://127.0.0.1:1/never.mp3'
    info.ext = 'mp3'
    info.with_valid_download_url = True


class FakeFinal:
    def __init__(self, path):
        self.save_path = path
        self.samplerate = 44100
        self.bitrate = 320


class FakeDownloader:
    payload = b'ID3' + b'x' * 200_000

    def _download(self, info, searched, downloaded, progress, pid, flag):
        target = Path(info._save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.payload)
        downloaded.append(FakeFinal(str(target)))


class InterruptingDownloader(FakeDownloader):
    def _download(self, info, searched, downloaded, progress, pid, flag):
        target = Path(info._save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'ID3partial')
        raise RuntimeError('connection reset mid-download')


block_gate = threading.Event()


class BlockingDownloader(FakeDownloader):
    def _download(self, info, searched, downloaded, progress, pid, flag):
        block_gate.wait(10)
        super()._download(info, searched, downloaded, progress, pid, flag)


def fake_decrypt(path, ekey):
    '''stand-in for QMC decryption: the encrypted temp file becomes a plaintext temp file'''
    src = Path(path)
    out = src.with_suffix('.flac')
    out.write_bytes(FakeDownloader.payload)
    src.unlink(missing_ok=True)
    return str(out)


library.api_search_sync = fake_search
downloads.api_resolve_into = fake_resolve
downloads.get_lib_downloader = lambda: FakeDownloader()
downloads.qmc_decrypt_file = fake_decrypt

import app as webapp    # noqa: E402  (import AFTER the stubs are in place)


def _free_port() -> int:
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close(); return port


def start(app):
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    base = f'http://127.0.0.1:{port}'
    for _ in range(50):
        try:
            urllib.request.urlopen(base + '/healthz', timeout=1)
            return base, server
        except Exception:
            time.sleep(0.2)
    raise RuntimeError('webgui did not start')


def api(base, path, method='GET', body=None, headers=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {}


print('== webgui offline (K-05) ==')

base, server = start(webapp.app)

# ---- A: golden path ----
print('[A] search -> download -> atomic publish -> outbox')
st, body = api(base, '/api/search', 'POST', {'keyword': '尾戒', 'sources': {'kuwo': 3}})
items = (body.get('data') or {}).get('items') or []
check('api search returns an item', st == 200 and len(items) == 1, f'items={len(items)}')
key = items[0]['key'] if items else ''
st, body = api(base, '/api/downloads', 'POST', {'keys': [key], 'quality_pref': 'any', 'dedupe': False})
task = body.get('data') or {}
tid = task.get('task_id')
check('task created', st == 200 and bool(tid))

deadline, snap = time.time() + 20, {}
while time.time() < deadline:
    _, body = api(base, f'/api/tasks/{tid}')
    snap = body.get('data') or {}
    if snap.get('status') in {'completed', 'partial', 'cancelled'}:
        break
    time.sleep(0.2)
item = (snap.get('items') or [{}])[0]
check('download succeeded', item.get('status') == 'success', f"{item.get('status')}: {item.get('error', '')}")
saved = Path(item.get('saved_path') or '')
check('published inside the download root', saved.is_file() and saved.parent == DL_DIR.resolve(),
      str(saved))
check('readable multi-segment name', ' - ' in saved.stem, saved.stem)
check('no partial files left in the temp dir', not any((DL_DIR / '.tmp').glob('*'))
      if (DL_DIR / '.tmp').is_dir() else True)
entries = outbox.list_entries()
check('outbox holds one completion notice', len(entries) == 1, f'entries={len(entries)}')
entry = entries[0] if entries else {}
check('outbox notice carries the TrackRef identity',
      (entry.get('track_ref') or {}).get('id') == 'song-1'
      and (entry.get('track_ref') or {}).get('source') == 'kuwo', f"ref={entry.get('track_ref')}")
blob = json.dumps(entry, ensure_ascii=False)
check('outbox notice has no url/ekey', SECRET_EKEY not in blob and 'never.mp3' not in blob
      and 'http' not in blob)

# ---- B: identity-only snapshot ----
print('[B] identity-only task snapshot')
tasks_file = Path(os.environ['XDG_STATE_HOME']) / 'download_tasks.json'
raw = tasks_file.read_text(encoding='utf-8')
check('persisted queue has no ekey/url/api_extra', SECRET_EKEY not in raw and 'never.mp3' not in raw
      and 'api_extra' not in raw, f'len={len(raw)}')
persisted = json.loads(raw)
ref = persisted['tasks'][0]['items'][0]['_restore']['track_ref']
check('snapshot stores a whitelisted TrackRef', ref == {'provider': 'kwqq', 'source': 'kuwo',
                                                        'id': 'song-1', 'extra': {}}, str(ref))

# ---- D: forged / legacy snapshots ----
print('[D] forged and legacy snapshots')
forged = {'origin': 'api', 'platform': 'tunehub',
          'track_ref': {'provider': 'kwqq', 'source': 'tunehub', 'id': 'x', 'extra': {'ekey': 'evil'}},
          'song_name': 'evil'}
check('cross-channel forged TrackRef is rejected', downloads._rehydrate_info(forged) is None)
missing_copyright = {'origin': 'api', 'platform': 'migu',
                     'track_ref': {'provider': 'kwqq', 'source': 'migu', 'id': '6009', 'extra': {}},
                     'song_name': 'x'}
check('migu identity without copyrightId is rejected', downloads._rehydrate_info(missing_copyright) is None)
legacy = {'origin': 'api', 'platform': 'kuwo', 'song_name': '尾戒', 'singers': '测试歌手',
          'album': '测试专辑', 'ext': 'mp3', 'duration_s': 180,
          'api_id': 'song-1', 'api_source': 'kuwo',
          'api_extra': {'ekey': SECRET_EKEY, 'copyrightId': 'c9', 'url': 'http://evil'}}
rehydrated = downloads._rehydrate_info(legacy)
check('legacy snapshot rehydrates from whitelisted identity only',
      rehydrated is not None and rehydrated.api_extra == {} and 'ekey' not in rehydrated.api_extra)

downloads.TASKS_PATH.write_text(json.dumps({'version': 2, 'tasks': [{
    'task_id': 'resume-1', 'created_at': '00:00:00', 'quality_pref': 'any', 'dedupe': False,
    'cancel_flag': False, 'status': 'running',
    'items': [{'item_id': 'resume-1-0', 'key': 'kuwo:x', 'song_name': 'evil', 'status': 'queued',
               'progress': 0, 'speed': '', 'saved_path': '', 'downloaded_bytes': 0, 'total_bytes': 0,
               'error': '', '_restore': forged}]}]}), encoding='utf-8')
requeued = downloads.engine.restore()
restored = downloads.engine.snapshot('resume-1')['items'][0]
check('unrecognizable snapshot pauses instead of re-running',
      requeued == 0 and restored['status'] == 'paused', f'requeued={requeued} status={restored["status"]}')

# ---- C: strict mode ----
print('[C] kwqq_only strict source mode')
config.SETTINGS['kwqq_only'] = True
st, body = api(base, '/api/search', 'POST', {'keyword': 'x', 'sources': {'tunehub': 3}})
failed = (body.get('data') or {}).get('failed') or {}
check('library platform search is refused in strict mode',
      'tunehub' in failed and '严格模式' in str(failed.get('tunehub')), f'failed={failed}')

lib_info = SongInfo(source='tunehub', song_name='libsong', singers='x', album='y',
                    identifier='lib-1', download_url='http://example.test/a.mp3', ext='mp3',
                    duration_s=100)
with downloads.STORE_LOCK:
    downloads.RESULT_STORE['tunehub:lib1'] = lib_info
st, body = api(base, '/api/downloads', 'POST', {'keys': ['tunehub:lib1'], 'quality_pref': 'any',
                                                'dedupe': False})
check('strict mode rejects library downloads at create', st == 200 and body.get('code') == 400,
      f'status={st} code={body.get("code")}')
st, body = api(base, '/api/search', 'POST', {'keyword': '尾戒', 'sources': {'kuwo': 3}})
check('strict mode still serves kwqq-api sources', st == 200
      and len((body.get('data') or {}).get('items') or []) == 1)
config.SETTINGS['kwqq_only'] = False

# ---- E: publish guards ----
print('[E] atomic publish guards')
tmp_file = DL_DIR / '.tmp' / 'probe.part'
tmp_file.parent.mkdir(parents=True, exist_ok=True)
tmp_file.write_bytes(b'data')
outside = TMP / 'outside.mp3'
try:
    downloads.publish_atomically(tmp_file, str(outside))
    check('publish outside the download root is refused', False)
except RuntimeError as err:
    check('publish outside the download root is refused', '越界' in str(err), str(err))
tmp_file.unlink(missing_ok=True)
check('traversal template cannot escape the root',
      '..' not in quality.render_stem('../../{title}', type('I', (), {
          'singers': 'a', 'song_name': 'b', 'album': 'c', 'ext': 'mp3'})(), platform_id='kuwo'))

downloads.get_lib_downloader = lambda: InterruptingDownloader()
st, body = api(base, '/api/search', 'POST', {'keyword': '尾戒', 'sources': {'kuwo': 3}})
key = ((body.get('data') or {}).get('items') or [{}])[0].get('key')
_, body = api(base, '/api/downloads', 'POST', {'keys': [key], 'quality_pref': 'any', 'dedupe': False})
tid = (body.get('data') or {}).get('task_id')
deadline = time.time() + 10
while time.time() < deadline:
    _, body = api(base, f'/api/tasks/{tid}')
    if (body.get('data') or {}).get('status') in {'completed', 'partial', 'cancelled'}:
        break
    time.sleep(0.2)
failed_item = ((body.get('data') or {}).get('items') or [{}])[0]
check('interrupted download fails visibly', failed_item.get('status') == 'failed', failed_item.get('status'))
check('no half file lands in the library root',
      not any(p.is_file() and p.name != '.tmp' for p in DL_DIR.iterdir())
      or all(p.suffix != '.part' for p in DL_DIR.iterdir()))
check('interrupted temp bytes are cleaned', not any((DL_DIR / '.tmp').glob('*')))

# ---- F: outbox idempotence + bounded queue ----
print('[F] outbox idempotence + bounded queue')
before = len(outbox.list_entries())
outbox.publish_completed(task_id='t1', item_id='i1', track_ref={'id': '1'}, path=str(saved),
                         size_bytes=123, ext='mp3')
outbox.publish_completed(task_id='t1', item_id='i1', track_ref={'id': '1'}, path=str(saved),
                         size_bytes=123, ext='mp3')
check('duplicate completion notice is idempotent', len(outbox.list_entries()) == before + 1,
      f'before={before} after={len(outbox.list_entries())}')

block_gate.clear()
downloads.get_lib_downloader = lambda: BlockingDownloader()
config.SETTINGS['max_queued_items'] = 1
_, body = api(base, '/api/search', 'POST', {'keyword': '尾戒', 'sources': {'kuwo': 3}})
key = ((body.get('data') or {}).get('items') or [{}])[0].get('key')
st, body = api(base, '/api/downloads', 'POST', {'keys': [key], 'quality_pref': 'any', 'dedupe': False})
check('first task admitted', st == 200 and bool((body.get('data') or {}).get('task_id')))
st, body = api(base, '/api/downloads', 'POST', {'keys': [key], 'quality_pref': 'any', 'dedupe': False})
check('over-full queue answers 503', st == 503 and body.get('code') == 503, f'status={st}')
block_gate.set()
config.SETTINGS['max_queued_items'] = 50
downloads.get_lib_downloader = lambda: FakeDownloader()
server.should_exit = True

# ---- G: inbound auth ----
print('[G] inbound auth')
config.SETTINGS['api_key'] = 'sekrit'
base2, server2 = start(webapp.app)
st, _ = api(base2, '/healthz')
check('healthz stays public', st == 200)
st, body = api(base2, '/api/downloads', 'POST', {'keys': ['x'], 'quality_pref': 'any'})
check('anonymous write is rejected', st == 401, f'status={st}')
st, body = api(base2, '/api/search', 'POST', {'keyword': 'x', 'sources': {'kuwo': 3}},
               headers={'X-API-Key': 'sekrit'})
check('authenticated write passes', st == 200, f'status={st}')
config.SETTINGS['api_key'] = ''
server2.should_exit = True

print(f'\nRESULT: {PASSED} passed, {len(FAILED)} failed' + (f' -> {FAILED}' if FAILED else ''))
sys.exit(1 if FAILED else 0)
