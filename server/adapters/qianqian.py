'''
Function:
    Qianqian (Baidu 91q) adapter — signed official API, naturally by-id friendly.
    tracklink(TSID, rate) resolves directly; response also carries song meta.
'''
from .base import SourceAdapter, AdapterError
from musicdl.modules.sources.qianqian import QianqianMusicClient

LOSSLESS_RATES = {'3000'}


class QianqianAdapter(SourceAdapter):
    source_key = 'qianqian'

    def _build_client(self) -> QianqianMusicClient:
        return QianqianMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-qqy', max_retries=2,
        )

    '''metadata-only search via /v1/search (signed), no parse chain'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        params = self.client._addsignandtstoparams(params={'word': keywords, 'type': '1',
                                                  'pageNo': str(page), 'pageSize': str(limit),
                                                  'appid': self.client.APPID})
        resp = self.client.get('https://music.91q.com/v1/search', params=params)
        return ((resp.json().get('data') or {}).get('typeTrack')) or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        artists = ', '.join(a.get('name') for a in (raw.get('artist') or []) if isinstance(a, dict) and a.get('name'))
        return {'id': str(raw.get('TSID') or ''), 'name': raw.get('title'), 'singer': artists or None,
                'album': raw.get('albumTitle'), 'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('duration') or 0)) or None,
                'cover': raw.get('pic'), 'source': 'qianqian'}

    def _tracklink(self, tsid: str, rate: str) -> dict:
        params = self.client._addsignandtstoparams(params={'TSID': tsid, 'appid': self.client.APPID, 'rate': rate})
        resp = self.client.get('https://music.91q.com/v1/song/tracklink', params=params)
        data = (resp.json() or {}).get('data') or {}
        path = data.get('path') or (data.get('trail_audio_info') or {}).get('path') or ''
        # size/format/bits/rate are the server-declared file attributes of THIS link —
        # exact payload size and bit depth, far more reliable than any tier promise.
        return {'path': path if str(path).startswith('http') else '',
                **{k: data.get(k) for k in ('title', 'duration', 'size', 'format', 'bits', 'rate')}}

    '''quality routing: auto/320k/128k capped at 320; flac/hires gated by ENABLE_LOSSLESS'''
    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '192k', '128k', 'flac', 'hires'} else 'auto'
        if q == '192k': q = '320k'  # no native 192k tier — snap up to 320k
        t0 = __import__('time').perf_counter()
        import time
        elapsed = lambda: round((time.perf_counter() - t0) * 1000)
        rates = {'128k': ['128'], '320k': ['320'], 'auto': ['320', '128'],
                 'flac': ['3000'], 'hires': ['3000']}[q]
        if q in {'flac', 'hires'} and not self.settings.enable_lossless:
            raise AdapterError(403, 'lossless tier disabled on this server (ENABLE_LOSSLESS=false)')
        for rate in rates:
            link = await self.run(self._tracklink, song_id, rate)
            if not link['path']: continue
            status = await self.run(self.client.audio_link_tester.test, link['path'])
            if not status.get('ok'): continue
            link_size = int(float(link.get('size') or 0)) or None
            bits = str(link.get('bits') or '')
            platform_tag = f'{rate}kbps' + (f'·{bits}bit' if bits else '')
            return {'id': str(song_id), 'source': self.source_key, 'quality': q,
                    'url': status.get('download_url') or link['path'], 'ext': status.get('ext'),
                    'size_bytes': status.get('file_size_bytes') or link_size,
                    'bitrate_kbps': int(rate) if rate.isdigit() else None,
                    'duration_s': int(float(link.get('duration') or 0)) or None,
                    'cover': None, 'verified': True, 'headers': {}, 'parser': f'tracklink.{rate}',
                    'platform_tag': platform_tag,
                    'elapsed_ms': elapsed(), 'cached': False}
        raise AdapterError(404, f'no playable url resolved (rates tried: {rates})')

    '''song meta via tracklink response fields (works with any available rate)'''
    async def song_info(self, song_id: str) -> dict:
        for rate in ('320', '3000', '128'):
            link = await self.run(self._tracklink, song_id, rate)
            if link['path'] or link.get('title'):
                return {'id': str(song_id), 'source': self.source_key, 'name': link.get('title'),
                        'singer': None, 'album': None,
                        'size_bytes': int(float(link.get('size') or 0)) or None,
                        'duration_s': int(float(link.get('duration') or 0)) or None, 'cover': None,
                        'raw': {'qqy_note': 'full artist/album available in search items'}}
        raise AdapterError(404, 'song not found')

    '''lyric url only exists inside search results; by-id lyric not supported upstream'''
    async def lyric(self, song_id: str) -> str:
        return ''
