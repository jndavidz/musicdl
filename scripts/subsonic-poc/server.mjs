import http from 'node:http';
import crypto from 'node:crypto';
import { Readable } from 'node:stream';

const PORT = Number(process.env.PORT || 4533);
const KWQQ = process.env.KWQQ || 'http://10.10.10.2:3003';
const SOURCES = (process.env.SOURCES || 'kuwo').split(',').map((s) => s.trim()).filter(Boolean);
const ID_TTL_MS = Number(process.env.ID_TTL_MS || 10 * 60 * 1000);
const URL_TTL_MS = Number(process.env.URL_TTL_MS || 5 * 60 * 1000);
const REQUIRE_AUTH = process.env.POC_AUTH === '1';
const USER = process.env.POC_USER || 'david';
const PASS = process.env.POC_PASS || 'kwqq';
const VERSION = '1.16.1';

const xml = (s) => String(s ?? '').replace(/[<>&"']/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[c]));

function makeId(source, id) {
  return Buffer.from(JSON.stringify({ s: source, i: id, x: Date.now() + ID_TTL_MS })).toString('base64url');
}
function parseId(raw) {
  try {
    const o = JSON.parse(Buffer.from(String(raw || ''), 'base64url').toString('utf8'));
    if (!o || typeof o.s !== 'string' || typeof o.i !== 'string') return null;
    if (typeof o.x === 'number' && Date.now() > o.x) return null;
    return o;
  } catch {
    return null;
  }
}

function authed(q) {
  if (!REQUIRE_AUTH) return true;
  if (q.get('u') !== USER) return false;
  const token = q.get('t');
  const salt = q.get('s');
  if (token && salt) return crypto.createHash('md5').update(PASS + salt).digest('hex') === token;
  const p = q.get('p') || '';
  if (p.startsWith('enc:')) return Buffer.from(p.slice(4), 'hex').toString('utf8') === PASS;
  return p === PASS;
}

function envelope(fmt, payload) {
  if (fmt === 'json') return { 'subsonic-response': { status: 'ok', version: VERSION, type: 'kwqq', serverVersion: '0.1', ...payload } };
  return `<?xml version="1.0" encoding="UTF-8"?><subsonic-response xmlns="http://subsonic.org/restapi" status="ok" version="${VERSION}" type="kwqq" serverVersion="0.1">${payload.xml || ''}</subsonic-response>`;
}

function send(res, fmt, payload) {
  if (fmt === 'json') {
    const body = JSON.stringify(envelope(fmt, payload));
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(body) });
    return res.end(body);
  }
  const body = envelope(fmt, payload);
  res.writeHead(200, { 'Content-Type': 'text/xml; charset=utf-8' });
  res.end(body);
}
function fail(res, fmt, code, message) {
  if (fmt === 'json') {
    const body = JSON.stringify({ 'subsonic-response': { status: 'failed', version: VERSION, error: { code, message } } });
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    return res.end(body);
  }
  const body = `<?xml version="1.0" encoding="UTF-8"?><subsonic-response xmlns="http://subsonic.org/restapi" status="failed" version="${VERSION}"><error code="${code}" message="${xml(message)}"/></subsonic-response>`;
  res.writeHead(200, { 'Content-Type': 'text/xml; charset=utf-8' });
  res.end(body);
}

async function kwqq(path, timeoutMs = 20000) {
  const r = await fetch(`${KWQQ}${path}`, { signal: AbortSignal.timeout(timeoutMs) });
  return r.json();
}

function coverId(item) {
  return item.cover ? `c_${Buffer.from(item.cover).toString('base64url')}` : '';
}
function songObj(item, base) {
  return {
    id: makeId(item.source, item.id),
    parent: makeId(item.source, 'album'),
    isDir: false,
    title: item.name,
    album: item.album || 'kwqq',
    artist: item.singer || '',
    duration: Number(item.duration_s || 0),
    track: 0,
    year: 0,
    genre: 'Pop',
    coverArt: coverId(item),
    size: Number(item.size_bytes || 0),
    contentType: 'audio/mpeg',
    suffix: item.ext || 'mp3',
    path: `${base}/${item.source}/${item.id}`,
  };
}
function songXml(item, base) {
  const s = songObj(item, base);
  return `<song id="${xml(s.id)}" parent="${xml(s.parent)}" isDir="false" title="${xml(s.title)}" album="${xml(s.album)}" artist="${xml(s.artist)}" duration="${s.duration}" track="0" year="0" genre="${s.genre}" coverArt="${xml(s.coverArt)}" size="${s.size}" contentType="audio/mpeg" suffix="${xml(s.suffix)}" path="${xml(s.path)}"/>`;
}

