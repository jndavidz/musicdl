'''
Function:
    Kuwo adapter: mobi.s official direct (fast) with bitrate guard -> third-party chain fallback.
'''
import re
import time
from .base import SourceAdapter, AdapterError
from musicdl.modules.sources.kuwo import KuwoMusicClient
from musicdl.modules.utils import AudioLinkTester
from musicdl.modules.utils.kuwoutils import KuwoMusicClientUtils

MIN_KBPS = {'128k': 112, '320k': 256}
LOSSLESS_EXTS = {'flac', 'wav', 'ape'}


class KuwoAdapter(SourceAdapter):
    source_key = 'kuwo'

    def _build_client(self) -> KuwoMusicClient:
        return KuwoMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-kuwo', max_retries=2,
            audio_link_tester_timeout=self.settings.tester_timeout,
        )

    '''official anonymous direct link via mobi.s convert_url2 (~100ms), returns dict or None'''
    def _official_direct(self, song_id: str, fmt: str):
        query = f"user=0&corp=kuwo&source=kwplayer_ar_5.1.0.0_B_jiakong_vh.apk&p2p=1&type=convert_url2&sig=0&format={fmt}&rid={song_id}"
        resp = self.client.get(f"http://mobi.kuwo.cn/mobi.s?f=kuwo&q={KuwoMusicClientUtils.encryptquery(query)}", headers={'user-agent': 'okhttp/3.10.0'})
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
       Verified live 2026-08-12: br=320kmp3 -> bitrate 320 exactly; br=2000kflac -> flac 2000.'''
    def _nmobi_direct(self, song_id: str, br: str):
        import json as _json
        url = f"http://nmobi.kuwo.cn/mobi.s?f=web&source=kwplayerhd_ar_4.3.0.8_tianbao_T1A_qirui.apk&user=0&type=convert_url_with_sign&rid={song_id}&br={br}"
        resp = self.client.get(url, headers={'user-agent': 'okhttp/4.10.0'})
        payload = resp.json() if resp and hasattr(resp, 'json') else {}
        data = payload.get('data') or {}
        cdn = data.get('url')
        if payload.get('code') != 200 or not cdn or not str(cdn).startswith('http'): return None
        try: bitrate = int(data.get('bitrate') or 0)
        except Exception: bitrate = 0
        return {'url': cdn, 'bitrate': bitrate, 'duration_s': int(data['duration']) if data.get('duration') else None,
                'format': data.get('format')}

    '''third-party parse chain by minimal search_result dict'''
    def _via_thirdparty(self, song_id: str):
        return self.client._parsewiththirdpartapis({'musicrid': f'MUSIC_{song_id}'}, {})

    '''haitangw relay with corrected path /music/kw.php (plugin ships dead /music1/, verified live 2026-08-23).
       level: exhigh -> 320k mp3, lossless -> FLAC via kuwo CDN.'''
    def _via_haitangw(self, song_id: str, quality: str):
        import time as _time
        level = 'lossless' if quality in {'flac', 'hires'} else 'exhigh'
        t0 = _time.perf_counter()
        try:
            resp = self.client.get('https://music.haitangw.cc/music/kw.php',
                                   params={'id': song_id, 'level': level}, timeout=(3, 10))
            payload = resp.json() if resp and hasattr(resp, 'json') else {}
            url = ((payload.get('data') or {}).get('url')) or ''
            ok = payload.get('code') == 200 and str(url).startswith('http')
            self.health.record('haitangw.relay.kw', ok, (_time.perf_counter() - t0) * 1000,
                               None if ok else f"code={payload.get('code')} msg={payload.get('msg')}")
            if not ok: return None
            status = self.client.audio_link_tester.test(url)
            if not status.get('ok'): return None
            return status
        except Exception as err:
            self.health.record('haitangw.relay.kw', False, (_time.perf_counter() - t0) * 1000, err)
            return None

    '''metadata-only search via searchMusicBykeyWord (single GET, no parse chain)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        rule = {"vipver": "1", "client": "kt", "ft": "music", "cluster": "0", "strategy": "2012", "encoding": "utf8",
                "rformat": "json", "mobi": "1", "issubtitle": "1", "show_copyright_off": "1",
                "pn": str(page - 1), "rn": str(limit), "all": keywords}
        resp = self.client.get('http://www.kuwo.cn/search/searchMusicBykeyWord?' + urlencode(rule))
        return resp.json().get('abslist') or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        song_id = str(raw.get('MUSICRID') or raw.get('musicrid') or '').removeprefix('MUSIC_')
        try: duration = int(float(raw.get('DURATION') or raw.get('duration') or 0))
        except Exception: duration = None
        return {'id': song_id, 'name': raw.get('SONGNAME') or raw.get('name'), 'singer': raw.get('ARTIST') or raw.get('artist'),
                'album': raw.get('ALBUM') or raw.get('album'), 'ext': None, 'size_bytes': None,
                'duration_s': duration or None, 'cover': raw.get('hts_MVPIC') or raw.get('albumpic') or raw.get('pic'), 'source': 'kuwo'}

    '''HEAD-probe a direct link and build the response dict'''
    async def _finalize_direct(self, song_id: str, q: str, direct: dict, t0: float, parser: str, platform_tag: str = '') -> dict:
        status = await self.run(self.client.audio_link_tester.test, direct['url'])
        return {
            'id': str(song_id), 'source': self.source_key, 'quality': q,
            'url': status.get('download_url') or direct['url'], 'ext': status.get('ext') or 'mp3',
            'size_bytes': status.get('file_size_bytes'), 'bitrate_kbps': direct['bitrate'] or None,
            'duration_s': direct.get('duration_s'), 'cover': None, 'verified': bool(status.get('ok')),
            'headers': {}, 'parser': parser, 'platform_tag': platform_tag or direct.get('format'),
            'elapsed_ms': round((time.perf_counter() - t0) * 1000),
            'cached': False,
        }

    '''xcloudv relay (upstream v2.13.10 new source, POST protocol, verified FLAC 2000k)'''
    def _via_xcloudv(self, song_id: str):
        import requests as _rq
        try:
            r = _rq.post('https://music.xcloudv.top/php/kuwo_backup_source.php',
                         data={'action': 'url', 'songid': song_id, 'yz': '5'},
                         headers={'User-Agent': 'Mozilla/5.0 Chrome/131'}, timeout=15)
            d = r.json()
            url = d.get('raw') or ''
            if not (d.get('success') and str(url).startswith('http')): return None
            status = self.client.audio_link_tester.test(url)
            if not status.get('ok'): return None
            return {'url': status.get('download_url') or url, 'ext': status.get('ext')}
        except Exception:
            return None

    '''quality routing per plan §3.4 (revised by stage-0 spike + 2026-08-12 endpoint probe):
       - flac/hires: nmobi 2000kflac first (ENABLE_LOSSLESS gate), then third-party chain
       - auto/320k/128k: nmobi plain API first (no silent downgrade), then mobi.s encrypted
         sibling, then third-party chain; keep whichever candidate has more bandwidth.'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        t0 = time.perf_counter()
        if q in {'flac', 'hires'}:
            if not self.settings.enable_lossless:
                raise AdapterError(403, 'lossless tier disabled on this server (ENABLE_LOSSLESS=false)')
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
                return {
                    'id': str(song_id), 'source': self.source_key, 'quality': q,
                    'url': relay['download_url'], 'ext': relay.get('ext') or 'mp3',
                    'size_bytes': relay.get('file_size_bytes'), 'bitrate_kbps': 320 if not lossless_hit else None,
                    'duration_s': None, 'cover': None, 'verified': True,
                    'headers': {}, 'parser': 'haitangw.relay',
                    'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False,
                }
        # tier-2c: xcloudv relay (upstream v2.13.10 new source, flac-capable)
        xcv = await self.run(self._via_xcloudv, song_id)
        if xcv:
            return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                    'url': xcv['url'], 'ext': xcv.get('ext') or 'flac',
                    'size_bytes': None, 'bitrate_kbps': 2000 if 'flac' in str(xcv.get('url', '')).lower() else 320,
                    'duration_s': None, 'cover': None, 'verified': True, 'headers': {},
                    'parser': 'xcloudv.relay',
                    'elapsed_ms': round((time.perf_counter() - t0) * 1000), 'cached': False}
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
