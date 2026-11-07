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
    id: Optional[str] = None
    source: str
    name: str
    artist: Optional[str] = None
    albums: List[AlbumEntry] = []
    items: List[SearchItem] = []
    total: int = 0
    # 整册曲目数（仅 adapter.album_track_count=True 的源给出；其余源为 None，客户端不显示）
    track_count: Optional[int] = None


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
    # 词曲编曲：{lyricist: [], composer: [], arranger: []}（每项都是数组，取不到的留空数组，
    # 不写 null；整源无此能力时 routes 层整个键缺省）。来源是歌词头部的署名行（见 base.parse_credits）。
    credits: Optional[dict] = None
    # identity fields the client should pass back to the v2 playback contract
    # (e.g. bilibili verified cid/page for the selected part)
    extra: dict = {}
    raw: dict = {}


class MvItem(BaseModel):
    '''单条 MV 候选；quality 统一为 ld/sd/hd/fhd（按源实际清晰度归一，不照抄平台档位名）'''
    id: str
    source: str
    title: Optional[str] = None
    artist: Optional[str] = None
    cover: Optional[str] = None
    duration_s: Optional[int] = None
    url: Optional[str] = None
    quality: Optional[str] = None

    _int_fields = field_validator('duration_s', mode='before')(_coerce_int)


class MvData(BaseModel):
    '''MV 契约：顶层永远是「首个可直接播放的 MV」。拿不到时 url=None（HTTP 200 + code 200，
       业务未命中不做 404、不返回空对象）。items 仅在源确有多个 MV 时给出（按可播性排序）。'''
    id: str
    source: str
    url: Optional[str] = None
    cover: Optional[str] = None
    duration_s: Optional[int] = None
    quality: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    items: List[MvItem] = []

    _int_fields = field_validator('duration_s', mode='before')(_coerce_int)


class SearchMvData(BaseModel):
    '''MV 搜索契约（`GET /{source}/search?type=mv`）：只换 items 形状，不改歌曲搜索字段。
       type 固定回显 'mv'；items 与 MvItem 同构，url 恒为 None（点击后再走 /{source}/mv?id= 现取），
       id 是该源 MV 端点可直接接收的 id（详见 docs/API-REFERENCE.md §4.12）。'''
    source: str
    type: str = 'mv'
    keywords: str
    page: int = 1
    total: int = 0
    items: List[MvItem] = []


class LyricData(BaseModel):
    id: str
    source: str
    lyric: str = ''
    # 逐字歌词（洛雪格式：行前缀 [mm:ss.mmm]，逐字 <偏移ms,时长ms>文本，偏移相对行首）。
    # 字段名固定，客户端按此消费；源无逐字通道时为 null。
    lxlyric: Optional[str] = None
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
    created_at: Optional[int] = None   # 毫秒时间戳（历史字段，保留兼容）
    # 统一发布时间契约（2026-11）：Unix 秒。上游是毫秒的来源由 adapter 换算，
    # 只给格式化文本的来源（酷狗 addtime）尽力解析成秒，解析不了才落到 create_time_text。
    create_time: Optional[int] = None
    create_time_text: Optional[str] = None
    replies: List[dict] = []


class CommentsData(BaseModel):
    source: str
    id: str
    page: int = 1
    total: Optional[int] = None
    has_more: bool = False
    hot: List[CommentEntry] = []
    items: List[CommentEntry] = []


# ---- P9c 导入协议（2026-11-04）：importMusicItem / importMusicSheet ----

class ImportItemData(BaseModel):
    """urlLike → 单曲（MusicFree importMusicItem 语义）"""
    source: str
    url: str
    item: Optional[SearchItem] = None


class ImportSheetData(BaseModel):
    """urlLike → 歌单全量曲目（MusicFree importMusicSheet 语义；超上限截断并标 truncated）"""
    source: str
    url: str
    total: int = 0
    truncated: bool = False
    items: List[SearchItem] = []
