'''
Function:
    QQ adapter: all playback links come from the third-party parse chain
    (official anonymous GetVkey verified dead in stage-0 spike).
'''
import time
import base64
from .base import SourceAdapter, AdapterError
from musicdl.modules.sources.qq import QQMusicClient
from musicdl.modules.utils import AudioLinkTester

LOSSLESS_EXTS = {'flac', 'wav', 'ape'}


class QQAdapter(SourceAdapter):
    source_key = 'qq'

    def _build_client(self) -> QQMusicClient:
        return QQMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-qq', max_retries=2,
            audio_link_tester_timeout=self.settings.tester_timeout,
        )

    '''third-party parse chain by minimal search_result dict'''
    def _via_thirdparty(self, song_id: str):
        return self.client._parsewiththirdpartapis({'mid': song_id}, {})

    '''metadata-only search via musicu.fcg (single POST, no parse chain)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        import json as _json
        from musicdl.modules.utils.qqutils import QQMusicClientUtils, SearchType, Credential
        payload = QQMusicClientUtils.buildrequestdata(
            params={'searchid': QQMusicClientUtils.randomsearchid(), 'query': keywords, 'search_type': SearchType.SONG.value,
                    'num_per_page': limit, 'page_num': page, 'highlight': 0, 'grp': 1},
            module="music.search.SearchCgiService", method="DoSearchForQQMusicMobile", credential=Credential())
        resp = self.client.post(QQMusicClientUtils.endpoint, data=_json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return ((resp.json().get('music.search.SearchCgiService.DoSearchForQQMusicMobile', {}).get('data', {}).get('body', {}) or {}).get('item_song')) or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        album = raw.get('album') or {}
        return {'id': raw.get('mid') or raw.get('songmid') or '', 'name': raw.get('title') or raw.get('songname'),
                'singer': ', '.join(s.get('name') for s in (raw.get('singer') or []) if isinstance(s, dict) and s.get('name')) or None,
                'album': album.get('title') if isinstance(album, dict) else None,
                'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('interval') or 0)) or None,
                'cover': f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{album.get('mid', '')}.jpg" if isinstance(album, dict) else None,
                'source': 'qq'}

    '''quality param is advisory for QQ (chain returns the best it can); flac/hires gated likewise'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        if q in {'flac', 'hires'} and not self.settings.enable_lossless:
            raise AdapterError(403, 'lossless tier disabled on this server (ENABLE_LOSSLESS=false)')
        t0 = time.perf_counter()
        info = await self.run(self._via_thirdparty, song_id)
        elapsed = round((time.perf_counter() - t0) * 1000)
        if not (info.with_valid_download_url and info.ext in AudioLinkTester.VALID_AUDIO_EXTS):
            raise AdapterError(404, 'no playable url resolved')
        data = self.urldata_from_songinfo(song_id, q, info, elapsed)
        # annotate actual tier honestly
        if info.ext in LOSSLESS_EXTS: data['quality'] = 'flac' if q not in {'flac', 'hires'} else q
        return data

    '''meta info from official track_info'''
    async def song_info(self, song_id: str) -> dict:
        meta = await self.run(self.client._getsongmetainfo, song_id)
        if not meta: raise AdapterError(404, 'song not found')
        singers = ', '.join(s.get('name') for s in (meta.get('singer') or []) if isinstance(s, dict) and s.get('name'))
        album = (meta.get('album') or {}).get('title') if isinstance(meta.get('album'), dict) else meta.get('albumname')
        return {'id': str(song_id), 'source': self.source_key, 'name': meta.get('title') or meta.get('songname'),
                'singer': singers or None, 'album': album,
                'duration_s': int(float(meta.get('interval') or 0)) or None,
                'cover': f"https://y.gtimg.cn/music/photo_new/T002R800x800M000{(meta.get('album') or {}).get('mid', '')}.jpg",
                'raw': {'qq_meta': {k: meta.get(k) for k in ('title', 'interval', 'songmid') if k in meta}}}

    '''lyric via official fcg endpoint (base64 json)'''
    async def lyric(self, song_id: str) -> str:
        params = {'songmid': str(song_id), 'g_tk': '5381', 'loginUin': '0', 'hostUin': '0',
                  'format': 'json', 'inCharset': 'utf8', 'outCharset': 'utf-8', 'platform': 'yqq'}
        resp = await self.run(self.client.get, 'https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg',
                              headers={'Referer': 'https://y.qq.com/portal/player.html'}, params=params)
        lyric_b64 = (resp.json() or {}).get('lyric') or ''
        if not lyric_b64: return ''
        return base64.b64decode(lyric_b64).decode('utf-8', errors='ignore')
