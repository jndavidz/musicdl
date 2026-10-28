import http from 'node:http';
import dgram from 'node:dgram';

const HOST = '10.10.10.6';
const PORT = 4599;
const LX = '10.10.10.20';
const LXPORT = 9999;
const UUID = 'uuid:6b1d2a44-0000-4000-8000-000000000002';
const LOCATION = `http://${HOST}:${PORT}/desc.xml`;
const CT = 'text/xml; charset="utf-8"';

const DESC = `<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>小爱音箱 (kwqq 代理)</friendlyName>
    <manufacturer>kwqq</manufacturer>
    <modelName>kwqq-dlna-proxy</modelName>
    <modelNumber>1</modelNumber>
    <UDN>${UUID}</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
        <SCPDURL>/avt.xml</SCPDURL>
        <controlURL>/avt</controlURL>
        <eventSubURL>/avt/event</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
        <SCPDURL>/rc.xml</SCPDURL>
        <controlURL>/rc</controlURL>
        <eventSubURL>/rc/event</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
        <SCPDURL>/cm.xml</SCPDURL>
        <controlURL>/cm</controlURL>
        <eventSubURL>/cm/event</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>`;

const SCPD = { '/avt.xml': 'AVTransport1.xml', '/rc.xml': 'RenderingControl1.xml', '/cm.xml': 'ConnectionManager1.xml' };
const CONTROL = { '/avt': '/AVTransport/control', '/rc': '/RenderingControl/control', '/cm': '/ConnectionManager/control' };

let paused = false;
let resuming = false;
let lastUri = '';
let lastPos = '00:00:00';

const AVT = 'urn:schemas-upnp-org:service:AVTransport:1';

function avtBody(action, inner) {
  return `<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:${action} xmlns:u="${AVT}"><InstanceID>0</InstanceID>${inner}</u:${action}></s:Body></s:Envelope>`;
}

function callUpstream(action, inner = '') {
  return new Promise((resolve) => {
    const body = avtBody(action, inner);
    const r = http.request({
      host: LX, port: LXPORT, path: '/AVTransport/control', method: 'POST', timeout: 8000,
      headers: { 'Content-Type': CT, 'Content-Length': Buffer.byteLength(body), SOAPACTION: `"${AVT}#${action}"` },
    }, (ur) => {
      let o = '';
      ur.setEncoding('utf8');
      ur.on('data', (c) => { o += c; });
      ur.on('end', () => resolve({ status: ur.statusCode, body: o }));
    });
    r.on('error', () => resolve({ status: 502, body: '' }));
    r.end(body);
  });
}

const transportState = (b) => (b.match(/<CurrentTransportState>([^<]*)</) || [])[1] || '?';
const relTime = (b) => (b.match(/<RelTime>([^<]*)</) || [])[1] || null;

// LX06 的 Pause 不可信：实测暂停后 GetTransportInfo 仍报 PLAYING，裸 Play 因此被当成 no-op，
// 表现为"首次恢复无声，再暂停一次再恢复才生效"。所以恢复时无条件按暂停位置重投一次。
async function resumeNudge() {
  const before = await callUpstream('GetTransportInfo');
  const st = transportState(before.body);
  let sk = await callUpstream('Seek', `<Unit>REL_TIME</Unit><Target>${lastPos}</Target>`);
  let pl = await callUpstream('Play', '<Speed>1</Speed>');
  console.log(`[nudge] state=${st} seek=${sk.status} play=${pl.status} pos=${lastPos}`);

  const p1 = relTime((await callUpstream('GetPositionInfo')).body);
  await new Promise((r) => setTimeout(r, 1500));
  const p2 = relTime((await callUpstream('GetPositionInfo')).body);
  const stuck = p1 && p2 && p1 === p2;
  if (stuck || sk.status !== 200 || pl.status !== 200) {
    console.log(`[nudge] not progressing (${p1} -> ${p2}) -> re-set URI`);
    if (lastUri) await callUpstream('SetAVTransportURI', `<CurrentURI>${lastUri}</CurrentURI><CurrentURIMetaData></CurrentURIMetaData>`);
    await callUpstream('Seek', `<Unit>REL_TIME</Unit><Target>${lastPos}</Target>`);
    const pl2 = await callUpstream('Play', '<Speed>1</Speed>');
    console.log(`[nudge] retry play=${pl2.status} state=${transportState(pl2.body)}`);
  }
}

