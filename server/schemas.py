'''
Function:
    Pydantic response schemas (unified envelope: {code, msg, data, timestamp})
'''
import time
from typing import Optional, List, Any
from pydantic import BaseModel, Field, field_validator


def _coerce_int(v):
    '''upstream numbers arrive as floats sometimes (qq third-party chain returned
       duration 228.98 -> 500 on a strict int field); truncate or drop, never fail'''
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


class Envelope(BaseModel):
    code: int = 200
    msg: str = 'success'
    data: Any = None
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class SearchItem(BaseModel):
    id: str
    name: Optional[str] = None
    singer: Optional[str] = None
    album: Optional[str] = None
    ext: Optional[str] = None
    size_bytes: Optional[int] = None
    duration_s: Optional[int] = None
    cover: Optional[str] = None
    source: str
    # search-stage quality stock (qq file sizes / netease hr-sq-h tiers) — lets
    # clients show what the platform stocks before any per-song resolve happens.
    stock_tier: Optional[str] = None
    stock_size_bytes: Optional[int] = None
    # 有序曲目场景（/{source}/album）的曲序号，1 起；search 场景恒 None
    track_no: Optional[int] = None
    # platform-specific fields the client should echo back to /song/url
    # (e.g. migu needs copyrightId for by-id resolution)
    extra: dict = {}


class SearchData(BaseModel):
    keywords: str
    page: int = 1
    total: int = 0
    items: List[SearchItem] = []


class AlbumEntry(BaseModel):
    id: str
    name: Optional[str] = None
    artist: Optional[str] = None
    size: Optional[int] = None  # 曲目数（平台口径）
    cover: Optional[str] = None
    source: str
    extra: dict = {}


class AlbumData(BaseModel):
    """P6 专辑检索：albums = 候选专辑（首个为最优匹配），items = 首选专辑的有序曲目（track_no 1 起）"""
    source: str
    name: str
    artist: Optional[str] = None
    albums: List[AlbumEntry] = []
    items: List[SearchItem] = []
    total: int = 0


class PlaylistEntry(BaseModel):
    id: str
    name: Optional[str] = None
    creator: Optional[str] = None
    track_count: Optional[int] = None
    play_count: Optional[int] = None
    cover: Optional[str] = None
    source: Optional[str] = None
    extra: dict = {}


class PlaylistData(BaseModel):
    """P6 歌单检索：playlists = 候选歌单（首个为最优匹配），items = 首选歌单的有序曲目（track_no 1 起）"""
    source: str
    name: str
    playlists: List[PlaylistEntry] = []
    items: List[SearchItem] = []
    total: int = 0


class SongUrlData(BaseModel):
    id: str
    source: str
    quality: str
    url: str
    ext: Optional[str] = None
    size_bytes: Optional[int] = None
    bitrate_kbps: Optional[int] = None
    duration_s: Optional[int] = None
    cover: Optional[str] = None
    verified: bool = False
    headers: dict = {}
    parser: Optional[str] = None
    platform_tag: Optional[str] = None   # upstream native quality tag (2000kflac/lossless/SQ/HQ...)
    ekey: Optional[str] = None           # kuwo zhenpin: QMC key to decrypt mflac/mgg -> flac/ogg
    elapsed_ms: int = 0
    cached: bool = False

    _int_fields = field_validator('size_bytes', 'bitrate_kbps', 'duration_s', mode='before')(_coerce_int)


class SongInfoData(BaseModel):
    id: str
    source: str
    name: Optional[str] = None
    singer: Optional[str] = None
    album: Optional[str] = None
    duration_s: Optional[int] = None
    cover: Optional[str] = None
    # identity fields the client should pass back to the v2 playback contract
    # (e.g. bilibili verified cid/page for the selected part)
    extra: dict = {}
    raw: dict = {}


class LyricData(BaseModel):
    id: str
    source: str
    lyric: str = ''
    cached: bool = False


'''---------------- v2 managed playback contract ----------------'''


class TrackRefBody(BaseModel):
    '''request side: stable source identity; no URL, cookie or ekey is accepted'''
    source: str
    id: str
    extra: dict = {}


class ProfileBody(BaseModel):
    '''playback policy. quality is the ORIGINAL caller spelling (whitelisted before
       normalization); target=device is the managed-playback delivery profile,
       target=media_prepare is Songloft's media-preparation profile.'''
    quality: str = 'auto'
    target: str = 'device'


class PlaybackResolveBody(BaseModel):
    track_ref: TrackRefBody
    profile: ProfileBody = ProfileBody()
    freshness: str = 'allow_cache'   # allow_cache | revalidate


class InvalidateBody(BaseModel):
    '''scoped cache invalidation: exact identity + policy of the caller's generation'''
    track_ref: TrackRefBody
    profile: ProfileBody = ProfileBody()


