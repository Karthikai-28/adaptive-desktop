// Who is on the TV's home network, found from the TV itself.
//
// One look takes about five seconds:
//   1. a UDP datagram to every address on the TV's subnet, so the kernel
//      asks each one for its hardware address (ARP)
//   2. meanwhile, names: the router's DNS (DHCP host names), mDNS (what
//      phones, laptops, Chromecasts and printers call themselves) and SSDP
//      (TVs, speakers and routers describe themselves over UPnP)
//   3. /proc/net/arp then lists everything that answered
// Plain Node 12 (the TV's service runtime): no npm modules, no ?. or ??.

'use strict';

const dgram = require('dgram');
const dns = require('dns');
const fs = require('fs');
const http = require('http');
const os = require('os');

const LOOK_MS = 4500;
const NAME_WAIT_MS = 1800;
const MAX_HOSTS = 254;
const MDNS = { address: '224.0.0.251', port: 5353 };
const SSDP = { address: '239.255.255.250', port: 1900 };
const MDNS_SERVICES = [
    '_services._dns-sd._udp.local', '_googlecast._tcp.local', '_airplay._tcp.local', '_raop._tcp.local',
    '_companion-link._tcp.local', '_device-info._tcp.local', '_ipp._tcp.local', '_printer._tcp.local',
    '_spotify-connect._tcp.local', '_hap._tcp.local', '_smb._tcp.local', '_workstation._tcp.local',
    '_androidtvremote2._tcp.local', '_amzn-wplay._tcp.local', '_sleep-proxy._udp.local',
];
const SERVICE_NAMES = {
    _googlecast: 'Chromecast', _airplay: 'AirPlay', _raop: 'AirPlay audio', _ipp: 'Printer',
    _printer: 'Printer', '_spotify-connect': 'Spotify Connect', _hap: 'HomeKit', _smb: 'File sharing',
    _workstation: 'Computer', _androidtvremote2: 'Android TV', '_amzn-wplay': 'Fire TV',
    '_companion-link': 'Apple device', '_sleep-proxy': 'Apple sleep proxy',
};

// --- reading the TV's tables (pure) -------------------------------------------

// Little-endian hex from /proc/net/route -> dotted address.
function hexToIp(hex) {
    const n = parseInt(hex, 16);
    return [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255].join('.');
}

// The interface and gateway of the default route.
function parseRoute(text) {
    const lines = String(text || '').trim().split('\n').slice(1);
    for (let i = 0; i < lines.length; i++) {
        const cols = lines[i].trim().split(/\s+/);
        if (cols[1] === '00000000' && cols[2] !== '00000000') {
            return { iface: cols[0], gateway: hexToIp(cols[2]) };
        }
    }
    return null;
}

// Complete entries ("0x2") on one interface: [{ip, mac}].
function parseArp(text, iface) {
    return String(text || '').trim().split('\n').slice(1).map((line) => line.trim().split(/\s+/))
        .filter((cols) => cols.length >= 6 && cols[2] === '0x2' && cols[3] !== '00:00:00:00:00:00'
            && (!iface || cols[5] === iface))
        .map((cols) => ({ ip: cols[0], mac: cols[3].toLowerCase() }));
}

function ipToInt(ip) {
    return ip.split('.').reduce((n, part) => n * 256 + Number(part), 0);
}

function intToIp(n) {
    return [Math.floor(n / 16777216) % 256, Math.floor(n / 65536) % 256, Math.floor(n / 256) % 256, n % 256].join('.');
}

// Every other address on the subnet; a subnet wider than /24 is looked at as
// the /24 around the TV, which is where a home router hands out addresses.
function hostsOf(ip, netmask) {
    let mask = ipToInt(netmask || '255.255.255.0');
    if (mask < ipToInt('255.255.255.0')) mask = ipToInt('255.255.255.0');
    const base = ipToInt(ip) - (ipToInt(ip) % (4294967296 - mask));
    const size = 4294967296 - mask;
    const out = [];
    for (let n = base + 1; n < base + size - 1 && out.length < MAX_HOSTS; n++) {
        if (intToIp(n) !== ip) out.push(intToIp(n));
    }
    return out;
}

// Phones and laptops make up an address per network ("private address").
function isPrivateMac(mac) {
    return /^[0-9a-f]([26ae])/i.test(mac || '');
}

let vendorIndex = null;
function vendorOf(mac) {
    if (!vendorIndex) {
        vendorIndex = {};
        const groups = require('./vendors.json');
        Object.keys(groups).forEach((brand) => groups[brand].forEach((prefix) => { vendorIndex[prefix] = brand; }));
    }
    return vendorIndex[String(mac || '').replace(/:/g, '').slice(0, 6).toUpperCase()] || null;
}

