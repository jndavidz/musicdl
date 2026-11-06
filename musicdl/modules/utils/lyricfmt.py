'''
Function:
    Per-word lyric (逐字) helpers shared by the API adapters.

    Formats implemented here:
      - QQ QRC   : hex ciphertext -> custom-DES-EDE -> zlib -> XML (per-word times)
      - Netease YRC : plain JSON text "[start,dur](offset,dur,0)word..."
      - Kuwo LRCX  : plain text with "[kuwo:<octal>]" scale tag, words encoded as <a,b>
    All three are normalised to LX Music (洛雪) per-word format:
        [mm:ss.mmm]<offset_ms,duration_ms>text<offset_ms,duration_ms>text...
    where `offset` is relative to the LINE start, which is what songloft / LX Music
    consume as `lxlyric`.

    The QRC cipher is QQ's own DES variant (bit layout differs from standard DES),
    so it cannot be delegated to pycryptodome; the tables and the round function
    below are a line-by-line port of the reference implementation used by
    smart-lyric / qrc-decoder (both produce identical plaintext for the same
    ciphertext, verified 2026-11-06 against the live musicu.fcg payload).
'''
import re
import zlib

_MASK32 = 0xFFFFFFFF

_QRC_KEY1 = b'!@#)(NHL'
_QRC_KEY2 = b'123ZXC!@'
_QRC_KEY3 = b'!@#)(*$%'

