#!/usr/bin/env python3
"""musicdl 源码 API 端点/密钥/方法 提取分析"""
import re, os, json

src_dir = 'musicdl/modules/sources'
results = {}

for fname in sorted(os.listdir(src_dir)):
    if not fname.endswith('.py') or fname == '__init__.py':
        continue
    with open(os.path.join(src_dir, fname), 'r', encoding='utf-8') as f:
        code = f.read()

    urls = set()
    for m in re.finditer(r'https?://[^\s"\')]+', code):
        u = m.group().rstrip(',.;:')
        if any(x in u.lower() for x in ['pypi.org', 'python.org', 'readthedocs',
                                         'github.com', 'opensource.org', 'apache.org',
                                         'copyright', 'musicdl.readthedocs']):
            continue
        urls.add(u)

    keys = set()
    for m in re.findall(r"'([A-Za-z0-9+/=]{20,})'", code):
        keys.add(m)
    for m in re.finditer(
        r'(?:apikey|api_key|token|secret|password)\s*[=:]\s*["\']([A-Za-z0-9_\-+/=]{8,})["\']',
        code, re.I):
        keys.add(m.group(1))

    methods = sorted(set(re.findall(r'def (_parsewith\w+)\s*\(', code)))
    lines = len(code.split('\n'))

    # 按域名分类 URL
    qq_urls = [u for u in urls if any(x in u for x in ['y.qq.com', 'gtimg.cn', 'qzone', 'qqmusic', 'vkeys', 'nki.pw', 'cyapi', 'xingmian', 'xcvts', '317ak', 'xunyusi', 'xianyuw', 'hk0.cc', 'tang.api', 'lpz.chatc', 'yutangxiaowu'])]
    kw_urls = [u for u in urls if any(x in u for x in ['kuwo.cn', 'kuwo', 'nxinxz', 'cenguigui', 'haitangw', 'nobb', 'guyuei', 'yyy001', 'gdstudio', 'liuyun', 'ccwu', '942240'])]
    other_urls = [u for u in urls if u not in qq_urls and u not in kw_urls]

    results[fname] = {
        'lines': lines, 'urls': urls, 'keys': keys, 'methods': methods,
        'qq_urls': qq_urls, 'kw_urls': kw_urls, 'other_urls': other_urls,
    }

# 输出
total_lines = sum(r['lines'] for r in results.values())
print('=' * 130)
print('MusicDL 源码 API 端点/密钥/方法 分析 ({} 个源, {} 总行)'.format(len(results), total_lines))
print('=' * 130)

for fname in sorted(results.keys()):
    r = results[fname]
    print('\n--- {} ({} 行) ---'.format(fname, r['lines']))
    if r['methods']:
        print('  _parsewith* 方法 ({}): {}'.format(len(r['methods']), ', '.join(r['methods'])))
    if r['keys']:
        ks = []
        for k in sorted(r['keys']):
            if len(k) > 12:
                ks.append('{}...{}'.format(k[:8], k[-6:]))
            else:
                ks.append(k)
        print('  密钥 ({}): {}'.format(len(r['keys']), '; '.join(ks[:15])))
        if len(r['keys']) > 15:
            print('    ... 还有 {} 个'.format(len(r['keys']) - 15))
    print('  QQ 系 URL:')
    for u in sorted(r['qq_urls']):
        print('    {}'.format(u))
    print('  Kuwo 系 URL:')
    for u in sorted(r['kw_urls']):
        print('    {}'.format(u))
    if r['other_urls']:
        print('  其他 URL:')
        for u in sorted(r['other_urls']):
            print('    {}'.format(u))