import dgram from 'node:dgram';

const mode = process.argv[2] || 'multi';
const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });
const seen = new Map();
const mk = (st) => Buffer.from(
  'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: ' + st + '\r\n\r\n'
);

sock.on('message', (buf, rinfo) => {
  const t = buf.toString('utf8');
  const st = (t.match(/^ST:\s*(.+)$/im) || [])[1] || '?';
  const loc = (t.match(/^LOCATION:\s*(.+)$/im) || [])[1] || '';
  const key = `${rinfo.address}|${st}|${loc.trim()}`;
  if (!seen.has(key)) {
    seen.set(key, 1);
    console.log(`${rinfo.address}:${rinfo.port} ST=${st.trim()} ${loc.trim()}`);
  }
});
sock.bind(() => {
  const send = () => {
    if (mode === 'uni') {
      sock.send(mk('ssdp:all'), 1900, '10.10.10.20');
    } else {
      sock.send(mk('ssdp:all'), 1900, '239.255.255.250');
    }
  };
  send();
  setTimeout(send, 700);
  setTimeout(() => { console.log(`mode=${mode} total=${seen.size}`); sock.close(); }, 5000);
});