_DES_TRANSFORM = (
    57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18,
    10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36,
    63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22,
    14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4,
)
_DES_ROTATIONS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)
_DES_PERMUTED = (
    14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10,
    23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2,
    41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48,
    44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32,
)
_DES_INITIAL = (
    58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7,
)
_DES_FINAL = (
    40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31,
    38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29,
    36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
    34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25,
)
_DES_PBOX = (
    16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
    2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25,
)
_DES_EXPANSION = (
    32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9,
    8, 9, 10, 11, 12, 13, 12, 13, 14, 15, 16, 17,
    16, 17, 18, 19, 20, 21, 20, 21, 22, 23, 24, 25,
    24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1,
)
_DES_SBOX = (
    0x0E, 0x00, 0x04, 0x0F, 0x0D, 0x07, 0x01, 0x04, 0x02, 0x0E, 0x0F, 0x02, 0x0B, 0x0D, 0x08, 0x01,
    0x03, 0x0A, 0x0A, 0x06, 0x06, 0x0C, 0x0C, 0x0B, 0x05, 0x09, 0x09, 0x05, 0x00, 0x03, 0x07, 0x08,
    0x04, 0x0F, 0x01, 0x0C, 0x0E, 0x08, 0x08, 0x02, 0x0D, 0x04, 0x06, 0x09, 0x02, 0x01, 0x0B, 0x07,
    0x0F, 0x05, 0x0C, 0x0B, 0x09, 0x03, 0x07, 0x0E, 0x03, 0x0A, 0x0A, 0x00, 0x05, 0x06, 0x00, 0x0D,
    0x0F, 0x03, 0x01, 0x0D, 0x08, 0x04, 0x0E, 0x07, 0x06, 0x0F, 0x0B, 0x02, 0x03, 0x08, 0x04, 0x0F,
    0x09, 0x0C, 0x07, 0x00, 0x02, 0x01, 0x0D, 0x0A, 0x0C, 0x06, 0x00, 0x09, 0x05, 0x0B, 0x0A, 0x05,
    0x00, 0x0D, 0x0E, 0x08, 0x07, 0x0A, 0x0B, 0x01, 0x0A, 0x03, 0x04, 0x0F, 0x0D, 0x04, 0x01, 0x02,
    0x05, 0x0B, 0x08, 0x06, 0x0C, 0x07, 0x06, 0x0C, 0x09, 0x00, 0x03, 0x05, 0x02, 0x0E, 0x0F, 0x09,
    0x0A, 0x0D, 0x00, 0x07, 0x09, 0x00, 0x0E, 0x09, 0x06, 0x03, 0x03, 0x04, 0x0F, 0x06, 0x05, 0x0A,
    0x01, 0x02, 0x0D, 0x08, 0x0C, 0x05, 0x07, 0x0E, 0x0B, 0x0C, 0x04, 0x0B, 0x02, 0x0F, 0x08, 0x01,
    0x0D, 0x01, 0x06, 0x0A, 0x04, 0x0D, 0x09, 0x00, 0x08, 0x06, 0x0F, 0x09, 0x03, 0x08, 0x00, 0x07,
    0x0B, 0x04, 0x01, 0x0F, 0x02, 0x0E, 0x0C, 0x03, 0x05, 0x0B, 0x0A, 0x05, 0x0E, 0x02, 0x07, 0x0C,
    0x07, 0x0D, 0x0D, 0x08, 0x0E, 0x0B, 0x03, 0x05, 0x00, 0x06, 0x06, 0x0F, 0x09, 0x00, 0x0A, 0x03,
    0x01, 0x04, 0x02, 0x07, 0x08, 0x02, 0x05, 0x0C, 0x0B, 0x01, 0x0C, 0x0A, 0x04, 0x0E, 0x0F, 0x09,
    0x0A, 0x03, 0x06, 0x0F, 0x09, 0x00, 0x00, 0x06, 0x0C, 0x0A, 0x0B, 0x0A, 0x07, 0x0D, 0x0D, 0x08,
    0x0F, 0x09, 0x01, 0x04, 0x03, 0x05, 0x0E, 0x0B, 0x05, 0x0C, 0x02, 0x07, 0x08, 0x02, 0x04, 0x0E,
    0x02, 0x0E, 0x0C, 0x0B, 0x04, 0x02, 0x01, 0x0C, 0x07, 0x04, 0x0A, 0x07, 0x0B, 0x0D, 0x06, 0x01,
    0x08, 0x05, 0x05, 0x00, 0x03, 0x0F, 0x0F, 0x0A, 0x0D, 0x03, 0x00, 0x09, 0x0E, 0x08, 0x09, 0x06,
    0x04, 0x0B, 0x02, 0x08, 0x01, 0x0C, 0x0B, 0x07, 0x0A, 0x01, 0x0D, 0x0E, 0x07, 0x02, 0x08, 0x0D,
    0x0F, 0x06, 0x09, 0x0F, 0x0C, 0x00, 0x05, 0x09, 0x06, 0x0A, 0x03, 0x04, 0x00, 0x05, 0x0E, 0x03,
    0x0C, 0x0A, 0x01, 0x0F, 0x0A, 0x04, 0x0F, 0x02, 0x09, 0x07, 0x02, 0x0C, 0x06, 0x09, 0x08, 0x05,
    0x00, 0x06, 0x0D, 0x01, 0x03, 0x0D, 0x04, 0x0E, 0x0E, 0x00, 0x07, 0x0B, 0x05, 0x03, 0x0B, 0x08,
    0x09, 0x04, 0x0E, 0x03, 0x0F, 0x02, 0x05, 0x0C, 0x02, 0x09, 0x08, 0x05, 0x0C, 0x0F, 0x03, 0x0A,
    0x07, 0x0B, 0x00, 0x0E, 0x04, 0x01, 0x0A, 0x07, 0x01, 0x06, 0x0D, 0x00, 0x0B, 0x08, 0x06, 0x0D,
    0x04, 0x0D, 0x0B, 0x00, 0x02, 0x0B, 0x0E, 0x07, 0x0F, 0x04, 0x00, 0x09, 0x08, 0x01, 0x0D, 0x0A,
    0x03, 0x0E, 0x0C, 0x03, 0x09, 0x05, 0x07, 0x0C, 0x05, 0x02, 0x0A, 0x0F, 0x06, 0x08, 0x01, 0x06,
    0x01, 0x06, 0x04, 0x0B, 0x0B, 0x0D, 0x0D, 0x08, 0x0C, 0x01, 0x03, 0x04, 0x07, 0x0A, 0x0E, 0x07,
    0x0A, 0x09, 0x0F, 0x05, 0x06, 0x00, 0x08, 0x0F, 0x00, 0x0E, 0x05, 0x02, 0x09, 0x03, 0x02, 0x0C,
    0x0D, 0x01, 0x02, 0x0F, 0x08, 0x0D, 0x04, 0x08, 0x06, 0x0A, 0x0F, 0x03, 0x0B, 0x07, 0x01, 0x04,
    0x0A, 0x0C, 0x09, 0x05, 0x03, 0x06, 0x0E, 0x0B, 0x05, 0x00, 0x00, 0x0E, 0x0C, 0x09, 0x07, 0x02,
    0x07, 0x02, 0x0B, 0x01, 0x04, 0x0E, 0x01, 0x07, 0x09, 0x04, 0x0C, 0x0A, 0x0E, 0x08, 0x02, 0x0D,
    0x00, 0x0F, 0x06, 0x0C, 0x0A, 0x09, 0x0D, 0x00, 0x0F, 0x03, 0x03, 0x05, 0x05, 0x06, 0x08, 0x0B,
)
_BITMAP = tuple(1 << (31 - i) for i in range(32)) * 2

