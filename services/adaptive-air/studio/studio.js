'use strict';
// Kinect Studio: the page. Served by services/adaptive-air/kinect_hub.py on 127.0.0.1:8792.
//
// Each view asks the hub for the frame after the one it last drew (/frame/<kind>.jpg?after=seq),
// so a view runs as fast as the Kinect and the page can, never faster. The point cloud is binary
// (/cloud.bin: u32 count, u32 seq, float32 xyz * n, uint8 rgb * n) drawn as WebGL points.
// Colours come from the stylesheet's custom properties (no colour is written here).

const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function rgbOf(name) {
    const probe = document.createElement('i');
    probe.style.color = css(name);
    document.body.appendChild(probe);
    const m = getComputedStyle(probe).color.match(/[\d.]+/g).map(Number);
    probe.remove();
    return [m[0] / 255, m[1] / 255, m[2] / 255];
}
const post = (name, value) => fetch(`/api/${name}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }),
}).catch(() => {});

let status = null;
let visible = !document.hidden;
document.addEventListener('visibilitychange', () => { visible = !document.hidden; });

// The hub stays up while this page is open (and stops itself a little after it closes).
function presence() {
    const ws = new WebSocket(`ws://${location.host}/presence`);
    ws.onclose = () => setTimeout(presence, 2000);
}
presence();

// ------------------------------------------------------------------ camera views

function streamView(kind, canvas, meta) {
    const ctx = canvas.getContext('2d');
    let seq = 0, count = 0, since = performance.now();
    async function loop() {
        while (true) {
            if (!visible) { await new Promise(r => setTimeout(r, 300)); continue; }
            try {
                const res = await fetch(`/frame/${kind}.jpg?after=${seq}`, { cache: 'no-store' });
                if (res.status !== 200) { await new Promise(r => setTimeout(r, 500)); continue; }
                seq = Number(res.headers.get('X-Seq')) || seq;
                const bitmap = await createImageBitmap(await res.blob());
                ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
                bitmap.close();
                count++;
                const now = performance.now();
                if (now - since > 1000) {
                    meta.textContent = `${(count * 1000 / (now - since)).toFixed(0)} fps · 640×480`;
                    count = 0; since = now;
                }
            } catch (e) {
                await new Promise(r => setTimeout(r, 1000));
            }
        }
    }
    loop();
}
streamView('video', $('video'), $('video-meta'));
streamView('depth', $('depth'), $('depth-meta'));

// ------------------------------------------------------------------ point cloud (WebGL)

