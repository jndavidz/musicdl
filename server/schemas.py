'''
Function:
    Pydantic response schemas (unified envelope: {code, msg, data, timestamp})
'''
import time
from typing import Optional, List, Any
from pydantic import BaseModel, Field


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
    # platform-specific fields the client should echo back to /song/url
    # (e.g. migu needs copyrightId for by-id resolution)
    extra: dict = {}


class SearchData(BaseModel):
    keywords: str
    page: int = 1
    total: int = 0
    items: List[SearchItem] = []


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
    elapsed_ms: int = 0
    cached: bool = False


class SongInfoData(BaseModel):
    id: str
    source: str
    name: Optional[str] = None
    singer: Optional[str] = None
    album: Optional[str] = None
    duration_s: Optional[int] = None
    cover: Optional[str] = None
    raw: dict = {}


class LyricData(BaseModel):
    id: str
    source: str
    lyric: str = ''
    cached: bool = False
