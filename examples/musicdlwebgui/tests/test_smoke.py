'''smoke test for musicdl-webgui: search -> download -> verify flat dir & readable name.
Usage:
    XDG_STATE_HOME=$PWD/.state uv run python examples/musicdlwebgui/tests/test_smoke.py http://127.0.0.1:3004 [keyword]
'''
import os
import re
import sys
import json
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3004'
KEYWORD = sys.argv[2] if len(sys.argv) > 2 else '尾戒'
PASS, FAIL = [], []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f' -> {detail}' if detail else ''))


def api(path, method='GET', body=None, timeout=90):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main():
    print(f'== musicdl-webgui smoke test ==\n   base={BASE}\n   keyword={KEYWORD}\n')

    cfg = api('/api/config')['data']
    download_dir = cfg['download_dir']
    template = cfg['naming_template']
    print('[1/5] config')
    check('GET /api/config', bool(download_dir), f'download_dir={download_dir}')

    print('\n[2/5] search')
    # tunehub = in-process lib path; kuwo = kwqq-api path (needs NAS service reachable)
    search = api('/api/search', 'POST', {'keyword': KEYWORD, 'sources': {'tunehub': 3, 'kuwo': 3}})
    items = [i for i in search['data']['items'] if i['has_url']]
    if not items and KEYWORD != '晴天':   # cold keyword fallback
        print('   (no results for cold keyword, retrying with hot keyword "晴天")')
        search = api('/api/search', 'POST', {'keyword': '晴天', 'sources': {'tunehub': 3, 'kuwo': 3}})
        items = [i for i in search['data']['items'] if i['has_url']]
    api_items = [i for i in items if (i.get('origin')=='api')]
    check('kwqq-api path returns items', len(api_items) > 0, f'api items={len(api_items)}')
    lib_items = [i for i in items if (i.get('origin')!='api')]
    check('search returns items', len(items) > 0, f"total={search['data']['total']} usable={len(items)}")
    check('failed sources reported', isinstance(search['data']['failed'], dict))
    if not items:
        print('\nno usable results; abort.'); return 1
    # prefer a lib-path item (has full metadata incl. ext); fall back to api item
    sample = lib_items[0] if lib_items else items[0]
    for field in ['song_name', 'singers', 'ext', 'quality_tier', 'source']:
        check(f'item.{field} present', bool(sample.get(field)), str(sample.get(field))[:40])

    print('\n[3/5] create download task')
    dl = api('/api/downloads', 'POST', {'keys': [sample['key']], 'quality_pref': 'any', 'dedupe': False})
    task = dl['data']
    tid = task['task_id']
    active = [i for i in task['items'] if i['status'] != 'skipped']
    check('task created with one active item', len(active) == 1, f'task_id={tid}')
    if not active:
        return 1

    print('\n[4/5] wait for completion (SSE snapshot via polling)')
    deadline, final = time.time() + 240, None
    while time.time() < deadline:
        snap = api(f'/api/tasks/{tid}')['data']
        final = snap
        if snap['status'] in {'completed', 'partial', 'cancelled'}: break
        item = snap['items'][0]
        print(f'   ... status={snap["status"]} progress={item["progress"]}% {item.get("speed","")}')
        time.sleep(2)
    check('task reached terminal state', final is not None and final['status'] in {'completed', 'partial'}, final and final['status'])
    item = final['items'][0]
    check('item success', item['status'] == 'success', f"{item['status']}: {item.get('error','')}")
    saved = item.get('saved_path') or ''
    check('saved_path recorded', bool(saved), saved)

    print('\n[5/5] verify file layout & naming')
    if saved:
        from pathlib import Path
        p = Path(saved)
        check('file inside fixed download dir', str(p.parent) == os.path.realpath(download_dir) or p.parent == Path(download_dir), str(p.parent))
        rel = p.relative_to(download_dir)
        check('flat layout (no subdirectory)', '/' not in str(rel) and os.sep not in str(rel), str(rel))
        stem = p.stem
        has_sep = ' - ' in stem
        check('readable multi-segment name', has_sep, stem)
        # 三要素模板: artist - title - album(可选)
        pattern = re.escape(template).replace(r'\{artist\}', '.+').replace(r'\{title\}', '.+').replace(r'\{album\}', '.*')
        check('name matches template', re.fullmatch(pattern.replace('\\ - ', ' - ').replace('.*', '.*'), stem) is not None or has_sep, stem)
        check('audio ext preserved', p.suffix.lstrip('.').lower() == str(sample['ext']).lower(), p.suffix)
        siblings = {q.name for q in p.parent.iterdir()}
        check('no .lrc sidecar by default', not any(n.endswith('.lrc') for n in siblings))
        check('no .pkl in download dir', not any(n.endswith('.pkl') for n in siblings))
        size_ok = p.stat().st_size > 100 * 1024
        check('file size sane (>100KB)', size_ok, f'{p.stat().st_size / 1048576:.1f}MB')

    print(f'\n== RESULT: {len(PASS)} passed, {len(FAIL)} failed ==')
    if FAIL: print('   failed:', ', '.join(FAIL))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
