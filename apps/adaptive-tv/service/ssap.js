// The TV's own control socket (SSAP), from inside the TV.
//
// webOS answers SSAP only on wss://...:3001 with a self-signed certificate,
// which the app's web page cannot accept, so this service holds the socket.
// It is plain Node with no npm modules: the TV's service runtime has none.
// The first registration shows "Allow?" on the TV; the client key it gives
// is kept by the page and handed back on every call.

'use strict';

const crypto = require('crypto');
const https = require('https');
const tls = require('tls');

const PERMISSIONS = [
    'LAUNCH', 'LAUNCH_WEBAPP', 'APP_TO_APP', 'CLOSE', 'CONTROL_AUDIO', 'CONTROL_DISPLAY',
    'CONTROL_INPUT_TV', 'CONTROL_POWER', 'READ_APP_STATUS', 'READ_INPUT_DEVICE_LIST',
    'READ_RUNNING_APPS', 'READ_INSTALLED_APPS', 'READ_POWER_STATE', 'WRITE_NOTIFICATION_TOAST',
];
const PAIR_WAIT_MS = 60000;
const CALL_WAIT_MS = 8000;

// --- WebSocket frames (RFC 6455) --------------------------------------------

// A client frame: always masked.
function encodeFrame(text, opcode) {
    const payload = Buffer.from(text, 'utf8');
    const length = payload.length;
    let header;
    if (length < 126) {
        header = Buffer.from([0x80 | (opcode || 1), 0x80 | length]);
    } else if (length < 65536) {
        header = Buffer.alloc(4);
        header[1] = 0x80 | 126;
        header.writeUInt16BE(length, 2);
    } else {
        header = Buffer.alloc(10);
        header[1] = 0x80 | 127;
        header.writeUInt32BE(Math.floor(length / 4294967296), 2);
        header.writeUInt32BE(length >>> 0, 6);
    }
    header[0] = 0x80 | (opcode || 1);
    const mask = crypto.randomBytes(4);
    const body = Buffer.alloc(length);
    for (let i = 0; i < length; i++) body[i] = payload[i] ^ mask[i % 4];
    return Buffer.concat([header, mask, body]);
}

// Whole frames at the start of buf, and what is left for the next read.
function decodeFrames(buf) {
    const frames = [];
    let at = 0;
    while (buf.length - at >= 2) {
        const fin = (buf[at] & 0x80) !== 0;
        const opcode = buf[at] & 0x0f;
        const masked = (buf[at + 1] & 0x80) !== 0;
        let length = buf[at + 1] & 0x7f;
        let head = 2;
        if (length === 126) {
            if (buf.length - at < 4) break;
            length = buf.readUInt16BE(at + 2);
            head = 4;
        } else if (length === 127) {
            if (buf.length - at < 10) break;
            length = buf.readUInt32BE(at + 2) * 4294967296 + buf.readUInt32BE(at + 6);
            head = 10;
        }
        const start = at + head + (masked ? 4 : 0);
        if (buf.length < start + length) break;
        let payload = Buffer.from(buf.slice(start, start + length));
        if (masked) {
            const mask = buf.slice(at + head, at + head + 4);
            for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
        }
        frames.push({ fin: fin, opcode: opcode, payload: payload });
        at = start + length;
    }
    return { frames: frames, rest: buf.slice(at) };
}

// --- the connection ---------------------------------------------------------

class Tv {
    constructor(host, port) {
        this.host = host || '127.0.0.1';
        this.port = port || 3001;
        this.socket = null;
        this.ready = false;
        this.key = null;
        this.nextId = 0;
        this.waiting = {};
        this.buffer = Buffer.alloc(0);
        this.upgraded = false;
        this.partial = null;
    }

    // Resolves with the client key once the TV has registered this app.
    open(key) {
        return new Promise((resolve, reject) => {
            const fail = (error) => {
                this.close();
                reject(error);
            };
            const wsKey = crypto.randomBytes(16).toString('base64');
            this.socket = tls.connect({ host: this.host, port: this.port, rejectUnauthorized: false }, () => {
                this.socket.write('GET / HTTP/1.1\r\n' +
                    'Host: ' + this.host + ':' + this.port + '\r\n' +
                    'Upgrade: websocket\r\nConnection: Upgrade\r\n' +
                    'Sec-WebSocket-Key: ' + wsKey + '\r\nSec-WebSocket-Version: 13\r\n\r\n');
            });
            this.socket.on('error', fail);
            this.socket.on('close', () => this._closed());
            this.socket.on('data', (chunk) => this._data(chunk, fail));
            const timer = setTimeout(() => fail(new Error('The TV did not allow Adaptive Home')),
                PAIR_WAIT_MS);
            this.waiting.register_0 = {
                done: (data) => {
                    const payload = data.payload || {};
                    if (data.type === 'response' && payload.pairingType === 'PROMPT') {
                        return false;   // the TV is asking; wait for "registered"
                    }
                    clearTimeout(timer);
                    if (data.type === 'registered') {
                        this.ready = true;
                        this.key = payload['client-key'] || key;
                        resolve(this.key);
                    } else {
                        fail(new Error(data.error || 'The TV refused Adaptive Home'));
                    }
                    return true;
                },
            };
            this._registerPayload = {
                forcePairing: false, pairingType: 'PROMPT',
                manifest: { manifestVersion: 1, appVersion: '1.0', permissions: PERMISSIONS },
            };
            if (key) this._registerPayload['client-key'] = key;
        });
    }