const cloud = (() => {
    const canvas = $('cloud');
    const gl = canvas.getContext('webgl', { antialias: true });
    if (!gl) {
        $('cloud-meta').textContent = 'WebGL is not available here';
        return null;
    }
    const vs = `
        attribute vec3 pos; attribute vec3 col;
        uniform mat4 mvp; uniform float size; uniform int byDepth;
        uniform vec3 nearC; uniform vec3 midC; uniform vec3 farC;
        varying vec3 v;
        void main() {
            gl_Position = mvp * vec4(pos.x, -pos.y, -pos.z, 1.0);
            gl_PointSize = size;
            if (byDepth == 1) {
                float t = clamp((pos.z - 0.4) / 3.6, 0.0, 1.0);
                v = t < 0.5 ? mix(nearC, midC, t * 2.0) : mix(midC, farC, t * 2.0 - 1.0);
            } else {
                v = col;
            }
        }`;
    const fs = `precision mediump float; varying vec3 v;
        void main() { vec2 c = gl_PointCoord - 0.5; if (dot(c, c) > 0.25) discard; gl_FragColor = vec4(v, 1.0); }`;
    const shader = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        return s;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, vs));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(prog);
    gl.useProgram(prog);
    const loc = name => gl.getUniformLocation(prog, name);
    const posBuf = gl.createBuffer(), colBuf = gl.createBuffer();
    const aPos = gl.getAttribLocation(prog, 'pos'), aCol = gl.getAttribLocation(prog, 'col');
    gl.uniform3fv(loc('nearC'), rgbOf('--warn'));
    gl.uniform3fv(loc('midC'), rgbOf('--cyan'));
    gl.uniform3fv(loc('farC'), rgbOf('--indigo'));
    gl.enable(gl.DEPTH_TEST);
    const ground = rgbOf('--ground');

    const view = { yaw: 0, pitch: 0, dist: 0.1, tx: 0, ty: 0, tz: -1.6, spin: false };
    const reset = () => Object.assign(view, { yaw: 0, pitch: 0, dist: 0.1, tx: 0, ty: 0, tz: -1.6 });
    let n = 0, seq = 0, byDepth = 0, size = 2, step = 4, last = performance.now();

    function perspective(fovy, aspect, near, far) {
        const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
        return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
    }
    function mul(a, b) {
        const o = new Array(16).fill(0);
        for (let i = 0; i < 4; i++)
            for (let j = 0; j < 4; j++)
                for (let k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k];
        return o;
    }
    const translate = (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];
    const rotX = a => [1, 0, 0, 0, 0, Math.cos(a), Math.sin(a), 0, 0, -Math.sin(a), Math.cos(a), 0, 0, 0, 0, 1];
    const rotY = a => [Math.cos(a), 0, -Math.sin(a), 0, 0, 1, 0, 0, Math.sin(a), 0, Math.cos(a), 0, 0, 0, 0, 1];

    function draw() {
        const dpr = window.devicePixelRatio || 1;
        const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
        if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
        gl.viewport(0, 0, w, h);
        gl.clearColor(ground[0], ground[1], ground[2], 1);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        const now = performance.now();
        if (view.spin) view.yaw += (now - last) / 1000 * 0.4;
        last = now;
        // Orbit around a point 1.6 m in front of the Kinect.
        let m = translate(view.tx, view.ty, -view.dist - 1.6);
        m = mul(m, rotX(view.pitch));
        m = mul(m, rotY(view.yaw));
        m = mul(m, translate(0, 0, 1.6));
        const mvp = mul(perspective(0.9, w / Math.max(1, h), 0.05, 20), m);
        gl.uniformMatrix4fv(loc('mvp'), false, new Float32Array(mvp));
        gl.uniform1f(loc('size'), size * dpr);
        gl.uniform1i(loc('byDepth'), byDepth);
        if (n) gl.drawArrays(gl.POINTS, 0, n);
        requestAnimationFrame(draw);
    }

    async function fetchLoop() {
        let count = 0, since = performance.now();
        while (true) {
            if (!visible) { await new Promise(r => setTimeout(r, 300)); continue; }
            try {
                const res = await fetch(`/cloud.bin?step=${step}&after=${seq}`, { cache: 'no-store' });
                if (res.status !== 200) { await new Promise(r => setTimeout(r, 500)); continue; }
                const buf = await res.arrayBuffer();
                const head = new Uint32Array(buf, 0, 2);
                const count0 = head[0];
                seq = head[1];
                const xyz = new Float32Array(buf, 8, count0 * 3);
                const rgb = new Uint8Array(buf, 8 + count0 * 12, count0 * 3);
                gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
                gl.bufferData(gl.ARRAY_BUFFER, xyz, gl.DYNAMIC_DRAW);
                gl.enableVertexAttribArray(aPos);
                gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
                gl.bindBuffer(gl.ARRAY_BUFFER, colBuf);
                gl.bufferData(gl.ARRAY_BUFFER, rgb, gl.DYNAMIC_DRAW);
                gl.enableVertexAttribArray(aCol);
                gl.vertexAttribPointer(aCol, 3, gl.UNSIGNED_BYTE, true, 0, 0);
                n = count0;
                count++;
                const now = performance.now();
                if (now - since > 1000) {
                    $('cloud-meta').textContent = `${n.toLocaleString()} points · ${(count * 1000 / (now - since)).toFixed(0)} fps`;
                    count = 0; since = now;
                }
            } catch (e) {
                await new Promise(r => setTimeout(r, 1000));
            }
        }
    }

    // Mouse: drag turns, right-drag / shift-drag moves, wheel zooms.
    let drag = null;
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    canvas.addEventListener('pointerdown', e => {
        drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
        canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', e => {
        if (!drag) return;
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        drag.x = e.clientX; drag.y = e.clientY;
        if (drag.pan) {
            view.tx += dx * 0.003 * (1 + view.dist);
            view.ty -= dy * 0.003 * (1 + view.dist);
        } else {
            view.yaw += dx * 0.008;
            view.pitch = Math.max(-1.5, Math.min(1.5, view.pitch + dy * 0.008));
        }
    });
    canvas.addEventListener('pointerup', () => { drag = null; });
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        view.dist = Math.max(-1.4, Math.min(8, view.dist + e.deltaY * 0.002));
    }, { passive: false });

    requestAnimationFrame(draw);
    fetchLoop();
    return {
        setColour: v => { byDepth = v === 'depth' ? 1 : 0; },
        setSize: v => { size = v; },
        setStep: v => { step = v; },
        toggleSpin: () => (view.spin = !view.spin),
        reset,
    };
})();