_VERSION_CONVERT_CODE = bytes.fromhex(
    '77483273def2c0c895ec30b251c3e1a0'
    '9ee69dcffa7f14d1ceb8dcc34a6793d6'
    '28c29170ca8da2a4f00861907e6fa2e0'
    'ebae3eb667c792f491b5f66c5e8440f7'
    'f31b027fd5ab418928f425cc5211ad43'
    '68a6418b84b5ff2c924a26d8476a7c95'
    '61cce6cbbb3f47588975c375a1d9afcc'
    '087317dcaa9aa21641d8a206c68bfc66'
    '349fcf1823a00a74e72b277092e9af37'
    'e68ca7bc62659cc208c988b3f343ac74'
    '2c0fd4afa1c30164954e489ff4357895'
    '7a39d66aa06d40e84fa8ef111df31b3f'
    '3f07dd6f5b193019fbef0e37f00ecd16'
    '49fe5347131abda4f14019600eed6809'
    '065f4dcf3d1afe2077e4d9daf9a42b76'
    '1c71db00bcfd0c6ca547f7f600794a11')


def _des_subkeys(key: bytes) -> tuple:
    first_low = int.from_bytes(key[0:4], 'little')
    first_high = int.from_bytes(key[4:8], 'little')
    temp_low = temp_high = 0
    for i in range(28):
        item = _DES_TRANSFORM[i]
        got = (first_low if item <= 32 else first_high) & _BITMAP[item - 1]
        if got:
            temp_low |= _BITMAP[i]
        item = _DES_TRANSFORM[i + 28]
        got = (first_low if item <= 32 else first_high) & _BITMAP[item - 1]
        if got:
            temp_high |= _BITMAP[i]
    subs = []
    for index in range(16):
        rcnt = _DES_ROTATIONS[index]
        mask = (0, 0x80000000, 0xC0000000)[rcnt]
        v6 = temp_low & mask
        v7 = temp_high & mask
        if rcnt == 1:
            v6 >>= 27
            v7 >>= 27
        else:
            v6 >>= 26
            v7 >>= 26
        temp_low = ((temp_low << rcnt) & _MASK32) | (v6 & 0xFFFFFFF0)
        temp_high = ((temp_high << rcnt) & _MASK32) | (v7 & 0xFFFFFFF0)
        sub_low = sub_high = 0
        for i in range(48):
            v10 = _DES_PERMUTED[i]
            if i >= 24:
                if _BITMAP[v10 - 28] & temp_high:
                    sub_high |= _BITMAP[i - 24]
            elif _BITMAP[v10 - 1] & temp_low:
                sub_low |= _BITMAP[i]
        subs.append((sub_low & _MASK32, sub_high & _MASK32))
    return tuple(subs)


