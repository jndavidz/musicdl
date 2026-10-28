import http from 'node:http';
import dgram from 'node:dgram';

const HOST = '10.10.10.6';
const PORT = 4599;
const UUID = 'uuid:6b1d2a44-0000-4000-8000-000000000001';
const LOCATION = `http://${HOST}:${PORT}/desc.xml`;

const DESC = `<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>kwqq DLNA Test</friendlyName>
    <manufacturer>kwqq</manufacturer>
    <modelName>kwqq-renderer</modelName>
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

const env = (action, service, inner = '') =>
  `<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:${action}Response xmlns:u="urn:schemas-upnp-org:service:${service}:1">${inner}</u:${action}Response></s:Body></s:Envelope>`;

const httpServer = http.createServer((req, res) => {
  const u = new URL(req.url, `http://${HOST}:${PORT}`);
  console.log(`[http] ${req.method} ${u.pathname} from ${req.socket.remoteAddress}`);
  if (req.method === 'GET' && (u.pathname === '/desc.xml' || u.pathname.endsWith('.xml'))) {
    res.writeHead(200, { 'Content-Type': 'text/xml; charset="utf-8"', 'Content-Length': Buffer.byteLength(DESC) });
    return res.end(DESC);
  }
  if (req.method === 'SUBSCRIBE' || req.method === 'UNSUBSCRIBE') {
    res.writeHead(200, { SID: 'uuid:00000000-0000-4000-8000-000000000001', TIMEOUT: 'Second-1800' });
    return res.end();
  }
  if (req.method === 'POST') {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      const action = ((req.headers.soapaction || '').match(/#(.+)"/) || [])[1] || 'Unknown';
      let inner = '';
      if (action === 'GetTransportInfo') inner = '<CurrentTransportState>STOPPED</CurrentTransportState><CurrentTransportStatus>OK</CurrentTransportStatus><CurrentSpeed>1</CurrentSpeed>';
      else if (action === 'GetPositionInfo') inner = '<Track>0</Track><TrackDuration>00:00:00</TrackDuration><TrackURI></TrackURI><RelTime>00:00:00</RelTime><AbsTime>00:00:00</AbsTime><RelCount>0</RelCount><AbsCount>0</AbsCount>';
      else if (action === 'GetMediaInfo') inner = '<NrTracks>0</NrTracks><MediaDuration>00:00:00</MediaDuration><CurrentURI></CurrentURI><CurrentURIMetaData></CurrentURIMetaData><NextURI></NextURI><NextURIMetaData></NextURIMetaData><PlayMedium>NONE</PlayMedium><RecordMedium>NOT_IMPLEMENTED</RecordMedium><WriteStatus>NOT_IMPLEMENTED</WriteStatus>';
      else if (action === 'GetVolume') inner = '<CurrentVolume>9</CurrentVolume>';
      else if (action === 'GetMute') inner = '<CurrentMute>0</CurrentMute>';
      else if (action === 'GetProtocolInfo') inner = '<Source></Source><Sink>http-get:*:audio/mpeg:*,http-get:*:audio/mp4:*,http-get:*:audio/aac:*,http-get:*:audio/flac:intel.com-flac</Sink>';
      else if (action === 'GetCurrentTransportActions') inner = '<Actions>Play,Pause,Stop,Seek</Actions>';
      else if (action === 'GetTransportSettings') inner = '<PlayMode>NORMAL</PlayMode><RecQualityMode>NOT_IMPLEMENTED</RecQualityMode>';
      const service = req.headers.soapaction?.includes('RenderingControl') ? 'RenderingControl' : req.headers.soapaction?.includes('ConnectionManager') ? 'ConnectionManager' : 'AVTransport';
      res.writeHead(200, { 'Content-Type': 'text/xml; charset="utf-8"' });
      res.end(env(action, service, inner));
    });
    return;
  }
  res.writeHead(404); res.end();
});

const udp = dgram.createSocket({ type: 'udp4', reuseAddr: true });
udp.on('error', (e) => console.log('[udp] ' + e.message));
udp.bind(1900, () => {
  try { udp.addMembership('239.255.255.250', HOST); } catch (e) { console.log('[udp] membership ' + e.message); }
  console.log('[udp] listening');
});
udp.on('message', (buf, rinfo) => {
  const t = buf.toString('utf8');
  if (!/^M-SEARCH/i.test(t)) return;
  const st = (t.match(/^ST:\s*(.+)$/im) || [])[1]?.trim() || '';
  if (!/ssdp:all|MediaRenderer|upnp:rootdevice/i.test(st)) return;
  const usn = st === 'upnp:rootdevice' ? `${UUID}::upnp:rootdevice` : st === 'ssdp:all' ? `${UUID}::urn:schemas-upnp-org:device:MediaRenderer:1` : `${UUID}::${st}`;
  const resp = `HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nEXT:\r\nLOCATION: ${LOCATION}\r\nSERVER: Node/1.0 UPnP/1.0 kwqq-renderer/1.0\r\nST: ${st === 'ssdp:all' ? 'urn:schemas-upnp-org:device:MediaRenderer:1' : st}\r\nUSN: ${usn}\r\n\r\n`;
  udp.send(Buffer.from(resp), rinfo.port, rinfo.address);
  console.log(`[ssdp] reply to ${rinfo.address}:${rinfo.port} ST=${st}`);
});

httpServer.listen(PORT, '0.0.0.0', () => console.log(`[http] listening ${LOCATION}`));