// --- DNS messages, for mDNS (pure) ----------------------------------------------

function encodeQuery(id, names, type) {
    const parts = [Buffer.from([id >> 8, id & 255, 0, 0, 0, names.length, 0, 0, 0, 0, 0, 0])];
    names.forEach((name) => {
        name.split('.').filter(Boolean).forEach((label) => {
            const bytes = Buffer.from(label, 'utf8');
            parts.push(Buffer.from([bytes.length]), bytes);
        });
        // QU: ask for a unicast answer, to the port this came from.
        parts.push(Buffer.from([0, 0, type >> 8, type & 255, 0x80, 0x01]));
    });
    return Buffer.concat(parts);
}

function readName(buf, offset) {
    const labels = [];
    let at = offset;
    let end = -1;
    for (let jumps = 0; jumps < 20 && at < buf.length; jumps++) {
        const length = buf[at];
        if (length === 0) {
            if (end < 0) end = at + 1;
            return { name: labels.join('.'), end: end };
        }
        if ((length & 0xc0) === 0xc0) {
            if (end < 0) end = at + 2;
            at = ((length & 0x3f) << 8) | buf[at + 1];
            continue;
        }
        labels.push(buf.toString('utf8', at + 1, at + 1 + length));
        at += 1 + length;
    }
    throw new Error('Bad name');
}

// Every record in a reply: [{name, type, data}]; PTR/SRV data is a name, A an address.
function decodeMessage(buf) {
    const questions = buf.readUInt16BE(4);
    const records = buf.readUInt16BE(6) + buf.readUInt16BE(8) + buf.readUInt16BE(10);
    let at = 12;
    for (let i = 0; i < questions; i++) at = readName(buf, at).end + 4;
    const out = [];
    for (let i = 0; i < records && at < buf.length; i++) {
        const head = readName(buf, at);
        const type = buf.readUInt16BE(head.end);
        const length = buf.readUInt16BE(head.end + 8);
        const start = head.end + 10;
        let data = null;
        if (type === 12 || type === 5) data = readName(buf, start).name;
        else if (type === 33) data = readName(buf, start + 6).name;
        else if (type === 1 && length === 4) data = Array.prototype.join.call(buf.slice(start, start + 4), '.');
        out.push({ name: head.name, type: type, data: data });
        at = start + length;
    }
    return out;
}

// "Kai's iPhone._companion-link._tcp.local" -> {instance, service}
function splitInstance(name) {
    const match = /^(.*?)\.(_[^.]+)\._(?:tcp|udp)\.local$/i.exec(name || '');
    return match ? { instance: match[1].replace(/\\032/g, ' '), service: match[2].toLowerCase() } : null;
}

// --- what a device is (pure) ------------------------------------------------------

const KINDS = [
    ['console', /playstation|\bps[45]\b|xbox|nintendo|switch|steam ?deck|valve/],
    ['camera', /camera|\bipc\b|\bcam\b|hikvision|ezviz|dahua|imou|cp plus|arlo|ring\b/],
    ['printer', /printer|laserjet|deskjet|officejet|epson|canon|brother|_ipp|_printer/],
    ['speaker', /echo|alexa|sonos|speaker|homepod|nest (mini|audio)|bose|jbl|harman|spotify connect|airplay audio/],
    ['tv', /\btv\b|webos|tizen|bravia|android ?tv|roku|fire ?tv|\baft|chromecast|mediarenderer|set-top|sdmc|vu\b|tcl|hisense/],
    ['tablet', /ipad|\btab\b|tablet/],
    ['phone', /iphone|android|galaxy|pixel|redmi|oneplus|phone|\bmi[- ]?\d|vivo|oppo|realme|poco|nord|nothing/],
    ['computer', /macbook|laptop|thinkpad|desktop|imac|mac ?mini|windows|workstation|ubuntu|linux|\bpc\b|file sharing|computer|intel|rivet|azurewave|liteon|dell|lenovo|asus|raspberry/],
    ['smart-home', /espressif|tuya|homekit|smart home|wipro|syska|philips hue|\bplug\b|bulb|esp[_-]|shelly|sonoff/],
];

function classify(device) {
    if (device.gateway) return 'router';
    if (device.self) return 'tv';
    const text = [device.name, device.hostname, device.model, device.vendor, device.deviceType]
        .concat(device.services || []).join(' ').toLowerCase();
    for (let i = 0; i < KINDS.length; i++) {
        if (KINDS[i][1].test(text)) return KINDS[i][0];
    }
    return device.privateMac ? 'personal' : 'unknown';
}

