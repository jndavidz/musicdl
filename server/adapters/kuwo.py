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

    '''third-party parse chain by minimal search_result dict'''
    def _via_thirdparty(self, song_id: str):
        return self.client._parsewiththirdpartapis({'musicrid': f'MUSIC_{song_id}'}, {})

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
    async def _finalize_direct(self, song_id: str, q: str, direct: dict, t0: float) -> dict:
        status = await self.run(self.client.audio_link_tester.test, direct['url'])
        return {
            'id': str(song_id), 'source': self.source_key, 'quality': q,
            'url': status.get('download_url') or direct['url'], 'ext': status.get('ext') or 'mp3',
            'size_bytes': status.get('file_size_bytes'), 'bitrate_kbps': direct['bitrate'] or None,
            'duration_s': None, 'cover': None, 'verified': bool(status.get('ok')),
            'headers': {}, 'parser': 'mobi.s.direct', 'elapsed_ms': round((time.perf_counter() - t0) * 1000),
            'cached': False,
        }

    '''quality routing per plan §3.4 (revised by stage-0 spike):
       - flac/hires: third-party chain only, gated by ENABLE_LOSSLESS
       - auto/320k/128k: mobi.s direct first; if actual bitrate < requested tier, escalate to the
         third-party chain; keep whichever candidate has more bandwidth (honest values always).'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        t0 = time.perf_counter()
        if q in {'flac', 'hires'}:
            if not self.settings.enable_lossless:
                raise AdapterError(403, 'lossless tier disabled on this server (ENABLE_LOSSLESS=false)')
            info = await self.run(self._via_thirdparty, song_id)
            if not (info.with_valid_download_url and info.ext in LOSSLESS_EXTS): raise AdapterError(404, 'no lossless source found')
            return self.urldata_from_songinfo(song_id, q, info, round((time.perf_counter() - t0) * 1000))

        fmt = '128kmp3' if q == '128k' else '320kmp3'
        min_kbps = MIN_KBPS.get(q, 256)
        direct = await self.run(self._official_direct, song_id, fmt)
        if direct and direct['bitrate'] and direct['bitrate'] >= min_kbps:
            return await self._finalize_direct(song_id, q, direct, t0)

        # direct missing/downgraded -> try the third-party chain for something better
        info = await self.run(self._via_thirdparty, song_id)
        tp_ok = bool(info.with_valid_download_url and info.ext in AudioLinkTester.VALID_AUDIO_EXTS)
        tp_kbps = 0
        if tp_ok and info.file_size_bytes and info.duration_s:
            tp_kbps = int(info.file_size_bytes * 8 / max(int(info.duration_s), 1) / 1000)
        elapsed = round((time.perf_counter() - t0) * 1000)

        if tp_ok and info.ext in LOSSLESS_EXTS:  # chain outperforms any direct link
            return self.urldata_from_songinfo(song_id, q, info, elapsed)
        if tp_ok and (direct is None or tp_kbps > (direct['bitrate'] or 0)):
            return self.urldata_from_songinfo(song_id, q, info, elapsed)
        if direct:
            return await self._finalize_direct(song_id, q, direct, t0)
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