function proxySoap(targetPath, body, soapAction, res) {
  const opts = {
    host: LX, port: LXPORT, path: targetPath, method: 'POST',
    headers: {
      'Content-Type': CT,
      'Content-Length': Buffer.byteLength(body),
      ...(soapAction ? { SOAPACTION: soapAction } : {}),
    },
    timeout: 8000,
  };
  const action = (soapAction || '').match(/#(.+)"/)?.[1] || '?';
  if (action === 'SetAVTransportURI') {
    const uri = (body.match(/<CurrentURI>(.*?)<\/CurrentURI>/s) || [])[1] || '';
    lastUri = uri;
    console.log(`[cast] SetAVTransportURI ${uri}`);
  } else if (action === 'Pause') { paused = true; }
  else if (action === 'Play') { resuming = paused; paused = false; }
  if (action === 'Play') console.log(`[play] body=${body.slice(0, 240)}`);

  const up = http.request(opts, (ur) => {
    let out = '';
    ur.setEncoding('utf8');
    ur.on('data', (c) => { out += c; });
    ur.on('end', () => {
      console.log(`[soap] ${action} -> ${ur.statusCode} (${out.length}B)`);
      let payload = out;
      if (action === 'GetPositionInfo') {
        const t = relTime(payload);
        if (t) lastPos = t;
      }
      if (action === 'GetTransportInfo' && paused && /STOPPED/.test(payload)) {
        payload = payload.replace(/<CurrentTransportState>STOPPED<\/CurrentTransportState>/g, '<CurrentTransportState>PAUSED_PLAYBACK</CurrentTransportState>');
      }
      if (action === 'GetProtocolInfo' && !/<Sink>[^<]*audio\/mpeg/.test(payload)) {
        payload = payload.replace(/<Sink>[^<]*<\/Sink>|<Sink\/>/, '<Sink>http-get:*:audio/mpeg:*,http-get:*:audio/aac:*,http-get:*:audio/mp4:*</Sink>');
      }
      res.writeHead(ur.statusCode || 200, { 'Content-Type': CT, 'Content-Length': Buffer.byteLength(payload) });
      res.end(payload);
      if (action === 'Play' && resuming) {
        resuming = false;
        setTimeout(() => { resumeNudge().catch((e) => console.log('[nudge] ' + e.message)); }, 700);
      }
    });
  });
  up.on('error', (e) => {
    console.log(`[soap] ${action} error ${e.message}`);
    res.writeHead(502, { 'Content-Type': CT });
    res.end();
  });
  up.end(body);
}

const httpServer = http.createServer((req, res) => {
  const u = new URL(req.url, `http://${HOST}:${PORT}`);
  const peer = (req.socket.remoteAddress || '').replace(/^::ffff:/, '');
  if (req.method === 'GET' && u.pathname === '/desc.xml') {
    res.writeHead(200, { 'Content-Type': CT, 'Content-Length': Buffer.byteLength(DESC) });
    return res.end(DESC);
  }
  if (req.method === 'GET' && SCPD[u.pathname]) {
    const up = http.get({ host: LX, port: LXPORT, path: `/${SCPD[u.pathname]}`, timeout: 8000 }, (ur) => {
      res.writeHead(ur.statusCode || 200, { 'Content-Type': CT });
      ur.pipe(res);
    });
    up.on('error', () => { res.writeHead(502); res.end(); });
    return;
  }
  if (req.method === 'SUBSCRIBE' || req.method === 'UNSUBSCRIBE') {
    console.log(`[event] ${req.method} ${u.pathname} from ${peer}`);
    res.writeHead(200, { SID: 'uuid:00000000-0000-4000-8000-000000000002', TIMEOUT: 'Second-1800' });
    return res.end();
  }
  if (req.method === 'POST' && CONTROL[u.pathname]) {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (c) => { body += c; });
    req.on('end', () => proxySoap(CONTROL[u.pathname], body, req.headers.soapaction, res));
    return;
  }
  console.log(`[http] ${req.method} ${u.pathname} from ${peer}`);
  res.writeHead(404); res.end();
});

const udp = dgram.createSocket({ type: 'udp4', reuseAddr: true });
function announce(method, nt, usn) {
  const msg = method === 'NOTIFY'
    ? `NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nCACHE-CONTROL: max-age=1800\r\nLOCATION: ${LOCATION}\r\nNT: ${nt}\r\nNTS: ssdp:alive\r\nSERVER: Node/1.0 UPnP/1.0 kwqq-proxy/1.0\r\nUSN: ${usn}\r\n\r\n`
    : '';
  if (msg) udp.send(Buffer.from(msg), 1900, '239.255.255.250');
}
udp.on('error', (e) => console.log('[udp] ' + e.message));
udp.bind(1900, () => {
  try { udp.addMembership('239.255.255.250', HOST); } catch (e) { console.log('[udp] membership ' + e.message); }
  console.log('[udp] listening');
  announce('NOTIFY', 'upnp:rootdevice', `${UUID}::upnp:rootdevice`);
  setInterval(() => announce('NOTIFY', 'upnp:rootdevice', `${UUID}::upnp:rootdevice`), 300000);
});
udp.on('message', (buf, rinfo) => {
  const t = buf.toString('utf8');
  if (!/^M-SEARCH/i.test(t)) return;
  const st = (t.match(/^ST:\s*(.+)$/im) || [])[1]?.trim() || '';
  if (!/ssdp:all|MediaRenderer|upnp:rootdevice/i.test(st)) return;
  const realSt = st === 'ssdp:all' ? 'urn:schemas-upnp-org:device:MediaRenderer:1' : st;
  const usn = `${UUID}::${realSt}`;
  const resp = `HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nEXT:\r\nLOCATION: ${LOCATION}\r\nSERVER: Node/1.0 UPnP/1.0 kwqq-proxy/1.0\r\nST: ${realSt}\r\nUSN: ${usn}\r\n\r\n`;
  udp.send(Buffer.from(resp), rinfo.port, rinfo.address);
  console.log(`[ssdp] reply to ${rinfo.address}:${rinfo.port} ST=${st}`);
});

httpServer.listen(PORT, '0.0.0.0', () => console.log(`[http] proxy ${LOCATION} -> ${LX}:${LXPORT}`));
