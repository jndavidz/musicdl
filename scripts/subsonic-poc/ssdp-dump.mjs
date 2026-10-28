import dgram from 'node:dgram';
const s = dgram.createSocket('udp4');
const msg = Buffer.from('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n');
s.on('message', (b, r) => { if (r.address === '10.10.10.20') { console.log('--- from ' + r.address + ':' + r.port); console.log(JSON.stringify(b.toString())); s.close(); } });
s.bind(0, '10.10.10.6', () => { s.send(msg, 1900, '10.10.10.20'); setTimeout(() => { s.close(); }, 4000); });
