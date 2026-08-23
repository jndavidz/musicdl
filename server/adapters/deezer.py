'''
Function:
    Deezer adapter — public search/meta APIs + third-party resolver chain.
    The official media.deezer.com stream is BF_CBC_STRIPE encrypted (not directly
    playable), so /song/url goes through the musicdl third-party chain which yields
    decrypted direct links (anandserver stream API first).
    NOTE: the chain includes a job-queue parser (antrahoshi, up to ~120s) — this
    adapter overrides the hard timeout accordingly.
'''
import time
from .base import SourceAdapter, AdapterError
from musicdl.modules.sources.deezer import DeezerMusicClient
from musicdl.modules.utils import AudioLinkTester


class DeezerAdapter(SourceAdapter):
    source_key = 'deezer'
    # antrahoshi job queue can legitimately take ~2 minutes
    timeout_override = 150

    def _build_client(self) -> DeezerMusicClient:
        return DeezerMusicClient(
            search_size_per_source=self.settings.search_size_max, search_size_per_page=25,
            disable_print=True, work_dir='/tmp/kwqq-deezer', max_retries=2,
            maintain_session=True,
        )

    async def run(self, fn, *args, **kwargs):
        # widen hard timeout for deezer's slow resolvers
        timeout = max(self.timeout_override, self.settings.hard_timeout_s)
        return await super().run_with_timeout(fn, timeout, *args, **kwargs)

    '''metadata-only search via public api.deezer.com (no signature needed)'''
    def _search_raw(self, keywords: str, limit: int, page: int) -> list:
        from urllib.parse import urlencode
        resp = self.client.get('https://api.deezer.com/search/track?' +
                               urlencode({'q': keywords, 'index': (page - 1) * limit + 1, 'limit': limit}))
        return (resp.json() or {}).get('data') or []

    @staticmethod
    def item_from_raw(raw: dict) -> dict:
        artist = (raw.get('artist') or {}).get('name')
        album = (raw.get('album') or {}).get('title')
        cover = ((raw.get('album') or {}).get('cover_medium')) or ((raw.get('album') or {}).get('cover_xl'))
        return {'id': str(raw.get('id') or ''), 'name': raw.get('title'), 'singer': artist,
                'album': album, 'ext': None, 'size_bytes': None,
                'duration_s': int(float(raw.get('duration') or 0)) or None,
                'cover': cover, 'source': 'deezer'}

    '''third-party resolver chain by minimal search_result dict ({'id'} suffices)'''
    def _via_thirdparty(self, song_id: str):
        return self.client._parsewiththirdpartapis({'id': song_id}, {})

    '''song meta via gw-light song.getData with api.deezer.com fallback'''
    def _get_meta(self, song_id: str):
        return self.client._getsongmetainfo(song_id=song_id)

    async def song_url(self, song_id: str, quality: str) -> dict:
        q = quality if quality in {'auto', '320k', '128k', 'flac', 'hires'} else 'auto'
        t0 = time.perf_counter()
        if q in {'flac', 'hires'} and not self.settings.enable_lossless:
            raise AdapterError(403, 'lossless tier disabled on this server (ENABLE_LOSSLESS=false)')
        info = await self.run(self._via_thirdparty, song_id)
        elapsed = round((time.perf_counter() - t0) * 1000)
        if not (info.with_valid_download_url and info.ext in AudioLinkTester.VALID_AUDIO_EXTS):
            raise AdapterError(404, 'no playable url resolved')
        data = self.urldata_from_songinfo(song_id, q, info, elapsed)
        data['parser'] = (info.raw_data.get('spike_parser') or 'deezer.chain')
        return data

    async def song_info(self, song_id: str) -> dict:
        meta = await self.run(self._get_meta, song_id)
        if not meta or meta.get('error'): raise AdapterError(404, 'track not found')
        artist = (meta.get('artist') or {}).get('name') if isinstance(meta.get('artist'), dict) else None
        album = (meta.get('album') or {}).get('title') if isinstance(meta.get('album'), dict) else None
        cover = Deezer_cover(meta)
        return {'id': str(song_id), 'source': self.source_key, 'name': meta.get('title') or meta.get('SNG_TITLE'),
                'singer': artist, 'album': album,
                'duration_s': int(float(meta.get('duration') or 0)) or None, 'cover': cover,
                'raw': {'deezer_meta': {k: meta.get(k) for k in ('id', 'title', 'duration', 'bpm')}}}

    '''Deezer has no public lyric endpoint exposed by musicdl; keep empty'''
    async def lyric(self, song_id: str) -> str:
        return ''


def Deezer_cover(meta: dict):
    from musicdl.modules.utils.deezerutils import DeezerMusicClientUtils
    try:
        return DeezerMusicClientUtils.getcoverurl((meta.get('album') or {}).get('picture')) or \
               ((meta.get('album') or {}).get('cover_xl'))
    except Exception:
        return None