document.querySelectorAll('[data-colour]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-colour]').forEach(x => x.classList.toggle('on', x === b));
    if (cloud) cloud.setColour(b.dataset.colour);
}));
$('size').addEventListener('input', e => cloud && cloud.setSize(Number(e.target.value)));
$('step').addEventListener('change', e => cloud && cloud.setStep(Number(e.target.value)));
$('spin').addEventListener('click', e => cloud && e.target.classList.toggle('on', cloud.toggleSpin()));
$('reset').addEventListener('click', () => cloud && cloud.reset());

// ------------------------------------------------------------------ controls

document.querySelectorAll('[data-video]').forEach(b => b.addEventListener('click', () => post('video', b.dataset.video)));
document.querySelectorAll('[data-led]').forEach(b => b.addEventListener('click', () => post('led', b.dataset.led)));
document.querySelectorAll('[data-tilt]').forEach(b => b.addEventListener('click', () => {
    $('tilt-set').value = b.dataset.tilt;
    post('tilt', Number(b.dataset.tilt));
}));
$('tilt-set').addEventListener('change', e => post('tilt', Number(e.target.value)));
$('webcam').addEventListener('change', e => post('webcam', e.target.checked));

$('measure').addEventListener('click', async () => {
    $('measure').disabled = true;
    $('you-text').textContent = 'Hold still…';
    try {
        const r = await (await fetch('/api/measure', { cache: 'no-store' })).json();
        $('you-height').textContent = r.ok ? `${r.height.toFixed(2)} m · ${r.feet}′${r.inches}″` : '–';
        $('you-meta').textContent = r.ok ? `${r.distance.toFixed(1)} m away · floor ${r.floor === 'seen' ? 'seen' : 'assumed'}` : '';
        $('you-text').textContent = r.sentence || r.error || '';
    } catch (e) {
        $('you-text').textContent = 'The Kinect hub did not answer.';
    }
    $('measure').disabled = false;
});

// ------------------------------------------------------------------ sensors

function horizon(pitch, roll) {
    const c = $('horizon'), ctx = c.getContext('2d');
    const s = c.width, r = s / 2 - 6;
    ctx.clearRect(0, 0, s, s);
    ctx.save();
    ctx.translate(s / 2, s / 2);
    ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.clip();
    ctx.fillStyle = css('--card'); ctx.fillRect(-s, -s, 2 * s, 2 * s);
    ctx.rotate(-roll * Math.PI / 180);
    const off = Math.max(-r, Math.min(r, pitch / 45 * r));
    ctx.fillStyle = css('--accent'); ctx.globalAlpha = 0.35;
    ctx.fillRect(-s, off, 2 * s, s);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = css('--cyan'); ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(-r, off); ctx.lineTo(r, off); ctx.stroke();
    ctx.restore();
    ctx.strokeStyle = css('--line-2'); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(s / 2, s / 2, r, 0, 2 * Math.PI); ctx.stroke();
    ctx.strokeStyle = css('--white'); ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(s / 2 - 34, s / 2); ctx.lineTo(s / 2 - 12, s / 2);
    ctx.moveTo(s / 2 + 12, s / 2); ctx.lineTo(s / 2 + 34, s / 2); ctx.stroke();
}

function bars(canvas, values, colour) {
    const ctx = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = colour;
    const bw = w / values.length;
    values.forEach((v, i) => ctx.fillRect(i * bw + 1, h - v * h, bw - 2, v * h));
}

