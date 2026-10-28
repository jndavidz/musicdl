import dgram from 'node:dgram';
const iface = process.argv[2] || '10.10.10.6';
const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });
const msg = Buffer.from('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n');
const seen = new Set();
sock.on('message', (b, r) => { const t = b.toString(); const loc = (t.match(/^LOCATION:\s*(.+)$/im)||[])[1]||''; const k = r.address+'|'+loc.trim(); if(!seen.has(k)){seen.add(k);console.log(r.address, loc.trim());} });
sock.bind(0, iface, () => { try { sock.setMulticastInterface(iface); } catch(e){ console.log('setMulticastInterface failed', e.message); } console.log('iface='+iface); sock.send(msg, 1900, '239.255.255.250'); setTimeout(()=>sock.send(msg,1900,'239.255.255.250'),700); setTimeout(()=>{console.log('total='+seen.size);sock.close();},5000); });
