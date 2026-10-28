import dgram from 'node:dgram';

const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });
const msg = Buffer.from(
  'M-SEARCH * HTTP/1.1\r\n' +
  'HOST: 239.255.255.250:1900\r\n' +
  'MAN: "ssdp:discover"\r\n' +
  'MX: 3\r\n' +
  'ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n' +
  '\r\n'
);

const seen = new Set();
sock.on('message', (buf, rinfo) => {
  const text = buf.toString('utf8');
  const loc = (text.match(/LOCATION:\s*(.+)/i) || [])[1] || '';
  const key = `${rinfo.address} ${loc.trim()}`;
  if (!seen.has(key)) {
    seen.add(key);
    console.log(`[response] from ${rinfo.address}:${rinfo.port} ${loc.trim()}`);
  }
});
sock.bind(() => {
  console.log('M-SEARCH sent');
  sock.send(msg, 1900, '239.255.255.250');
  setTimeout(() => sock.send(msg, 1900, '239.255.255.250'), 800);
  setTimeout(() => {
    console.log(`total responders: ${seen.size}`);
    sock.close();
  }, 6000);
});
