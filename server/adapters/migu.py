'''
Function:
    Migu adapter — official anonymous API (search_all.do + listen-url with XOR decrypt).
    by-id resolution needs copyrightId, which is returned in search items' `extra`
    and must be echoed back via the `copyright` query param on /song/url and /song/info.
'''
import re
from .base import SourceAdapter, AdapterError
from musicdl.modules.sources.migu import MiguMusicClient


class MiguAdapter(SourceAdapter):
    source_key = 'migu'

    def _build_client(self) -> MiguMusicClient:
        return MiguMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-migu', max_retries=2,
        )

    '''metadata-only search via search_all.do'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        rule = {'text': keywords, 'pageNo': page, 'pageSize': limit, 'isCopyright': 1, 'sort': 1,
                'searchSwitch': {'song': 1, 'album': 0, 'singer': 0, 'tagSong': 1, 'mvSong': 0, 'bestShow': 1}}
        resp = self.client.get('https://c.musicapp.migu.cn/v1.0/content/search_all.do?' + urlencode(rule))
        return resp2json_migu(self.client, resp).get('songResultData', {}).get('result', []) or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        singers = ', '.join(s.get('name') for s in (raw.get('singers') or raw.get('singerList') or []) if isinstance(s, dict) and s.get('name'))
        album = raw.get('album') or ', '.join(a.get('name') for a in (raw.get('albums') or []) if isinstance(a, dict) and a.get('name'))
        cover = None
        img_items = raw.get('imgItems') or []
        if img_items and isinstance(img_items[-1], dict): cover = img_items[-1].get('img')
        cover = cover or next((raw.get(k) for k in ('img3', 'img2', 'img1') if raw.get(k)), None)
        if cover and not str(cover).startswith('http'): cover = 'https://d.musicapp.migu.cn' + str(cover)
        flags = sorted({r.get('formatType') for r in (raw.get('rateFormats') or []) + (raw.get('newRateFormats') or [])
                        if isinstance(r, dict) and r.get('formatType')})
        return {'id': str(raw.get('contentId') or ''), 'name': raw.get('name') or raw.get('songName'),
                'singer': singers or None, 'album': album or None, 'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('duration') or 0)) or None, 'cover': cover, 'source': 'migu',
                'extra': {'copyrightId': raw.get('copyrightId'), 'resourceType': raw.get('resourceType') or '2',
                          'toneFlags': flags}}

    '''resolve listen url for one toneFlag; falls back to listenSong.do template'''
    def _listen_url(self, song_id: str, copyright_id: str, resource_type: str, flag: str) -> dict:
        headers = {'Content-Type': 'application/json;charset=UTF-8', 'birth': 'h5page', 'signature': '1'}
        params = [('contentId', song_id), ('copyrightId', copyright_id), ('resourceType', resource_type),
                  ('netType', '01'), ('toneFlag', flag), ('scene', ''), ('lowerQualityContentId', song_id)]
        resp = self.client.get('https://c.musicapp.migu.cn/strategy/listen-url/h5/v2.4', params=params, headers=headers)
        result = self.client._decryptresp(resp=resp)
        url = ((result.get('data') or {}).get('url')) or ''
        url = re.sub(r'(?<=/)MP3_128_16_Stero(?=/)', 'MP3_320_16_Stero', url) if url else url
        if not str(url).startswith('http'):
            template = ('https://app.pd.nf.migu.cn/MIGUM3.0/v1.0/content/sub/listenSong.do?channel=mx'
                        f'&copyrightId={copyright_id}&contentId={song_id}&toneFlag={flag}&resourceType={resource_type}'
                        '&userId=15548614588710179085069&netType=00')
            status = self.client.audio_link_tester.test(template)
            if not status.get('ok'): return None
            return {'url': status['download_url'], 'status': status}
        status = self.client.audio_link_tester.test(url)
        if not status.get('ok'): return None
        return {'url': status['download_url'] or url, 'status': status}

    '''quality routing: HQ=320k mp3 reliable anonymously; SQ/ZQ flac gated by ENABLE_LOSSLESS'''
    async def song_url(self, song_id: str, quality: str, copyright_id: str = '') -> dict:
        q = quality if quality in {'auto', '320k', '192k', '128k', 'flac', 'hires'} else 'auto'
        if q == '192k': q = '320k'  # no native 192k tier — snap up to 320k
        t0 = __import__('time').perf_counter()
        import time
        elapsed = lambda: round((time.perf_counter() - t0) * 1000)
        if not copyright_id:
            raise AdapterError(404, 'migu by-id needs copyrightId — pass `copyright` from the search item extra')
        flags = {'128k': ['PQ'], '320k': ['HQ'], 'auto': ['HQ'],
                 'flac': ['SQ', 'ZQ'], 'hires': ['SQ', 'ZQ']}[q]
        if q in {'flac', 'hires'} and not self.settings.enable_lossless:
            raise AdapterError(403, 'lossless tier disabled on this server (ENABLE_LOSSLESS=false)')
        for flag in flags:
            resolved = await self.run(self._listen_url, song_id, copyright_id, '2', flag)
            if not resolved: continue
            status = resolved['status']
            return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                    'url': resolved['url'], 'ext': status.get('ext'),
                    'size_bytes': status.get('file_size_bytes'), 'bitrate_kbps': 320 if flag == 'HQ' else None,
                    'duration_s': None, 'cover': None, 'verified': True, 'headers': {},
                    'parser': f'migu.listen.{flag}', 'platform_tag': flag,
                    'elapsed_ms': elapsed(), 'cached': False}
        raise AdapterError(404, 'no playable url resolved')

    '''song meta: reuse listen-url response data.song (works with HQ)'''
    async def song_info(self, song_id: str, copyright_id: str = '') -> dict:
        if not copyright_id:
            raise AdapterError(404, 'migu by-id needs copyrightId — pass `copyright` from the search item extra')
        headers = {'Content-Type': 'application/json;charset=UTF-8', 'birth': 'h5page', 'signature': '1'}
        params = [('contentId', song_id), ('copyrightId', copyright_id), ('resourceType', '2'),
                  ('netType', '01'), ('toneFlag', 'HQ'), ('scene', ''), ('lowerQualityContentId', song_id)]
        def _fetch():
            resp = self.client.get('https://c.musicapp.migu.cn/strategy/listen-url/h5/v2.4', params=params, headers=headers)
            return self.client._decryptresp(resp=resp)
        result = await self.run(_fetch)
        song = (result.get('data') or {}).get('song') or {}
        if not song: raise AdapterError(404, 'song not found')
        singers = song.get('singer') or ''
        if isinstance(singers, list): singers = ', '.join(singers)
        return {'id': str(song_id), 'source': self.source_key, 'name': song.get('songName') or song.get('name'),
                'singer': singers or None, 'album': song.get('album') or None,
                'duration_s': int(float(song.get('duration') or 0)) or None, 'cover': song.get('img') or None,
                'raw': {'migu_song': {k: song.get(k) for k in list(song)[:12]}}}

    '''lyric via lyricUrl strategy (needs search item's lyric info); simplified to empty otherwise'''
    async def lyric(self, song_id: str, copyright_id: str = '') -> str:
        return ''


def resp2json_migu(client, resp):
    return client._decryptresp(resp=resp)