// "galaxy-s23.lan" -> "galaxy-s23"; router placeholders are no name.
function cleanHost(name) {
    const host = String(name || '').replace(/\.$/, '').replace(/\.(lan|local|home|localdomain|domain|router)$/i, '');
    if (!host || /^\d+\.\d+\.\d+\.\d+$/.test(host) || /^(localhost|unknown|\*)$/i.test(host)) return null;
    return host;
}

function bestName(device) {
    return device.friendlyName || device.instance || cleanHost(device.mdnsHost) || cleanHost(device.hostname) || null;
}

// --- looking ----------------------------------------------------------------------

function readText(path) {
    try {
        return fs.readFileSync(path, 'utf8');
    } catch (error) {
        return '';
    }
}

function ownAddress(iface) {
    const list = (os.networkInterfaces() || {})[iface] || [];
    for (let i = 0; i < list.length; i++) {
        if (list[i].family === 'IPv4' && !list[i].internal) return list[i];
    }
    return null;
}

function withTimeout(promise, ms) {
    return Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(null), ms))]);
}

function fetchText(url, ms) {
    return new Promise((resolve) => {
        const request = http.get(url, { timeout: ms }, (reply) => {
            let text = '';
            reply.setEncoding('utf8');
            reply.on('data', (part) => {
                text += part;
                if (text.length > 65536) request.destroy();
            });
            reply.on('end', () => resolve(text));
        });
        request.on('timeout', () => request.destroy());
        request.on('error', () => resolve(''));
    });
}

function xmlTag(xml, tag) {
    const match = new RegExp('<' + tag + '>([^<]*)</' + tag + '>', 'i').exec(xml || '');
    return match ? match[1].trim().replace(/&amp;/g, '&') : null;
}

// mDNS and SSDP answers, by address.
function listen(found, finished) {
    const socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    const locations = {};
    let over = false;
    const done = () => {
        if (!over) {
            over = true;
            finished(locations);
        }
    };
    socket.on('error', done);
    socket.on('message', (message, from) => {
        const entry = found[from.address] || (found[from.address] = { services: [] });
        if (from.port === SSDP.port || /^HTTP\/1\.1 200/.test(message.toString('utf8', 0, 12))) {
            const text = message.toString('utf8');
            const location = /^location:\s*(\S+)/im.exec(text);
            const server = /^server:\s*(.+)$/im.exec(text);
            if (location) locations[from.address] = location[1];
            if (server) entry.server = server[1].trim();
            return;
        }
        let records;
        try {
            records = decodeMessage(message);
        } catch (error) {
            return;
        }
        records.forEach((record) => {
            const named = splitInstance(record.type === 12 ? record.data : record.name);
            if (named) {
                const label = SERVICE_NAMES[named.service];
                if (label && entry.services.indexOf(label) < 0) entry.services.push(label);
                if (!entry.instance && named.service !== '_sleep-proxy' && named.service !== '_device-info') {
                    entry.instance = named.instance;
                }
                if (named.service === '_device-info' && !entry.model) entry.model = named.instance;
            }
            if (record.type === 12 && /in-addr\.arpa$/i.test(record.name)) entry.mdnsHost = record.data;
            if (record.type === 1 && /\.local$/i.test(record.name) && !entry.mdnsHost) entry.mdnsHost = record.name;
        });
    });
    socket.bind(0, () => {
        try {
            socket.setMulticastTTL(1);
        } catch (error) { /* the default works on one subnet */ }
        socket.send(encodeQuery(1, MDNS_SERVICES, 12), MDNS.port, MDNS.address);
        const search = 'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n' +
            'MX: 2\r\nST: ssdp:all\r\n\r\n';
        socket.send(search, SSDP.port, SSDP.address);
        setTimeout(() => socket.send(search, SSDP.port, SSDP.address), 800);
    });
    return {
        // Reverse lookups over mDNS, once the live addresses are known.
        ask: (ips) => {
            for (let i = 0; i < ips.length; i += 8) {
                const names = ips.slice(i, i + 8).map((ip) => ip.split('.').reverse().join('.') + '.in-addr.arpa');
                try {
                    socket.send(encodeQuery(2 + i, names, 12), MDNS.port, MDNS.address);
                } catch (error) { /* closed */ }
            }
        },
        close: () => {
            try {
                socket.close();
            } catch (error) { /* already */ }
            done();
        },
    };
}