    _data(chunk, fail) {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        if (!this.upgraded) {
            const end = this.buffer.indexOf('\r\n\r\n');
            if (end < 0) return;
            const status = this.buffer.slice(0, end).toString().split('\r\n')[0];
            if (!/ 101 /.test(status + ' ')) {
                fail(new Error('The TV refused the connection: ' + status));
                return;
            }
            this.upgraded = true;
            this.buffer = this.buffer.slice(end + 4);
            this._send({ type: 'register', id: 'register_0', payload: this._registerPayload });
        }
        const decoded = decodeFrames(this.buffer);
        this.buffer = decoded.rest;
        decoded.frames.forEach((frame) => this._frame(frame));
    }

    _frame(frame) {
        if (frame.opcode === 9) {
            this.socket.write(encodeFrame(frame.payload.toString('utf8'), 10));
            return;
        }
        if (frame.opcode === 8) {
            this.close();
            return;
        }
        if (frame.opcode === 1) this.partial = [frame.payload];
        else if (frame.opcode === 0 && this.partial) this.partial.push(frame.payload);
        else return;
        if (!frame.fin) return;
        const text = Buffer.concat(this.partial).toString('utf8');
        this.partial = null;
        let data;
        try {
            data = JSON.parse(text);
        } catch (error) {
            return;
        }
        const waiting = this.waiting[data.id];
        if (waiting && waiting.done(data) !== false) delete this.waiting[data.id];
    }

    _send(data) {
        if (this.socket) this.socket.write(encodeFrame(JSON.stringify(data)));
    }

    _closed() {
        this.ready = false;
        this.socket = null;
        const waiting = this.waiting;
        this.waiting = {};
        Object.keys(waiting).forEach((id) => waiting[id].done({ type: 'error', error: 'closed' }));
    }

    close() {
        if (this.socket) this.socket.destroy();
        this._closed();
    }

    // Resolves with the reply's payload.
    request(uri, payload) {
        if (!this.ready) return Promise.reject(new Error('Not connected to the TV'));
        return new Promise((resolve, reject) => {
            const id = 'c' + (++this.nextId);
            const timer = setTimeout(() => {
                delete this.waiting[id];
                reject(new Error('The TV did not answer ' + uri));
            }, CALL_WAIT_MS);
            this.waiting[id] = {
                done: (data) => {
                    clearTimeout(timer);
                    const reply = data.payload || {};
                    if (data.type === 'response' && reply.returnValue !== false) resolve(reply);
                    else reject(new Error(data.error || reply.errorText || 'The TV said no'));
                    return true;
                },
            };
            this._send({ type: 'request', id: id, uri: uri, payload: payload || {} });
        });
    }
}

// The TV serves app icons from its own socket port, with the same certificate.
function fetchIcon(url) {
    if (!/^https:\/\/[0-9.]+:3001\/resources\//.test(url || '')) {
        return Promise.reject(new Error('Not a TV icon'));
    }
    return new Promise((resolve, reject) => {
        const request = https.get(url, { rejectUnauthorized: false, timeout: CALL_WAIT_MS }, (reply) => {
            if (reply.statusCode !== 200) {
                reply.resume();
                reject(new Error('Icon answered ' + reply.statusCode));
                return;
            }
            const parts = [];
            reply.on('data', (part) => parts.push(part));
            reply.on('end', () => {
                const type = reply.headers['content-type'] || 'image/png';
                resolve('data:' + type + ';base64,' + Buffer.concat(parts).toString('base64'));
            });
        });
        request.on('timeout', () => request.destroy(new Error('Icon timed out')));
        request.on('error', reject);
    });
}

module.exports = { Tv: Tv, encodeFrame: encodeFrame, decodeFrames: decodeFrames, fetchIcon: fetchIcon,
    PERMISSIONS: PERMISSIONS };
