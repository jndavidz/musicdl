import dgram from 'node:dgram';
const seconds = Number(process.argv[2] || 45);
const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });
sock.on('error', (e) => { console.log('ERR ' + e.message); process.exit(1); });
sock.bind(1900, () => {
  try { sock.addMembership('239.255.255.250', '10.10.10.6'); } catch (e) { console.log('membership fail: ' + e.message); }
  console.log('listening 1900 for ' + seconds + 's');
});
sock.on('message', (b, r) => {
  const t = b.toString('utf8');
  if (/^M-SEARCH/i.test(t)) {
    const st = (t.match(/^ST:\s*(.+)$/im) || [])[1] || '?';
    console.log(`[M-SEARCH] from ${r.address}:${r.port} ST=${st.trim()}`);
  }
});
setTimeout(() => { console.log('done'); sock.close(); }, seconds * 1000);