def _des_round(low: int, high: int, sub: tuple) -> tuple:
    l = h = 0
    temp_high = high
    for i in range(48):
        mask = _BITMAP[_DES_EXPANSION[i] - 1]
        if i >= 24:
            if mask & temp_high:
                h |= _BITMAP[i - 24]
        elif mask & temp_high:
            l |= _BITMAP[i]
    l ^= sub[0]
    h ^= sub[1]
    nibbles = (
        (l >> 26) & 0x3F, (l >> 20) & 0x3F, (l >> 14) & 0x3F, (l >> 8) & 0x3F,
        (h >> 26) & 0x3F, (h >> 20) & 0x3F, (h >> 14) & 0x3F, (h >> 8) & 0x3F,
    )
    packed = 0
    for idx in range(7):
        packed = ((packed | _DES_SBOX[nibbles[idx] + 64 * idx]) << 4) & _MASK32
    packed = (packed | _DES_SBOX[448 + nibbles[7]]) & _MASK32
    tmp = 0
    for i in range(32):
        if packed & _BITMAP[_DES_PBOX[i] - 1]:
            tmp |= _BITMAP[i]
    return temp_high, (tmp ^ low) & _MASK32


def _des_block(low: int, high: int, subs: tuple, encrypt: bool) -> tuple:
    l = h = 0
    for i in range(64):
        v = _DES_INITIAL[i]
        src = (low if v <= 32 else high) & _BITMAP[v - 1]
        if src:
            if i >= 32:
                h |= _BITMAP[i]
            else:
                l |= _BITMAP[i]
    low, high = l & _MASK32, h & _MASK32
    for i in (range(16) if encrypt else range(15, -1, -1)):
        low, high = _des_round(low, high, subs[i])
    low, high = high, low
    l = h = 0
    for i in range(64):
        v = _DES_FINAL[i]
        src = (low if v <= 32 else high) & _BITMAP[v - 1]
        if src:
            if i >= 32:
                h |= _BITMAP[i]
            else:
                l |= _BITMAP[i]
    return l & _MASK32, h & _MASK32


def _des_crypt(data: bytes, key: bytes, encrypt: bool) -> bytes:
    subs = _des_subkeys(key)
    out = bytearray(len(data))
    for off in range(0, len(data), 8):
        low = int.from_bytes(data[off:off + 4], 'little')
        high = int.from_bytes(data[off + 4:off + 8], 'little')
        low, high = _des_block(low, high, subs, encrypt)
        out[off:off + 4] = low.to_bytes(4, 'little')
        out[off + 4:off + 8] = high.to_bytes(4, 'little')
    return bytes(out)


def qrcdecrypt(hexstr: str) -> str:
    '''QQ QRC 密文（hex 字符串）→ 明文 XML；失败返回 ''。'''
    try:
        buf = bytes.fromhex(''.join(str(hexstr).split()))
    except Exception:
        return ''
    if not buf:
        return ''
    if buf[:2] == b'\x98\x25':           # 新版：先用固定流还原旧版
        buf = bytes(v ^ _VERSION_CONVERT_CODE[(i * i + 0x013C1B) % 256]
                    for i, v in enumerate(buf))
    if buf[:8] == b'[offset:':           # .qrc 文件：去掉明文头，再补零对齐
        buf = buf[11:]
    if len(buf) % 8:
        buf += b'\x00' * (8 - len(buf) % 8)
    for key, enc in ((_QRC_KEY1, False), (_QRC_KEY2, True), (_QRC_KEY3, False)):
        buf = _des_crypt(buf, key, enc)
    try:
        return zlib.decompress(buf).decode('utf-8', errors='ignore')
    except Exception:
        return ''