const fpsHistory = [];
function spark(fps) {
    fpsHistory.push(fps);
    if (fpsHistory.length > 60) fpsHistory.shift();
    const c = $('spark'), ctx = c.getContext('2d'), w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = css('--accent'); ctx.lineWidth = 2;
    ctx.beginPath();
    fpsHistory.forEach((v, i) => {
        const x = i / 59 * w, y = h - 3 - Math.min(1, v / 32) * (h - 6);
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.stroke();
}

const mm = v => (v == null ? '–' : `${(v / 1000).toFixed(2)} m`);
function setAxis(id, raw) {
    const g = raw / 819;
    const el = $(id);
    const half = Math.min(50, Math.abs(g) * 50);
    el.style.left = g >= 0 ? '50%' : `${50 - half}%`;
    el.style.width = `${half}%`;
    $(`${id}v`).textContent = `${g.toFixed(2)} g`;
}

async function poll() {
    try {
        status = await (await fetch('/api/status', { cache: 'no-store' })).json();
    } catch (e) {
        status = null;
    }
    const pill = $('state');
    pill.className = 'pill';
    if (!status) {
        $('state-text').textContent = 'The Kinect hub is not running';
        pill.classList.add('bad');
    } else {
        const live = status.status === 'streaming';
        pill.classList.add(live ? 'live' : status.status === 'starting' ? 'warn' : 'bad');
        $('state-text').textContent = live
            ? `Kinect ${status.kinect.model} · ${status.fps.toFixed(0)} fps · ${status.mode === 'ir' ? 'infrared' : 'colour'}${status.video === 'auto' ? ' (auto)' : ''}`
            : ({ unpowered: 'Kinect has no power', 'no-kinect': 'No Kinect on USB', starting: 'Starting…' }[status.status] || 'Kinect error');
        const video = status.video || status.mode;
        document.querySelectorAll('.seg [data-video]').forEach(b => b.classList.toggle('on', b.dataset.video === video));
        $('video-title').textContent = (status.mode === 'ir' ? 'Infrared' : 'Colour') +
            (video === 'auto' ? (status.mode === 'ir' ? ' · auto: the room is dark' : ' · auto') : '');
        setAxis('ax', status.accel[0]); setAxis('ay', status.accel[1]); setAxis('az', status.accel[2]);
        $('g').textContent = `${status.g.toFixed(2)} g`;
        $('pitch').textContent = `${status.pitch.toFixed(1)}°`;
        $('roll').textContent = `${status.roll.toFixed(1)}°`;
        horizon(status.pitch, status.roll);
        $('tilt').textContent = status.tilt == null ? '–' : `${status.tilt > 0 ? '+' : ''}${status.tilt.toFixed(1)}°`;
        $('tilt-status').textContent = status.tilt_status || '';
        $('led-now').textContent = status.led || '';
        document.querySelectorAll('[data-led]').forEach(b => b.classList.toggle('on', b.dataset.led === status.led));
        const d = status.depth;
        if (d) {
            $('near').textContent = mm(d.nearest);
            $('median').textContent = mm(d.median);
            $('far').textContent = mm(d.farthest);
            $('valid').textContent = `${d.valid.toFixed(0)}% of pixels`;
            bars($('hist'), d.hist, css('--cyan'));
        }
        $('fps').textContent = `${status.fps.toFixed(1)} fps`;
        spark(status.fps);
        $('frames').textContent = status.seq ? (status.seq / 2).toLocaleString() : '–';
        const cam = status.webcam;
        if (document.activeElement !== $('webcam')) $('webcam').checked = cam.on;
        $('webcam-state').textContent = cam.streaming ? `on · ${cam.device}` : cam.on ? 'starting…' : 'off';
        $('air').textContent = status.air ? 'reading frames' : 'off';
        const dark = video === 'rgb' && status.light != null && status.light < 0.04
            ? 'Too dark for the colour camera (and for finding hands): Auto switches to infrared, which brings its own light.' : null;
        $('dark').hidden = !dark;
        const note = cam.error || (status.status !== 'streaming' ? status.error : null);
        $('note').hidden = !note;
        $('note').textContent = note || '';
    }
    setTimeout(poll, visible ? 250 : 1000);
}
poll();