// Make the kernel resolve every address: a datagram to the discard port.
function knock(hosts) {
    const socket = dgram.createSocket('udp4');
    socket.on('error', () => {});
    const payload = Buffer.from([0]);
    const send = () => hosts.forEach((ip) => socket.send(payload, 9, ip, () => {}));
    send();
    setTimeout(send, 900);
    setTimeout(() => socket.close(), 2000);
}

function reverseNames(ips, server) {
    const resolver = new dns.Resolver();
    try {
        resolver.setServers([server]);
    } catch (error) {
        return Promise.resolve({});
    }
    const names = {};
    const lookups = ips.map((ip) => new Promise((resolve) => {
        resolver.reverse(ip, (error, hosts) => {
            if (!error && hosts && hosts.length) names[ip] = hosts[0];
            resolve();
        });
    }));
    return withTimeout(Promise.all(lookups), NAME_WAIT_MS).then(() => {
        resolver.cancel();
        return names;
    });
}

function describe(locations, found) {
    const ips = Object.keys(locations).slice(0, 24);
    return Promise.all(ips.map((ip) => fetchText(locations[ip], 1500).then((xml) => {
        const entry = found[ip];
        const friendly = xmlTag(xml, 'friendlyName');
        if (friendly && !/^(unknown|linux|router)$/i.test(friendly)) entry.friendlyName = friendly;
        entry.model = entry.model || [xmlTag(xml, 'manufacturer'), xmlTag(xml, 'modelName')].filter(Boolean).join(' ') || null;
        entry.deviceType = xmlTag(xml, 'deviceType');
    })));
}

let looking = null;

function look() {
    if (looking) return looking;
    looking = new Promise((resolve, reject) => {
        const route = parseRoute(readText('/proc/net/route'));
        const own = route && ownAddress(route.iface);
        if (!route || !own) {
            reject(new Error('The TV is not on a network'));
            return;
        }
        const hosts = hostsOf(own.address, own.netmask);
        const found = {};
        let arp = [];
        let dnsNames = {};
        const described = new Promise((done) => {
            const names = listen(found, (locations) => describe(locations, found).then(done, done));
            knock(hosts);
            // Most devices answer ARP within a second or two; the rest of
            // the time goes to asking the live ones their names.
            setTimeout(() => {
                arp = parseArp(readText('/proc/net/arp'), route.iface);
                const live = arp.map((entry) => entry.ip).concat([own.address]);
                names.ask(live);
                reverseNames(live, route.gateway).then((result) => { dnsNames = result; });
            }, LOOK_MS - NAME_WAIT_MS);
            setTimeout(() => names.close(), LOOK_MS + 100);
        });
        described.then(finish);

        function finish() {
            const byIp = {};
            arp.forEach((entry) => { byIp[entry.ip] = { ip: entry.ip, mac: entry.mac }; });
            byIp[own.address] = { ip: own.address, mac: (own.mac || '').toLowerCase(), self: true };
            Object.keys(found).forEach((ip) => {
                if (ip.indexOf('.') > 0 && hosts.concat([own.address]).indexOf(ip) >= 0 && !byIp[ip]) byIp[ip] = { ip: ip, mac: null };
            });
            const devices = Object.keys(byIp).map((ip) => {
                const extra = found[ip] || {};
                const device = Object.assign({}, byIp[ip], {
                    gateway: ip === route.gateway, hostname: dnsNames[ip] || null, mdnsHost: extra.mdnsHost || null,
                    instance: extra.instance || null, friendlyName: extra.friendlyName || null,
                    model: extra.model || null, deviceType: extra.deviceType || null, server: extra.server || null,
                    services: extra.services || [],
                });
                device.vendor = device.mac ? vendorOf(device.mac) : null;
                device.privateMac = isPrivateMac(device.mac);
                device.name = bestName(device);
                device.kind = classify(device);
                return device;
            }).sort((a, b) => ipToInt(a.ip) - ipToInt(b.ip));
            looking = null;
            resolve({ subnet: own.address + '/' + own.netmask, self: own.address, gateway: route.gateway,
                iface: route.iface, devices: devices, at: Date.now() });
        }
    });
    looking.catch(() => { looking = null; });
    return looking;
}

module.exports = {
    look: look, parseRoute: parseRoute, parseArp: parseArp, hostsOf: hostsOf, hexToIp: hexToIp,
    isPrivateMac: isPrivateMac, vendorOf: vendorOf, encodeQuery: encodeQuery, decodeMessage: decodeMessage,
    splitInstance: splitInstance, classify: classify, cleanHost: cleanHost, bestName: bestName,
};
