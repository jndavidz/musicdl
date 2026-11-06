'''
Function:
    Kuwo adapter: mobi.s official direct (fast) with bitrate guard -> third-party chain fallback.
'''
import re
import time
from .base import SourceAdapter, AdapterError
from ..quality import resolve as resolve_quality, lossless_allowed, LOSSLESS_MSG, LOSSLESS_EXTS
from musicdl.modules.sources.kuwo import KuwoMusicClient
from musicdl.modules.utils import AudioLinkTester
from musicdl.modules.utils.kuwoutils import KuwoMusicClientUtils

MIN_KBPS = {'128k': 112, '320k': 256}


class KuwoAdapter(SourceAdapter):
    source_key = 'kuwo'
    album_track_count = True

    def _build_client(self) -> KuwoMusicClient:
        return KuwoMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-kuwo', max_retries=2,
            audio_link_tester_timeout=self.settings.tester_timeout,
        )

    '''official anonymous direct link via mobi.s convert_url2 (~100ms), returns dict or None'''
    def _official_direct(self, song_id: str, fmt: str):
        query = f"user=0&corp=kuwo&source=kwplayer_ar_5.1.0.0_B_jiakong_vh.apk&p2p=1&type=convert_url2&sig=0&format={fmt}&rid={song_id}"
        resp = self.client.get(f"http://mobi.kuwo.cn/mobi.s?f=kuwo&q={KuwoMusicClientUtils.encryptquery(query)}", headers={'user-agent': 'okhttp/3.10.0'}, timeout=self.io_timeout)
        text = resp.text or ''
        fields = {}
        for line in text.splitlines():
            if '=' in line:
                key, _, val = line.partition('='); fields.setdefault(key.strip(), val.strip())
        m = re.search(r'http[^\s$"]+', text)
        if not m or not str(m.group(0)).startswith('http'): return None
        try: bitrate = int(fields.get('bitrates') or fields.get('bitrate') or 0)
        except Exception: bitrate = 0
        return {'url': m.group(0), 'bitrate': bitrate}

    '''official anonymous direct link via nmobi plain-text API (structured JSON, no silent downgrade).
       Verified live 2026-08-12: br=320kmp3 -> bitrate 320 exactly; br=2000kflac -> flac 2000.
       Zhenpin tiers (2026-09-07 probe, docs/KUWO-ZHENPIN-PROBE.md): anonymous, no cookie;
       br=20900kmflac -> 192k/24bit/2ch mflac+ekey; br=20501kmflac -> 44.1k/16bit/6ch mflac+ekey.'''
    def _nmobi_direct(self, song_id: str, br: str):
        import json as _json
        url = f"http://nmobi.kuwo.cn/mobi.s?f=web&source=kwplayerhd_ar_4.3.0.8_tianbao_T1A_qirui.apk&user=0&type=convert_url_with_sign&rid={song_id}&br={br}"
        resp = self.client.get(url, headers={'user-agent': 'okhttp/4.10.0'}, timeout=self.io_timeout)
        payload = resp.json() if resp and hasattr(resp, 'json') else {}
        data = payload.get('data') or {}
        cdn = data.get('url')
        if payload.get('code') != 200 or not cdn or not str(cdn).startswith('http'): return None
        try: bitrate = int(data.get('bitrate') or 0)
        except Exception: bitrate = 0
        return {'url': cdn, 'bitrate': bitrate, 'duration_s': int(data['duration']) if data.get('duration') else None,
                'format': data.get('format'), 'ekey': data.get('ekey') or None}

    '''zhenpin (臻品) tier table — anonymous, verified 2026-09-07, see docs/KUWO-ZHENPIN-PROBE.md.
       master=192k/24bit/2ch · flac=CD 44.1k/16bit/2ch · surround51=44.1k/16bit/6ch.
       NOTE the `m` prefix: `20900kflac` (no m) silently downgrades to 128k mp3.'''
    ZHENPIN_BR = {
        'master': '20900kmflac',       # flac 192kHz/24bit/2ch after QMC decrypt (~5560kbps real)
        'surround51': '20501kmflac',   # flac 44.1kHz/16bit/6ch after QMC decrypt (~2392kbps real)
        'flac': '2000kflac',           # flac 44.1kHz/16bit/2ch plaintext (~1647kbps real)
    }
    ZHENPIN_EXTS = {'mflac': 'flac', 'mgg': 'ogg'}  # post-decrypt container per native format

    '''third-party parse chain by minimal search_result dict'''
    def _via_thirdparty(self, song_id: str):
        return self.client._parsewiththirdpartapis({'musicrid': f'MUSIC_{song_id}'}, {})

    '''haitangw relay with corrected path /music/kw.php (plugin ships dead /music1/, verified live 2026-08-23).
       level: exhigh -> 320k mp3, lossless -> FLAC via kuwo CDN. 429s cool the LOGICAL
       relay name (kuwo:relay.haitangw) and are re-raised, never swallowed.'''
    def _via_haitangw(self, song_id: str, quality: str):
        level = 'lossless' if quality in {'flac', 'hires'} else 'exhigh'
        try:
            resp = self.guarded_sync('kuwo:relay.haitangw', self.client.get,
                                     'https://music.haitangw.cc/music/kw.php',
                                     params={'id': song_id, 'level': level}, timeout=(3, 10))
        except AdapterError:
            raise            # 429/cooldown: surfaced, never silently skipped
        except Exception:
            return None
        payload = resp.json() if resp and hasattr(resp, 'json') else {}
        url = ((payload.get('data') or {}).get('url')) or ''
        if not (payload.get('code') == 200 and str(url).startswith('http')): return None
        status = self.client.audio_link_tester.test(url)
        return status if status.get('ok') else None

    '''metadata-only search via searchMusicBykeyWord (single GET, no parse chain)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        rule = {"vipver": "1", "client": "kt", "ft": "music", "cluster": "0", "strategy": "2012", "encoding": "utf8",
                "rformat": "json", "mobi": "1", "issubtitle": "1", "show_copyright_off": "1",
                "pn": str(page - 1), "rn": str(limit), "all": keywords}
        resp = self.client.get('http://www.kuwo.cn/search/searchMusicBykeyWord?' + urlencode(rule), timeout=self.io_timeout)
        return resp.json().get('abslist') or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        song_id = str(raw.get('MUSICRID') or raw.get('musicrid') or '').removeprefix('MUSIC_')
        try: duration = int(float(raw.get('DURATION') or raw.get('duration') or 0))
        except Exception: duration = None
        return {'id': song_id, 'name': raw.get('SONGNAME') or raw.get('name'), 'singer': raw.get('ARTIST') or raw.get('artist'),
                'album': raw.get('ALBUM') or raw.get('album'), 'ext': None, 'size_bytes': None,
                'duration_s': duration or None, 'cover': raw.get('hts_MVPIC') or raw.get('albumpic') or raw.get('pic'), 'source': 'kuwo'}

    '''HEAD-probe a direct link and build the response dict.
       Zhenpin tiers carry `ekey`: the returned url serves ENCRYPTED audio; the consumer must
       decrypt with KuwoQmcDecryptor -> plaintext flac/ogg (see webgui download hook).'''
    async def _finalize_direct(self, song_id: str, q: str, direct: dict, t0: float, parser: str, platform_tag: str = '') -> dict:
        status = await self.run(self.client.audio_link_tester.test, direct['url'])
        ext = status.get('ext')
        if direct.get('ekey'):
            # encrypted container: report the POST-DECRYPT container, not the raw mflac/mgg
            native = (platform_tag or direct.get('format') or '').lower()
            ext = 'mflac' if 'mflac' in native else ('mgg' if 'mgg' in native else (ext or 'mflac'))
        return self.url_data(song_id, q,
                             url=status.get('download_url') or direct['url'], ext=ext or 'mp3',
                             size_bytes=status.get('file_size_bytes'), bitrate_kbps=direct['bitrate'] or None,
                             duration_s=direct.get('duration_s'), verified=bool(status.get('ok')),
                             parser=parser, platform_tag=platform_tag or direct.get('format'),
                             ekey=direct.get('ekey') or None,
                             elapsed_ms=round((time.perf_counter() - t0) * 1000))

    '''xcloudv relay (upstream v2.13.10 new source, POST protocol, verified FLAC 2000k).
       429/cooldown is tracked under the logical relay name, not the host string.'''
    def _via_xcloudv(self, song_id: str):
        import requests as _rq
        try:
            r = self.guarded_sync('kuwo:relay.xcloudv', _rq.post,
                                  'https://music.xcloudv.top/php/kuwo_backup_source.php',
                                  data={'action': 'url', 'songid': song_id, 'yz': '5'},
                                  headers={'User-Agent': 'Mozilla/5.0 Chrome/131'}, timeout=self.io_timeout)
        except AdapterError:
            raise
        except Exception:
            return None
        d = r.json()
        url = d.get('raw') or ''
        if not (d.get('success') and str(url).startswith('http')): return None
        status = self.client.audio_link_tester.test(url)
        if not status.get('ok'): return None
        return {'url': status.get('download_url') or url, 'ext': status.get('ext')}

    '''quality routing per plan §3.4 (revised by stage-0 spike + 2026-08-12 endpoint probe;
       + zhenpin tiers 2026-09-07, docs/KUWO-ZHENPIN-PROBE.md):
       - master/surround51: nmobi zhenpin br (anonymous, mflac+ekey) -> decrypt to flac
       - flac/hires: nmobi 2000kflac first (ENABLE_LOSSLESS gate), then third-party chain
       - auto/320k/128k: nmobi plain API first (no silent downgrade), then mobi.s encrypted
         sibling, then third-party chain; keep whichever candidate has more bandwidth.'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = resolve_quality(self.source_key, quality)
        t0 = time.perf_counter()
        if not lossless_allowed(q, self.settings.enable_lossless):
            raise AdapterError(403, LOSSLESS_MSG)
        if q in self.ZHENPIN_BR:
            br = self.ZHENPIN_BR[q]
            direct = await self.run(self._nmobi_direct, song_id, br)
            if direct and direct.get('ekey'):
                return await self._finalize_direct(song_id, q, direct, t0, 'nmobi.zhenpin', platform_tag=br)
            if direct and direct['bitrate'] >= 900:  # plaintext fallback (no ekey = already unencrypted)
                return await self._finalize_direct(song_id, q, direct, t0, 'nmobi.zhenpin.plain', platform_tag=br)
            info = await self.run(self._via_thirdparty, song_id)
            if not (info.with_valid_download_url and info.ext in LOSSLESS_EXTS): raise AdapterError(404, f'no {q} source found')
            return self.urldata_from_songinfo(song_id, q, info, round((time.perf_counter() - t0) * 1000),
                                              platform_tag='第三方链无损')

        if q in {'flac', 'hires'}:
            lossless_br = '20000kflac' if q == 'hires' else '2000kflac'
            direct = await self.run(self._nmobi_direct, song_id, lossless_br)
            if direct and direct['bitrate'] >= 900:
                return await self._finalize_direct(song_id, q, direct, t0, 'nmobi.direct', platform_tag=lossless_br)
            info = await self.run(self._via_thirdparty, song_id)
            if not (info.with_valid_download_url and info.ext in LOSSLESS_EXTS): raise AdapterError(404, 'no lossless source found')
            return self.urldata_from_songinfo(song_id, q, info, round((time.perf_counter() - t0) * 1000),
                                              platform_tag='第三方链无损')

        min_kbps = MIN_KBPS.get(q, 256)
        # tier-1a: nmobi structured JSON (exact bitrate, verified live 2026-08-12)
        direct = await self.run(self._nmobi_direct, song_id, {'128k': '128kmp3'}.get(q, '320kmp3'))
        if direct and direct['bitrate'] >= min_kbps:
            return await self._finalize_direct(song_id, q, direct, t0, 'nmobi.direct',
                                               platform_tag={'128k': '128kmp3'}.get(q, '320kmp3'))
        # tier-1b: mobi.s encrypted sibling
        legacy = await self.run(self._official_direct, song_id, '128kmp3' if q == '128k' else '320kmp3')
        if legacy and legacy['bitrate'] >= min_kbps:
            return await self._finalize_direct(song_id, q, legacy, t0, 'mobi.s.direct')
        best_direct = direct or legacy  # degraded candidates kept as last resort

        # tier-2: third-party chain for something better than the degraded directs
        info = await self.run(self._via_thirdparty, song_id)
        tp_ok = bool(info.with_valid_download_url and info.ext in AudioLinkTester.VALID_AUDIO_EXTS)
        tp_kbps = 0
        if tp_ok and info.file_size_bytes and info.duration_s:
            tp_kbps = int(info.file_size_bytes * 8 / max(int(info.duration_s), 1) / 1000)
        elapsed = round((time.perf_counter() - t0) * 1000)

        if tp_ok and info.ext in LOSSLESS_EXTS:  # chain outperforms any direct link
            return self.urldata_from_songinfo(song_id, q, info, elapsed)
        if tp_ok and (best_direct is None or tp_kbps > ((best_direct['bitrate'] or 0))):
            return self.urldata_from_songinfo(song_id, q, info, elapsed)
        # tier-2b: haitangw relay (corrected path), then degraded direct as last resort
        relay = await self.run(self._via_haitangw, song_id, q)
        if relay:
            lossless_hit = relay.get('ext') in LOSSLESS_EXTS
            if lossless_hit or best_direct is None:
                return self.url_data(song_id, q,
                                     url=relay['download_url'], ext=relay.get('ext') or 'mp3',
                                     size_bytes=relay.get('file_size_bytes'),
                                     bitrate_kbps=320 if not lossless_hit else None,
                                     parser='haitangw.relay',
                                     elapsed_ms=round((time.perf_counter() - t0) * 1000))
        # tier-2c: xcloudv relay (upstream v2.13.10 new source, flac-capable)
        xcv = await self.run(self._via_xcloudv, song_id)
        if xcv:
            return self.url_data(song_id, q,
                                 url=xcv['url'], ext=xcv.get('ext') or 'flac',
                                 bitrate_kbps=2000 if 'flac' in str(xcv.get('url', '')).lower() else 320,
                                 parser='xcloudv.relay',
                                 elapsed_ms=round((time.perf_counter() - t0) * 1000))
        if best_direct:
            parser = 'nmobi.degraded' if best_direct is direct else 'mobi.s.degraded'
            return await self._finalize_direct(song_id, q, best_direct, t0, parser)
        raise AdapterError(404, 'no playable url resolved')

    '''meta info for getMusicInfo'''
    async def song_info(self, song_id: str) -> dict:
        meta = await self.run(self.client._getsongmetainfo, song_id)
        if not meta: raise AdapterError(404, 'song not found')
        return {'id': str(song_id), 'source': self.source_key, 'name': meta.get('songName') or meta.get('name'),
                'singer': meta.get('artist'), 'album': meta.get('album'),
                'duration_s': int(float(meta['duration'])) if meta.get('duration') else None,
                'cover': meta.get('pic') or meta.get('albumpic'),
                'raw': {'kw_meta': {k: meta.get(k) for k in list(meta)[:12]}}}

    '''lyric: newlyric.kuwo.cn (des-encoded, verified in musicdl) first; h5 lrclist as fallback'''
    async def lyric(self, song_id: str) -> str:
        from musicdl.modules.utils import cleanlrc
        # path 1: official encrypted lyric endpoint (same chain as KuwoMusicClient._parsewithofficialapiv1)
        try:
            encoded_params = KuwoMusicClientUtils.buildlyricsparams(song_id, True)
            resp = await self.run(self.client.get, f"http://newlyric.kuwo.cn/newlyric.lrc?{encoded_params}")
            text = cleanlrc(KuwoMusicClientUtils.convertrawlrc(KuwoMusicClientUtils.decodelyrics(resp.content, True)))
            if text and text not in {'NULL', ''}: return text
        except Exception:
            pass
        # path 2: h5 endpoint (frequently gated, keep as fallback)
        headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                   "Referer": f"https://m.kuwo.cn/yinyue/{song_id}", "Accept": "application/json, text/plain, */*"}
        try:
            resp = await self.run(self.client.get, "https://m.kuwo.cn/newh5/singles/songinfoandlrc", headers=headers, params={"musicId": song_id})
            lrclist = (resp.json().get('data') or {}).get('lrclist') or []
            lines = []
            for item in lrclist:
                try:
                    sec = float(item.get('lineTime') or 0); mm, ss = int(sec // 60), sec % 60
                    lines.append(f"[{mm:02d}:{ss:05.2f}]{item.get('lrc', '')}")
                except Exception:
                    lines.append(str(item.get('lrc') or ''))
            return '\n'.join(lines)
        except Exception:
            return ''

    '''lyric_data: 同一次 lrcx=1 抓取同时产出普通 LRC 与逐字（LRCX 即酷我逐字源）。
       lrcx 缺失/解不出时退回既有 lyric() 双路链，lxlyric=None。'''
    async def lyric_data(self, song_id: str) -> dict:
        from musicdl.modules.utils import cleanlrc
        from musicdl.modules.utils.lyricfmt import lrcx2lxlyric
        raw_text = ''
        try:
            encoded_params = KuwoMusicClientUtils.buildlyricsparams(song_id, True)
            resp = await self.run(self.client.get, f"http://newlyric.kuwo.cn/newlyric.lrc?{encoded_params}")
            raw_text = KuwoMusicClientUtils.decodelyrics(resp.content, True)
        except Exception:
            raw_text = ''
        if raw_text:
            text = cleanlrc(KuwoMusicClientUtils.convertrawlrc(raw_text))
            if text and text not in {'NULL', ''}:
                return {'lyric': text, 'lxlyric': lrcx2lxlyric(raw_text) or None}
        return {'lyric': await self.lyric(song_id) or '', 'lxlyric': None}

    '''P7 多类型搜索（老搜索接口 r.s，零 Cookie）：ft=album/artist/playlist + itemset=web_2013。
       形状与 musicfree-plugins kuwo 插件 kwXxxItem 对齐（2026-11-03 实测：album→albumlist、
       artist/playlist→abslist；total 大小写不一：album 小写 total、artist/playlist 大写 TOTAL）。'''
    _KW_MULTI_FT = {'album': 'album', 'artist': 'artist', 'sheet': 'playlist'}

    async def search_multi(self, keywords: str, search_type: str, page: int = 1, limit: int = 20) -> dict:
        import html as _html
        from urllib.parse import urlencode
        rule = {'all': keywords, 'ft': self._KW_MULTI_FT[search_type], 'itemset': 'web_2013',
                'client': 'kt', 'pn': str(page - 1), 'rn': str(limit),
                'rformat': 'json', 'encoding': 'utf8', 'pcjson': '1'}
        def _get():
            return self.client.get('http://search.kuwo.cn/r.s?' + urlencode(rule), timeout=self.io_timeout)
        resp = await self.run(_get)
        j = resp.json() or {}

        def _txt(v):
            return _html.unescape(str(v)).strip() if v else ''

        if search_type == 'album':
            rows = j.get('albumlist') or []
            items = []
            for a in rows:
                aid = a.get('albumid')
                if not aid:
                    continue
                cover = a.get('img')
                if not cover:
                    # web_albumpic_short 形如 "120/s4s60/86/x.jpg"
                    short = str(a.get('pic') or '')
                    i = short.find('/')
                    if i >= 0:
                        cover = 'https://img4.kuwo.cn/star/albumcover/256' + short[i:]
                items.append({'id': str(aid), 'name': _txt(a.get('name')), 'artist': _txt(a.get('artist')),
                              'cover': cover,
                              'track_count': int(a['musiccnt']) if str(a.get('musiccnt') or '').isdigit() else None,
                              'source': 'kuwo'})
            total = int(j['total']) if str(j.get('total') or '').isdigit() else None
        elif search_type == 'artist':
            rows = j.get('abslist') or []
            items = []
            for a in rows:
                aid = a.get('ARTISTID')
                if not aid:
                    continue
                avatar = a.get('hts_PICPATH') or a.get('PICPATH') or ''
                avatar = avatar if str(avatar).startswith('http') else (
                    'https://img4.kuwo.cn/star/starheads/' + str(avatar) if avatar else None)
                items.append({'id': str(aid), 'name': _txt(a.get('ARTIST')), 'avatar': avatar, 'source': 'kuwo'})
            total = int(j['TOTAL']) if str(j.get('TOTAL') or '').isdigit() else None
        else:
            rows = j.get('abslist') or []
            items = []
            for p in rows:
                pid = p.get('playlistid') or p.get('id')
                if not pid:
                    continue
                items.append({'id': str(pid), 'name': _txt(p.get('name')),
                              'creator': _txt(p.get('nickname') or p.get('uname')),
                              'cover': p.get('pic') or p.get('img') or None,
                              'track_count': int(p['songnum']) if str(p.get('songnum') or '').isdigit() else None,
                              'play_count': int(p['playcnt']) if str(p.get('playcnt') or '').isdigit() else None,
                              'source': 'kuwo'})
            total = int(j['TOTAL']) if str(j.get('TOTAL') or '').isdigit() else None
        return {'items': items, 'total': total}

    '''P6 补齐（2026-11-03）：专辑检索走老搜索接口 r.s——候选 ft=album，首选曲目 stype=albuminfo。
       形状与 musicfree-plugins kuwo 插件 getAlbumInfo 对齐（rsWorkParams 附加参数缺一不可，
       缺了会拿到 HTML 而非 JSON）。曲目解析仍走 /song/url by-id（二段式不变）。'''
    _KUWO_ALBUM_WORK_PARAMS = {'alflac': '1', 'show_copyright_off': '1', 'pcmp4': '1', 'plat': 'pc',
                               'thost': 'search.kuwo.cn', 'vipver': 'MUSIC_9.1.1.2_BCS2',
                               'devid': '38668888', 'newver': '1'}

    async def album(self, name: str, artist: str = '', page: int = 1) -> dict:
        import html as _html
        from urllib.parse import urlencode

        def _rs(extra):
            rule = {'all': name, 'client': 'kt', 'rn': '5', 'rformat': 'json', 'encoding': 'utf8', 'pcjson': '1'}
            rule.update(self._KUWO_ALBUM_WORK_PARAMS)
            rule.update(extra)
            resp = self.client.get('http://search.kuwo.cn/r.s?' + urlencode(rule), timeout=self.io_timeout)
            return resp.json() or {}

        def _fetch():
            # 候选：ft=album（与 search_multi album 同款）；name+artist 无结果再退 name-only
            ft_rule = {'ft': 'album', 'itemset': 'web_2013', 'pn': str(page - 1)}
            j = _rs(ft_rule) if not artist else _rs({**ft_rule, 'all': f'{name} {artist}'.strip()})
            rows = j.get('albumlist') or []
            if not rows and artist:
                rows = (_rs(ft_rule)).get('albumlist') or []
            albums = []
            for a in rows:
                if not a.get('albumid'):
                    continue
                cover = a.get('img')
                if not cover:
                    short = str(a.get('pic') or '')
                    i = short.find('/')
                    if i >= 0:
                        cover = 'https://img4.kuwo.cn/star/albumcover/256' + short[i:]
                albums.append({'id': str(a['albumid']), 'name': _html.unescape(str(a.get('name') or '')),
                               'artist': _html.unescape(str(a.get('artist') or '')), 'cover': cover,
                               'source': 'kuwo'})
            if not albums:
                return {'albums': [], 'items': [], 'total': 0}
            # 首选曲目：stype=albuminfo（官方曲序即接口返回序）
            info = _rs({'stype': 'albuminfo', 'albumid': albums[0]['id'], 'sortby': '0', 'pn': '0', 'rn': '200'})
            items = []
            for n, m in enumerate(info.get('musiclist') or [], start=1):
                song_id = str(m.get('musicrid') or m.get('id') or '').removeprefix('MUSIC_')
                if not song_id:
                    continue
                short = str(m.get('web_albumpic_short') or '')
                i = short.find('/')
                cover = ('https://img4.kuwo.cn/star/albumcover/256' + short[i:]) if i >= 0 else None
                try:
                    duration = int(float(m.get('duration') or 0)) or None
                except Exception:
                    duration = None
                items.append({'id': song_id, 'name': _html.unescape(str(m.get('name') or m.get('NAME') or '')),
                              'singer': _html.unescape(str(m.get('artist') or m.get('ARTIST') or '')),
                              'album': _html.unescape(str(m.get('album') or m.get('ALBUM') or albums[0]['name'])),
                              'ext': None, 'size_bytes': None, 'duration_s': duration, 'cover': cover,
                              'source': 'kuwo', 'track_no': n})
            return {'albums': albums, 'items': items, 'total': len(items)}

        return await self.run(_fetch)

    '''P9b（2026-11-04 现网实测）：歌手详情/作品走 search.kuwo.cn/r.s
       （stype=artistinfo / artist2music / albumlist；rsWorkParams 附加参数缺一不可，
       缺了会返回 HTML 而非 JSON）。id 口径 = 数字 artistid（search_multi artist 项即 ARTISTID）。'''

    def _kw_rs_work(self, extra: dict) -> dict:
        from urllib.parse import urlencode
        rule = {'client': 'kt', 'rn': '30', 'rformat': 'json', 'encoding': 'utf8', 'pcjson': '1'}
        rule.update(self._KUWO_ALBUM_WORK_PARAMS)
        rule.update(extra)
        url = 'http://search.kuwo.cn/r.s?' + urlencode(rule)
        resp = self.client.get(url, timeout=self.io_timeout)
        try:
            return resp.json() or {}
        except Exception:
            raise AdapterError(502, 'kuwo r.s non-json response')

    @staticmethod
    def _kw_album_cover(a: dict):
        cover = a.get('hts_img') or a.get('img')
        if cover:
            return cover
        short = str(a.get('pic') or '')
        i = short.find('/')
        return ('https://img4.kuwo.cn/star/albumcover/256' + short[i:]) if i >= 0 else None

    async def artist_info(self, artist_id: str) -> dict:
        def _fetch():
            j = self._kw_rs_work({'artistid': str(artist_id), 'stype': 'artistinfo',
                                  'pn': '0', 'rn': '1'})
            if not j.get('name'):
                raise AdapterError(404, 'artist not found')
            pic = j.get('hts_pic') or j.get('pic') or ''
            if pic and not str(pic).startswith('http'):
                pic = 'https://img4.kuwo.cn/star/starheads/' + str(pic)
            return {'artist': {'id': str(j.get('id') or artist_id), 'name': j.get('name') or '',
                               'avatar': pic or None, 'alias': j.get('oname') or None,
                               'description': j.get('desc') or None,
                               'album_count': self._kw_int(j.get('albumnum')),
                               'music_count': self._kw_int(j.get('musicnum')),
                               'source': 'kuwo'}}
        return await self.run(_fetch)

    async def artist_works(self, artist_id: str, work_type: str = 'music',
                           page: int = 1, limit: int = 30) -> dict:
        import html as _html

        def _txt(v):
            return _html.unescape(str(v)).strip() if v else ''

        def _fetch():
            offset = max(0, (page - 1) * limit)
            if work_type == 'music':
                j = self._kw_rs_work({'artistid': str(artist_id), 'stype': 'artist2music',
                                      'sortby': '0', 'pn': str(page - 1), 'rn': str(limit)})
                rows = j.get('musiclist') or []
                total = self._kw_int(j.get('total')) or len(rows)
                items = []
                for m in rows:
                    sid = str(m.get('musicrid') or m.get('id') or '').removeprefix('MUSIC_')
                    if not sid:
                        continue
                    short = str(m.get('web_albumpic_short') or '')
                    i = short.find('/')
                    cover = ('https://img4.kuwo.cn/star/albumcover/256' + short[i:]) if i >= 0 else None
                    items.append({'id': sid, 'name': _txt(m.get('name') or m.get('NAME')),
                                  'singer': _txt(m.get('artist') or m.get('ARTIST')),
                                  'album': _txt(m.get('album') or m.get('ALBUM')),
                                  'ext': None, 'size_bytes': None,
                                  'duration_s': self._kw_int(m.get('duration')),
                                  'cover': cover, 'source': 'kuwo'})
                return {'type': work_type, 'page': page, 'is_end': offset + len(rows) >= total,
                        'total': total, 'items': items}
            j = self._kw_rs_work({'artistid': str(artist_id), 'stype': 'albumlist',
                                  'sortby': '1', 'pn': str(page - 1), 'rn': str(limit)})
            rows = j.get('albumlist') or []
            total = self._kw_int(j.get('total')) or len(rows)
            items = [{'id': str(a['albumid']), 'name': _txt(a.get('name')), 'artist': _txt(a.get('artist')),
                      'cover': self._kw_album_cover(a),
                      'size': self._kw_int(a.get('musiccnt')),
                      'extra': {'publish_time': a.get('pub'), 'description': a.get('info')},
                      'source': 'kuwo'}
                     for a in rows if a.get('albumid')]
            return {'type': work_type, 'page': page, 'is_end': offset + len(rows) >= total,
                    'total': total, 'items': items}
        return await self.run(_fetch)

    '''P8（2026-11-04）：榜单/推荐歌单走官方 wapi 免登通道（musicfree-plugins kuwo
       插件现役实现对齐，形状 2026-11-04 现网实测）。归一在此完成，kwqq 插件只做透传。
       曲目 id=rid，与 /kuwo/song/url 的 id 口径一致；曲目解析仍走 /song/url（二段式）。'''

    _KW_UA_HEADERS = {'user-agent': 'kwplayer_pc_9.0.5.0', 'Referer': 'https://www.kuwo.cn/'}

    async def _kw_official_get(self, url, params=None, timeout=None):
        from urllib.parse import urlencode
        qs = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        full = url + ('?' + qs if qs else '')

        def _get():
            return self.client.get(full, headers=self._KW_UA_HEADERS, timeout=timeout or self.io_timeout)
        return (await self.run(_get)).json()

    @staticmethod
    def _kw_int(v):
        try:
            return int(str(v))
        except (TypeError, ValueError):
            return None

    async def toplists(self) -> dict:
        data = await self._kw_official_get('http://wapi.kuwo.cn/api/pc/bang/list')
        items = []
        for group in (data or {}).get('child') or []:
            for b in group.get('child') or []:
                if not b.get('sourceid'):
                    continue
                items.append({'id': str(b['sourceid']), 'name': (b.get('name') or '').strip(),
                              'cover': b.get('pic5') or b.get('pic2') or b.get('pic'),
                              'description': b.get('intro'), 'source': 'kuwo'})
        return {'items': items}

    async def toplist_songs(self, toplist_id: str, page: int = 1, limit: int = 50) -> dict:
        # ksong.s：pn 从 0 起；不返回 total，用不足一页判尽（musicfree 同款）
        data = await self._kw_official_get('http://kbangserver.kuwo.cn/ksong.s', {
            'from': 'pc', 'fmt': 'json', 'pn': page - 1, 'rn': limit, 'type': 'bang',
            'data': 'content', 'id': toplist_id, 'show_copyright_off': 0,
            'pcmp4': 1, 'isbang': 1, 'userid': 0, 'httpStatus': 1,
        }, timeout=35)
        songs = (data or {}).get('musiclist') or []
        items = [{'id': str(m.get('id')).replace('MUSIC_', ''), 'name': (m.get('name') or '').strip(),
                  'singer': (m.get('artist') or '').strip(), 'album': m.get('album'),
                  'duration_s': self._kw_int(m.get('song_duration') or m.get('duration')),
                  'source': 'kuwo'} for m in songs if m.get('id')]
        return {'page': page, 'is_end': len(songs) < limit,
                'total': self._kw_int((data or {}).get('num')), 'items': items}

    async def playlist_tags(self) -> dict:
        data = await self._kw_official_get('http://wapi.kuwo.cn/api/pc/classify/playlist/getTagList', {
            'cmd': 'rcm_keyword_playlist', 'user': 0, 'prod': 'kwplayer_pc_9.0.5.0',
            'vipver': '9.0.5.0', 'source': 'kwplayer_pc_9.0.5.0',
            'loginUid': 0, 'loginSid': 0, 'appUid': 76039576,
        })
        groups, pinned = [], []
        for cat in (data or {}).get('data') or []:
            tags = [{'id': str(t.get('id')), 'title': (t.get('name') or '').strip()}
                    for t in (cat.get('data') or []) if t.get('id')]
            if not tags:
                continue
            groups.append({'title': cat.get('name') or '', 'data': tags})
            for t in (cat.get('data') or []):
                if str(t.get('digest')) == '10000' and len(pinned) < 8:
                    pinned.append({'id': str(t.get('id')), 'title': (t.get('name') or '').strip()})
        return {'pinned': pinned, 'groups': groups}

    async def playlist_sheets(self, tag: str, page: int = 1, limit: int = 30) -> dict:
        def _sheet(p):
            pid = p.get('playlistid') or p.get('id')
            return {'id': str(pid), 'name': (p.get('name') or '').strip(),
                    'creator': (p.get('nickname') or p.get('uname') or '').strip(),
                    'cover': p.get('pic') or p.get('img'),
                    'track_count': self._kw_int(p.get('songnum') or p.get('total')),
                    'play_count': self._kw_int(p.get('playcnt') or p.get('listencnt')),
                    'source': 'kuwo'}

        if tag:
            # 普通标签走 getTagPlayList 分页（digest=10000 热门与普通同通道）；
            # 专区标签（digest!=10000，kwqq 插件以 <id>@<digest> 编码）走 er.s 聚合一次返回、切片分页
            if '@' in tag:
                zone_id = tag.split('@', 1)[0]
                raw = await self._kw_official_get('http://mobileinterfaces.kuwo.cn/er.s', {
                    'type': 'get_pc_qz_data', 'f': 'web', 'id': zone_id, 'prod': 'pc'})
                flat = [p for sec in (raw if isinstance(raw, list) else []) for p in (sec.get('list') or [])]
                rows = flat[(page - 1) * limit: page * limit]
                return {'tag': tag, 'page': page, 'is_end': page * limit >= len(flat),
                        'total': len(flat), 'items': [_sheet(p) for p in rows if p.get('id') or p.get('playlistid')]}
            data = await self._kw_official_get(
                'http://wapi.kuwo.cn/api/pc/classify/playlist/getTagPlayList', {
                    'loginUid': 0, 'loginSid': 0, 'appUid': 76039576, 'pn': page - 1,
                    'id': tag, 'rn': limit,
                }, timeout=35)
            inner = (data or {}).get('data') or {}
            rows = inner.get('data') or []
            total = self._kw_int(inner.get('total'))
            return {'tag': tag, 'page': page, 'is_end': page * limit >= (total or 0),
                    'total': total, 'items': [_sheet(p) for p in rows]}
        # 空标签 = 全部热门推荐（getRcmPlayList，order=hot）
        data = await self._kw_official_get(
            'http://wapi.kuwo.cn/api/pc/classify/playlist/getRcmPlayList', {
                'loginUid': 0, 'loginSid': 0, 'appUid': 76039576, 'pn': page - 1,
                'rn': limit, 'order': 'hot',
            }, timeout=35)
        inner = (data or {}).get('data') or {}
        rows = inner.get('data') or []
        total = self._kw_int(inner.get('total'))
        return {'tag': '', 'page': page, 'is_end': page * limit >= (total or 0),
                'total': total, 'items': [_sheet(p) for p in rows]}

    async def playlist_songs(self, playlist_id: str, page: int = 1, limit: int = 50) -> dict:
        # nplserver pl.svc：pn 从 0 起；page=1 响应自带歌单元数据（meta），免额外请求
        data = await self._kw_official_get('http://nplserver.kuwo.cn/pl.svc', {
            'op': 'getlistinfo', 'pid': playlist_id, 'pn': page - 1, 'rn': limit,
            'encode': 'utf8', 'keyset': 'pl2012', 'vipver': 'MUSIC_9.1.1.2_BCS2', 'newver': 1,
        }, timeout=35)
        songs = (data or {}).get('musiclist') or []
        total = self._kw_int((data or {}).get('total')) or len(songs)
        items = [{'id': str(m.get('musicrid') or m.get('id') or '').replace('MUSIC_', ''),
                  'name': (m.get('name') or m.get('FNAME') or '').strip(),
                  'singer': (m.get('artist') or m.get('FARTIST') or '').strip(),
                  'album': m.get('album') or m.get('FALBUM'),
                  'duration_s': self._kw_int(m.get('duration') or m.get('song_duration')),
                  'cover': m.get('albumpic') or m.get('pic'),
                  'source': 'kuwo'} for m in songs if (m.get('musicrid') or m.get('id'))]
        meta = None
        if page == 1:
            meta = {'id': str((data or {}).get('id') or playlist_id),
                    'name': (data or {}).get('title') or '',
                    'creator': (data or {}).get('uname') or '',
                    'cover': (data or {}).get('pic'),
                    'track_count': total,
                    'play_count': self._kw_int((data or {}).get('playnum')),
                    'extra': {'description': (data or {}).get('info')}}
        return {'page': page, 'is_end': (page - 1) * limit + len(songs) >= total,
                'total': total, 'items': items, 'meta': meta}

    '''MV（2026-11-06 现网实测，见 docs/MUSIC-SOURCES-REGISTRY.md §12.3）：
       匿名网关 m.kuwo.cn/newh5app/wapi/**（www.kuwo.cn/api/** 对本机 IP 恒 "The request is illegal!"，
       Secret 复刻无效；wapi 前缀无需 Cookie/预热即可通过）。

       两条通道，结论都经现网取证：
       1) **歌曲 id → MV**：musicInfo.mvpayinfo.vid → playUrl(type=mv)；
          但酷我已把**歌曲关联 MV 全量下线**（对 mvpayinfo.vid 逐一实测恒 code:-1001「该MV已下线」，
          含 2025-2026 新歌），故此路径正常返回 url:null（业务未命中，不 404）。
       2) **MV 目录在架**：mvList(pid=9 个分类) 共约 2400 条，id 即播放用的 MV id；playUrl 直链 mp4 全部可播。
          id 先查目录命中（避免与歌曲 rid 数值空间撞号），未命中再走歌曲路径。'''
    _KW_MV_BASE = 'https://m.kuwo.cn/newh5app/'
    _KW_MV_HEADERS = {'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                                    'AppleWebKit/605.1.15 Mobile/15E148',
                      'referer': 'https://m.kuwo.cn/'}
    '''MV 目录分类（前端 tags 原值）：首播/华语/日韩/网络/欧美/现场/热舞/伤感/剧情'''
    _KW_MV_CATEGORIES = ('236682871', '236682731', '236742444', '236682773', '236682735',
                         '236742576', '236682777', '236742508', '236742578')
    _kw_mv_catalog = {'ts': 0.0, 'items': {}}
    _kw_mv_lock = None

    def _kw_mv_json(self, path: str, params: dict) -> dict:
        resp = self.client.get(self._KW_MV_BASE + path, params=params,
                               headers=self._KW_MV_HEADERS, timeout=self.io_timeout)
        try:
            return resp.json() or {}
        except Exception:
            return {}

    '''全量 MV 目录（9 分类分页拉齐，进程内缓存 6h）。命中即保证可播，供 /search?type=mv 与 mv() 复用。'''
    def _kw_mv_catalog_items(self) -> dict:
        import threading
        import time as _t
        if type(self)._kw_mv_lock is None:
            type(self)._kw_mv_lock = threading.Lock()
        cache = type(self)._kw_mv_catalog
        if cache['items'] and _t.time() - cache['ts'] < 6 * 3600:
            return cache['items']
        with type(self)._kw_mv_lock:
            if cache['items'] and _t.time() - cache['ts'] < 6 * 3600:
                return cache['items']
            items = {}
            for pid in self._KW_MV_CATEGORIES:
                pn, pages = 1, 1
                for _ in range(pages):
                    j = self._kw_mv_json('wapi/api/www/music/mvList',
                                         {'pid': pid, 'pn': pn, 'rn': 200})
                    data = j.get('data') or {}
                    rows = data.get('mvlist') or []
                    total = self._kw_int(data.get('total')) or 0
                    pages = max(1, -(-total // 200))
                    for r in rows:
                        mid = str(r.get('id') or '')
                        if not mid:
                            continue
                        items.setdefault(mid, {
                            'id': mid, 'source': 'kuwo', 'title': r.get('name') or None,
                            'artist': r.get('artist') or None, 'cover': r.get('pic') or None,
                            'duration_s': self._kw_int(r.get('duration')), 'quality': None,
                            'url': None, 'play_count': self._kw_int(r.get('mvPlayCnt'))})
                    pn += 1
            if items:
                cache['items'], cache['ts'] = items, _t.time()
            return cache['items']

    def _kw_mv_play(self, mv_id: str) -> str | None:
        play = self._kw_mv_json('wapi/api/v1/www/music/playUrl',
                                {'mid': str(mv_id), 'type': 'mv', 'httpsStatus': '1'})
        data = play.get('data') if isinstance(play.get('data'), dict) else {}
        url = data.get('url') if play.get('code') == 200 else None
        return url if isinstance(url, str) and url.startswith('http') else None

    async def mv(self, song_id: str, title: str = '', artist: str = '') -> dict:
        def _fetch():
            catalog = self._kw_mv_catalog_items()
            hit = catalog.get(str(song_id))
            if hit:
                return {**hit, 'url': self._kw_mv_play(str(song_id))}
            info = self._kw_mv_json('wapi/api/www/music/musicInfo', {'mid': str(song_id)})
            d = info.get('data') or {}
            vid = str(((d.get('mvpayinfo') or {}).get('vid')) or '')
            base = {'id': str(song_id), 'source': 'kuwo', 'url': None,
                    'title': d.get('name') or (title or None),
                    'artist': d.get('artist') or (artist or None),
                    'cover': d.get('pic'), 'duration_s': self._kw_int(d.get('duration')),
                    'quality': None}
            if vid:
                base['url'] = self._kw_mv_play(vid)   # 实测：歌曲关联 MV 已全量下线 → 多为 None
            return base
        return await self.run(_fetch)

    '''MV 搜索（首页目录本地检索）：分词全命中 title+artist，按 mvPlayCnt 降序分页。
       id = 在架 MV id（mv() 命中目录直取，**保证搜到的都能播**）；url 恒为 None（点击现取）。
       酷我按歌曲关键词的 MV 库（searchMvBykeyWord）仍返回歌曲，但这些歌的 MV 已下线，故不采用。'''
    async def search_mv(self, keywords: str, page: int = 1, limit: int = 20) -> dict:
        def _norm(v) -> str:
            return ''.join(str(v or '').lower().split())

        def _fetch():
            catalog = self._kw_mv_catalog_items()
            toks = [t for t in _norm(keywords).replace('/', ' ').split() if t] or [_norm(keywords)]
            matched = [it for it in catalog.values()
                       if all(t in _norm(it.get('title')) or t in _norm(it.get('artist')) for t in toks)]
            matched.sort(key=lambda it: it.get('play_count') or 0, reverse=True)
            start = max(0, (page - 1) * limit)
            return {'items': matched[start:start + limit], 'total': len(matched)}
        return await self.run(_fetch)