const urlCache = new Map();
const urlInflight = new Map();
async function resolveUrl(source, id) {
  const key = `${source}:${id}`;
  const hit = urlCache.get(key);
  if (hit && hit.exp > Date.now()) return hit.data;
  if (urlInflight.has(key)) return urlInflight.get(key);
  const task = (async () => {
    console.log(`[resolve] ${source}/${id} (cache miss)`);
    const j = await kwqq(`/${source}/song/url?id=${encodeURIComponent(id)}&quality=320k`);
    if (j.code !== 200 || !j.data || !j.data.url) throw new Error(`no playable url (code ${j.code})`);
    urlCache.set(key, { data: j.data, exp: Date.now() + URL_TTL_MS });
    return j.data;
  })().finally(() => urlInflight.delete(key));
  urlInflight.set(key, task);
  return task;
}

const songMeta = new Map();
let lastMetaKey = '';
function rememberMeta(item) {
  const key = `${item.source}:${item.id}`;
  songMeta.set(key, { artist: item.singer || '', title: item.name || '' });
  return key;
}

function parseLrc(lrc) {
  const lines = [];
  let synced = false;
  for (const raw of String(lrc || '').split(/\r?\n/)) {
    const m = raw.match(/\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\](.*)/);
    if (m) {
      const frac = (m[3] || '0').padEnd(3, '0').slice(0, 3);
      lines.push({ start: (Number(m[1]) * 60 + Number(m[2])) * 1000 + Number(frac), value: m[4].trim() });
      synced = true;
    } else if (raw.trim() && !/^\[[a-zA-Z#]+:.*\]$/.test(raw.trim())) {
      lines.push({ start: -1, value: raw.trim() });
    }
  }
  return { synced, lines };
}

async function fetchLyric(source, id) {
  try {
    const j = await kwqq(`/${source}/lyric?id=${encodeURIComponent(id)}`);
    if (j.code === 200 && j.data && j.data.lyric) return j.data.lyric;
  } catch (e) {
    console.error(`[lyric] ${source}/${id}: ${e.message}`);
  }
  return '';
}

async function handleSearch(query) {
  const count = Math.max(1, Math.min(20, Number(query.get('songCount') || 10)));
  const keywords = query.get('query') || '';
  if (!keywords) return [];
  const results = await Promise.all(SOURCES.map(async (s) => {
    try {
      const j = await kwqq(`/${s}/search?keywords=${encodeURIComponent(keywords)}&limit=${count}`);
      if (j.code !== 200 || !j.data || !Array.isArray(j.data.items)) return [];
      return j.data.items.map((it) => ({ ...it, source: it.source || s }));
    } catch (e) {
      console.error(`[search] ${s} failed: ${e.message}`);
      return [];
    }
  }));
  const items = results.flat();
  items.forEach(rememberMeta);
  return items;
}

async function songById(id) {
  const m = parseId(id);
  if (!m) return null;
  try {
    const j = await kwqq(`/${m.s}/song/info?id=${encodeURIComponent(m.i)}`);
    if (j.code === 200 && j.data) {
      const song = { ...j.data, source: m.s };
      lastMetaKey = rememberMeta(song);
      return song;
    }
  } catch {}
  return null;
}

async function streamAudio(req, res, fmt, query) {
  const m = parseId(query.get('id'));
  if (!m) return fail(res, fmt, 70, 'invalid or expired id');
  lastMetaKey = `${m.s}:${m.i}`;

  let data;
  try {
    data = await resolveUrl(m.s, m.i);
  } catch (e) {
    return fail(res, fmt, 50, e.message);
  }

  const headers = {};
  if (req.headers.range) headers.Range = req.headers.range;
  for (const [k, v] of Object.entries(data.headers || {})) headers[k] = v;

  let up;
  try {
    up = await fetch(data.url, { headers, method: req.method === 'HEAD' ? 'HEAD' : 'GET', redirect: 'follow' });
  } catch (e) {
    return fail(res, fmt, 0, `upstream fetch failed: ${e.message}`);
  }

  const out = {
    'Accept-Ranges': up.headers.get('accept-ranges') || 'bytes',
    'Content-Type': data.ext === 'mp3' ? 'audio/mpeg' : (up.headers.get('content-type') || 'application/octet-stream'),
    'Cache-Control': 'no-store',
  };
  for (const h of ['content-length', 'content-range', 'last-modified', 'etag']) {
    const v = up.headers.get(h);
    if (v) out[h] = v;
  }
  console.log(`[stream] ${m.s}/${m.i} range=${req.headers.range || '-'} -> ${up.status}`);
  res.writeHead(up.status, out);
  if (req.method === 'HEAD' || !up.body) return res.end();
  Readable.fromWeb(up.body).on('error', (e) => { console.error(`[stream] pipe error: ${e.message}`); res.destroy(); }).pipe(res);
}

const EMPTY = {
  getArtists: { xml: '<artists ignoredArticles="The El La Los Las Le Les"/>', json: { artists: { ignoredArticles: 'The El La Los Las Le Les' } } },
  getIndexes: { xml: '<indexes lastModified="0" ignoredArticles="The El La Los Las Le Les"/>', json: { indexes: { lastModified: 0, ignoredArticles: 'The El La Los Las Le Les' } } },
  getAlbumList2: { xml: '<albumList2/>', json: { albumList2: {} } },
  getGenres: { xml: '<genres/>', json: { genres: {} } },
  getPlaylists: { xml: '<playlists/>', json: { playlists: {} } },
  getStarred2: { xml: '<starred2/>', json: { starred2: {} } },
  getRandomSongs: { xml: '<randomSongs/>', json: { randomSongs: {} } },
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const path = url.pathname.replace(/\.view$/, '');
  const q = url.searchParams;
  const fmt = (q.get('f') || 'xml').toLowerCase() === 'json' ? 'json' : 'xml';
  const safe = new URLSearchParams();
  for (const [k, v] of q) if (!['p', 't', 's'].includes(k)) safe.append(k, v);
  console.log(`[req] ${req.method} ${path}?${safe.toString()}`);
  try {
    if (path === '/rest/ping') {
      if (!authed(q)) return fail(res, fmt, 40, 'wrong username or password');
      return fmt === 'json' ? send(res, fmt, {}) : send(res, fmt, { xml: '' });
    }
    if (!authed(q)) return fail(res, fmt, 40, 'wrong username or password');
    if (path === '/rest/getLicense') return send(res, fmt, fmt === 'json' ? { license: { valid: true } } : { xml: '<license valid="true"/>' });
    if (path === '/rest/getMusicFolders') return send(res, fmt, fmt === 'json' ? { musicFolders: { musicFolder: [{ id: 1, name: 'kwqq' }] } } : { xml: '<musicFolders><musicFolder id="1" name="kwqq"/></musicFolders>' });
    const empty = EMPTY[path.slice('/rest/'.length)];
    if (empty) return send(res, fmt, fmt === 'json' ? empty.json : { xml: empty.xml });
    if (path === '/rest/search3' || path === '/rest/search2') {
      const items = await handleSearch(q);
      const base = `kwqq://${q.get('u') || 'user'}`;
      if (fmt === 'json') return send(res, fmt, { searchResult3: { song: items.map((it) => songObj(it, base)) } });
      return send(res, fmt, { xml: `<searchResult3>${items.map((it) => songXml(it, base)).join('')}</searchResult3>` });
    }
    if (path === '/rest/getOpenSubsonicExtensions') {
      if (fmt === 'json') return send(res, fmt, { openSubsonicExtensions: [{ name: 'songLyrics', versions: [1] }] });
      return send(res, fmt, { xml: '<openSubsonicExtensions><openSubsonicExtension name="songLyrics" versions="1"/></openSubsonicExtensions>' });
    }
    if (path === '/rest/getLyricsBySongId') {
      const m = parseId(q.get('id'));
      if (!m) return fail(res, fmt, 70, 'invalid or expired id');
      const meta = songMeta.get(`${m.s}:${m.i}`) || {};
      const { synced, lines } = parseLrc(await fetchLyric(m.s, m.i));
      const timed = lines.filter((l) => l.start >= 0);
      if (fmt === 'json') {
        return send(res, fmt, {
          lyricsList: {
            structuredLyrics: timed.length ? [{
              displayArtist: meta.artist || '', displayTitle: meta.title || '', lang: 'zh',
              synced, offset: 0, line: timed.map((l) => ({ start: l.start, value: l.value })),
            }] : [],
          },
        });
      }
      const inner = timed.length
        ? `<lyricsList><structuredLyrics displayArtist="${xml(meta.artist || '')}" displayTitle="${xml(meta.title || '')}" lang="zh" synced="${synced}" offset="0">${timed.map((l) => `<line start="${l.start}">${xml(l.value)}</line>`).join('')}</structuredLyrics></lyricsList>`
        : '<lyricsList/>';
      return send(res, fmt, { xml: inner });
    }
    if (path === '/rest/getLyrics') {
      let artist = q.get('artist') || '';
      let title = q.get('title') || '';
      // 音流会先带 title/artist 探一次，再发一次空参数的请求来渲染——空参时回退到最近播放的歌曲
      if (!artist && !title) {
        const m = lastMetaKey && songMeta.get(lastMetaKey);
        if (m) { artist = m.artist; title = m.title; }
        console.log(`[lyric] empty params -> fallback ${lastMetaKey || 'none'} (${title}/${artist})`);
      }
      let srcKey = null;
      if (title) {
        for (const [key, meta] of songMeta) {
          if (meta.title === title && (!artist || meta.artist.includes(artist))) { srcKey = key; break; }
        }
      }
      if (!srcKey && title) {
        try {
          const j = await kwqq(`/kuwo/search?keywords=${encodeURIComponent(`${title} ${artist}`)}&limit=1`);
          const it = j.code === 200 && j.data && j.data.items && j.data.items[0];
          if (it) { srcKey = `kuwo:${it.id}`; rememberMeta({ ...it, source: 'kuwo' }); }
        } catch {}
      }
      let lrc = '';
      if (srcKey) {
        const [s, i] = srcKey.split(/:(.+)/);
        const raw = await fetchLyric(s, i);
        // 酷我原始 LRC 头部有 [kuwo:104]/[ver:v1.0]/[ti:..] 等非时间标签，严格解析器可能整篇丢弃 → 只留时间轴行与正文
        if ((process.env.LYRICS_OLD_FORMAT || 'lrc') === 'text') {
          lrc = parseLrc(raw).lines.map((l) => l.value).filter(Boolean).join('\n');
        } else {
          lrc = String(raw || '').split(/\r?\n/)
            .filter((ln) => /^\s*\[\d{1,3}:\d{1,2}([.:]\d{1,3})?\]/.test(ln) || (!/^\s*\[[a-zA-Z]/.test(ln) && ln.trim()))
            .join('\n');
        }
      }
      console.log(`[lyric-resp] ${artist}/${title} src=${srcKey || 'none'} len=${lrc.length}`);
      if (fmt === 'json') return send(res, fmt, { lyrics: { artist, title, value: lrc } });
      return send(res, fmt, { xml: `<lyrics artist="${xml(artist)}" title="${xml(title)}">${xml(lrc)}</lyrics>` });
    }
    if (path === '/rest/getSong') {
      const song = await songById(q.get('id'));
      if (!song) return fail(res, fmt, 70, 'song not found');
      const base = `kwqq://${q.get('u') || 'user'}`;
      return send(res, fmt, fmt === 'json' ? { song: songObj(song, base) } : { xml: songXml(song, base) });
    }
    if (path === '/rest/stream' || path === '/rest/download') return streamAudio(req, res, fmt, q);
    if (path === '/rest/getCoverArt') {
      const raw = String(q.get('id') || '');
      if (!raw.startsWith('c_')) return fail(res, fmt, 70, 'bad cover id');
      let target;
      try { target = Buffer.from(raw.slice(2), 'base64url').toString('utf8'); } catch { return fail(res, fmt, 70, 'bad cover id'); }
      if (!/^https?:\/\//.test(target)) return fail(res, fmt, 70, 'bad cover url');
      const up = await fetch(target, { signal: AbortSignal.timeout(15000) });
      const ct = up.headers.get('content-type') || 'image/jpeg';
      const buf = Buffer.from(await up.arrayBuffer());
      res.writeHead(up.ok ? 200 : 502, { 'Content-Type': ct, 'Content-Length': buf.length });
      return res.end(buf);
    }
    return fail(res, fmt, 0, `unsupported endpoint: ${path}`);
  } catch (e) {
    console.error(`[error] ${path}: ${e.stack || e.message}`);
    if (!res.headersSent) return fail(res, fmt, 0, e.message);
    res.destroy();
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`kwqq subsonic facade on :${PORT} -> ${KWQQ} sources=${SOURCES.join(',')} auth=${REQUIRE_AUTH ? 'on' : 'off'}`);
});