def _lxlyric_ts(start_ms: int) -> str:
    start_ms = max(0, int(start_ms))
    return f'[{start_ms // 60000:02d}:{start_ms // 1000 % 60:02d}.{start_ms % 1000:03d}]'


def _lxlyric_line(line_start: int, segs) -> str:
    segs = [(max(0, int(off)), max(0, int(dur)), txt) for off, dur, txt in segs if txt]
    if not segs:
        return ''
    return _lxlyric_ts(line_start) + ''.join(f'<{off},{dur}>{txt}' for off, dur, txt in segs)


def qrc2lxlyric(xml_text: str) -> str:
    '''QRC 明文 XML → 洛雪逐字。LyricContent 里的 (绝对ms,时长) 减行头得到行内偏移。'''
    if not xml_text:
        return ''
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
    except Exception:
        return ''
    content = ''
    for node in root.iter():
        if node.tag.split('}')[-1].startswith('Lyric_') and node.get('LyricType', '1') == '1':
            content = node.get('LyricContent') or ''
            if content:
                break
    # XML 属性值规范化会把歌词里的换行压成空格，所以不能按行切；改按行首 [start,dur] 切段。
    marks = list(re.finditer(r'\[(\d+),(\d+)\]', content))
    out = []
    for idx, mark in enumerate(marks):
        start = int(mark.group(1))
        body = content[mark.end():marks[idx + 1].start() if idx + 1 < len(marks) else len(content)]
        segs = [(int(a) - start, int(b), txt.strip())
                for a, b, txt in re.findall(r'\((\d+),(\d+)\)([^(]*)', body)]
        line = _lxlyric_line(start, segs)
        if line:
            out.append(line)
    return '\n'.join(out)


def yrc2lxlyric(text: str) -> str:
    '''网易云 YRC → 洛雪逐字。行 [start,dur]，逐字 (绝对ms,时长,保留)文本。'''
    if not text:
        return ''
    out = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith('{'):      # 跳过 {"t":..,"c":[..]} 元信息行
            continue
        m = re.match(r'\[(\d+),(\d+)\](.*)$', line)
        if not m:
            continue
        start = int(m.group(1))
        segs = [(int(a) - start, int(b), txt)
                for a, b, txt in re.findall(r'\((\d+),(\d+),\d+\)([^(]*)', m.group(3))]
        rendered = _lxlyric_line(start, segs)
        if rendered:
            out.append(rendered)
    return '\n'.join(out)


def lrcx2lxlyric(text: str) -> str:
    '''酷我 LRCX → 洛雪逐字。文件带 [kuwo:<八进制>]，<a,b> 需按 k1/k2 解算：
       行内偏移 = (a+b)/(k1*2)，时长 = (a-b)/(k2*2)。'''
    if not text:
        return ''
    tag = re.search(r'\[kuwo:([0-7]*[1-7])\]', str(text))
    if not tag:
        return ''
    kuwo = int(tag.group(1), 8)
    k1, k2 = kuwo // 10, kuwo % 10
    if k1 <= 0 or k2 <= 0:
        return ''
    out = []
    for raw in str(text).splitlines():
        m = re.match(r'\[(\d{1,3}):(\d{1,2})\.(\d{1,3})\](.*)$', raw.strip())
        if not m:
            continue
        start = int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int(m.group(3).ljust(3, '0'))
        payload = m.group(4)
        if payload.startswith('<0,0>'):      # 译文行：整行标 <0,0>，不是逐字数据
            continue
        segs = [((int(a) + int(b)) / (k1 * 2), (int(a) - int(b)) / (k2 * 2), txt)
                for a, b, txt in re.findall(r'<(-?\d+),(-?\d+)>([^<]*)', payload)]
        segs = [(round(off), round(dur), txt) for off, dur, txt in segs]
        rendered = _lxlyric_line(start, segs)
        if rendered:
            out.append(rendered)
    return '\n'.join(out)