class TrackRefData(BaseModel):
    kind: str = 'remote'
    provider: str = 'kwqq'
    source: str
    id: str
    extra: dict = {}


class VerificationData(BaseModel):
    '''kwqq can only assert upstream declaration / partial bytes; a full-file
       verification happens in Songloft's preparation chain, never here.'''
    level: str = 'partial'                   # declared | partial | full
    requires_byte_verification: bool = True
    requires_transcode: bool = False


class PlaybackResolveData(BaseModel):
    track_ref: TrackRefData
    resolved_source: str
    requested_quality: str
    delivered_quality: Optional[str] = None
    codec: Optional[str] = None
    url: str
    ext: Optional[str] = None
    size_bytes: Optional[int] = None
    bitrate_kbps: Optional[int] = None
    duration_s: Optional[int] = None
    cover: Optional[str] = None
    headers: dict = {}
    parser: Optional[str] = None
    platform_tag: Optional[str] = None
    verification: VerificationData = VerificationData()
    ready: bool = False                     # device-deliverable once byte verification passes
    verified: bool = False                   # honest: kwqq never fully verifies a file
    fallback_reason: Optional[str] = None
    resolved_at: int = 0
    cache_expires_at: Optional[int] = None
    upstream_expires_at: Optional[int] = None
    cached: bool = False

    _int_fields = field_validator('size_bytes', 'bitrate_kbps', 'duration_s', mode='before')(_coerce_int)


class SearchMultiData(BaseModel):
    """P7 多类型搜索：items 形状随 type 变化（MusicFree 语义归一，全部带 source）——
    album {id,name,artist,cover,track_count} / artist {id,name,avatar} /
    sheet {id,name,creator,cover,track_count,play_count}"""
    source: str
    type: str
    keywords: str
    page: int = 1
    total: Optional[int] = None
    items: List[dict] = []


# ---- P8 在线浏览：榜单 / 推荐歌单（2026-11-04，kuwo 首发） ----

class ToplistEntry(BaseModel):
    id: str
    name: Optional[str] = None
    cover: Optional[str] = None
    description: Optional[str] = None
    update_frequency: Optional[str] = None
    source: str


class ToplistsData(BaseModel):
    """P8 榜单列表：平台全部榜单（平铺，不做二级分组——分组交给客户端）"""
    source: str
    items: List[ToplistEntry] = []


class TagEntry(BaseModel):
    id: str
    title: Optional[str] = None


class TagGroup(BaseModel):
    title: Optional[str] = None
    data: List[TagEntry] = []


class PlaylistTagsData(BaseModel):
    """P8 推荐歌单标签：pinned 热门 + groups 全量分类（MusicFree 语义归一）"""
    source: str
    pinned: List[TagEntry] = []
    groups: List[TagGroup] = []


class SheetListData(BaseModel):
    """P8 标签下推荐歌单列表（PlaylistEntry 复用 P6 歌单检索形状，extra 带平台专有字段）"""
    source: str
    tag: str = ''
    page: int = 1
    is_end: bool = True
    total: Optional[int] = None
    items: List[PlaylistEntry] = []


class SheetSongsData(BaseModel):
    """P8 歌单/榜单内曲目（by id 分页）；meta 仅 page=1 附歌单/榜单元数据"""
    source: str
    id: str
    page: int = 1
    is_end: bool = True
    total: Optional[int] = None
    items: List[SearchItem] = []
    meta: Optional[PlaylistEntry] = None


# ---- P9 浏览收编二期（2026-11-04，netease/kugou）：歌手 / 评论 ----

class ArtistEntry(BaseModel):
    id: str
    name: Optional[str] = None
    avatar: Optional[str] = None
    alias: Optional[str] = None
    description: Optional[str] = None
    album_count: Optional[int] = None
    music_count: Optional[int] = None
    source: str


class ArtistData(BaseModel):
    source: str
    artist: ArtistEntry


class ArtistWorksData(BaseModel):
    """P9 歌手作品：type=music → items 为 SearchItem 形状；type=album → AlbumEntry 形状"""
    source: str
    id: str
    type: str
    page: int = 1
    is_end: bool = True
    total: Optional[int] = None
    items: List[dict] = []


class CommentEntry(BaseModel):
    id: str
    nick_name: Optional[str] = None
    avatar: Optional[str] = None
    content: Optional[str] = None
    like: Optional[int] = None
    created_at: Optional[int] = None   # 毫秒时间戳
    replies: List[dict] = []


class CommentsData(BaseModel):
    source: str
    id: str
    page: int = 1
    total: Optional[int] = None
    has_more: bool = False
    hot: List[CommentEntry] = []
    items: List[CommentEntry] = []
